"""Minimal private capability pack publisher and retraction mechanism (Issue #16).

The existing research exports (``research export``) are *bibliography dumps*:
``export_jsonl`` copies every ``works`` column — including abstracts,
``raw_sources``, local PDF paths and internal review bookkeeping — into a file
that must never be handed to a consumer plugin. This module builds the
opposite thing: a **field-whitelist knowledge pack** of general professional
assets that can be independently verified, privately distributed and
retracted, per `docs/design/growth-support-mvp/architecture.md` §2/§6 and the
governance rules of CE-GS-01 (``docs/governance/GROWTH-SUPPORT-QUALIFICATION.md``).

Pack layout (immutable full snapshot per build; AGENTS #15 boundary objects):

    ce-pack-<pack_version>/
        manifest.json                  strict-schema manifest (content hashes)
        catalog.jsonl                  whitelisted bibliography metadata
        evidence-cards.jsonl           publishable Claim cards (+ relations,
                                       findings, source versions, appraisals)
        strategies.jsonl               Strategy asset versions (verbatim)
        methods.jsonl                  SupportMethod asset versions
        interaction-profiles.jsonl     InteractionProfile asset versions
        evaluation-cases.jsonl         EvaluationCase asset versions

Key properties (Issue #16 验收条件):

- **Whitelist, not redaction** (AC #1): catalog records are projected onto
  ``CATALOG_FIELDS`` — abstract, raw_sources, local paths, internal review
  fields and child-record fields are *not expressible*. Every packaged record
  is scanned (``scan_record``) for forbidden field names, local filesystem
  paths and credential-shaped strings; unqualified assets are refused in
  release packs (PUB-Eligibility) and demo assets only ever travel in packs
  explicitly marked ``content_class="synthetic_demo"``.
- **Verifiable integrity** (AC #2): the manifest carries per-file sha256 +
  record counts and a ``pack_hash`` over its own canonical body; every asset
  record keeps its ``content_hash`` (assets layer). ``verify_pack``
  recomputes hashes, re-runs the asset-layer strict validation, re-checks
  citation closure, duplicate ids, mixed revisions and schema/runner
  compatibility, and rebuilds the manifest projection for comparison.
- **Snapshot + activation** (AC #3): a pack directory is written once and
  never overwritten (immutability); activation copies the *verified* pack
  into the consumer area and commits it with an atomic ``ACTIVE.json`` write
  (``os.replace``), so a failed activation leaves the previous version intact
  — never a half-activated version.
- **Independent retraction ledger** (AC #3, GS-03): retraction entries live in
  ``retractions.jsonl`` next to ``ACTIVE.json``, are appended independently of
  pack versions, and take precedence over version pinning *and* rollback:
  activating an older pack cannot resurrect a retracted asset.
- **No publisher credentials in packs** (交付范围 #4): the manifest records a
  publisher *reference* with ``authentication: "external"`` and
  ``credentials_embedded: false``; content hashes verify content, publisher
  authentication stays a separate trust channel (architecture.md §3, Issue
  #19 deployment decision). Credential-shaped material anywhere in a pack is
  rejected.

Data semantics are never weakened: retracted assets are excluded at build
time (and reported), the pack never contains PDFs, full text or child
records (AGENTS #8/#14; GS-06), and no code path flips ``release_eligibility``
or review states (AGENTS #23; the builder only *reads* qualification).

No network, no model calls, no third-party dependencies (AGENTS #9). Paths
are ``pathlib`` throughout (AGENTS #12).
"""
from __future__ import annotations

from contextlib import contextmanager
from importlib import resources
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is POSIX-only (Windows lacks it)
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - msvcrt is Windows-only
    msvcrt = None

from . import assets, db, evidence
from .strict_schema import strict_validate as _strict_validate

ISSUE_URL = "https://github.com/lybym/ChildEvidence/issues/16"

# Pack protocol version. The reader refuses packs whose schema_version is not
# in SUPPORTED_PACK_SCHEMA_VERSIONS (PUB-Schema) — new protocol versions are an
# explicit code change, never a silent upgrade.
PACK_SCHEMA_VERSION = "ce.pack/1"
SUPPORTED_PACK_SCHEMA_VERSIONS = ("ce.pack/1",)

# The runner/consumer compatibility floor shipped with this repository. A pack
# may declare a higher min_runner; readers older than that refuse the pack
# (PUB-Runner) instead of mis-reading unknown structures.
RUNNER_VERSION = "0.1.0"

CONTENT_CLASSES = ("synthetic_demo", "research_assets")

# Build modes map onto manifest content classes: release packs carry real
# qualified assets; synthetic-demo packs carry demo_only fixtures only.
CONTENT_CLASS_FOR_MODE = {"release": "research_assets",
                          "synthetic_demo": "synthetic_demo"}
# CLI spelling ("synthetic-demo") → canonical build mode.
MODE_FOR_CLI_FLAG = {"release": "release", "synthetic-demo": "synthetic_demo"}

JSONL_FILES = ("catalog.jsonl", "evidence-cards.jsonl", "strategies.jsonl",
               "methods.jsonl", "interaction-profiles.jsonl", "evaluation-cases.jsonl")

ASSET_FILE_FOR_KIND = {
    "strategy": "strategies.jsonl",
    "support_method": "methods.jsonl",
    "interaction_profile": "interaction-profiles.jsonl",
    "evaluation_case": "evaluation-cases.jsonl",
}
KIND_FOR_FILE = {file: kind for kind, file in ASSET_FILE_FOR_KIND.items()}

DEFAULT_PUBLISHER_REF = "childevidence-local-publisher"

# ---------------------------------------------------------------------------
# Whitelist (AC #1): what a catalog record may carry. Everything else in
# ``works`` — abstract, raw_sources, local_pdf_path, review bookkeeping,
# extraction fields — stays in the research library and never enters a pack.
# ---------------------------------------------------------------------------

CATALOG_FIELDS = (
    "internal_id", "doi", "pmid", "pmcid", "openalex_id", "eric_id", "s2_id",
    "title", "authors", "publication_date", "publication_year",
    "journal_or_publisher", "volume", "issue", "pages", "issn", "language",
    "document_type", "research_domains", "topic_tags", "peer_review_status",
    "metadata_status", "access_status", "license", "retraction_status",
    "expression_of_concern", "canonical_url", "record_status",
)

# Exact field names that must never appear in ANY packaged record (AC #1:
# 摘要 / 原文 / raw_sources / 本机路径 / 凭据 / 儿童记录). This is a defense
# net behind the whitelist projection — the scan runs on every record of
# every pack file at build *and* verify time. Works-internal bookkeeping
# fields that are *legitimate* elsewhere (e.g. ``review_status`` and
# ``limitations`` are required envelope/appraisal fields of assets and
# evidence cards) live in WORK_FORBIDDEN_FIELD_NAMES instead and are checked
# only for catalog records.
FORBIDDEN_FIELD_NAMES = frozenset({
    # literature text / research-extraction fields (stay in the library)
    "abstract", "main_findings", "effect_size", "research_question",
    "study_design", "population", "participant_age_range",
    "sample_size", "geographic_context", "evidence_category",
    "applicability_to_lumithink", "theoretical_frameworks",
    # provenance / local machine data
    "raw_sources", "local_pdf_path", "pdf_url", "source_urls", "sha256",
    "pdf_version", "pdf_file_size", "pdf_page_count", "retrieval_errors",
    "discovery_source", "query_key", "discovered_at", "last_checked_at",
    "downloaded_at",
    # internal review bookkeeping (works sense; asset/card review fields differ)
    "reviewer_notes", "conflicting_metadata",
    "unverified_claims", "human_review_required", "title_norm",
    "first_author_surname", "merge_conflict", "ingestion_notes",
    "cited_by_count",
    # credentials / child records (AGENTS #14, GS-06)
    "api_key", "secret", "password", "token", "private_key", "credential",
    "subject_ref", "child_profile", "student_record", "growth_record",
    "diagnosis_record", "personal_record",
})

# Bibliography-internal fields: forbidden in catalog records; the *same names*
# are required fields of the asset envelope (``review_status``) and of
# evidence appraisals (``limitations``), so they must not be blanket-banned.
WORK_FORBIDDEN_FIELD_NAMES = frozenset({"review_status", "limitations"})

_FORBIDDEN_KEY_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"abstract", r"raw_source", r"local_path", r"pdf_path", r"credential",
    r"password", r"secret", r"\btoken", r"api_key", r"private_key",
    r"subject_ref", r"child_profile", r"growth_record", r"diagnosis",
))

# String values: local machine paths and credential-shaped material are
# rejected wherever they hide (AC #1). Repo-relative doc pointers such as
# "docs/design/..." are data references, not local paths, and stay legal.
_WINDOWS_DRIVE_RE = re.compile(r"\b[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\")
_POSIX_USER_PATH_RE = re.compile(r"(?:^|[\s\"'=(\[])/(?:home|Users|root|var|tmp|mnt|opt)/")
_SECRET_RES = (
    re.compile(r"\bgh[posr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
)

_CONTENT_HASH_RE = re.compile(r"^sha256=[0-9a-f]{64}$")


class PublishError(ValueError):
    """Raised for any rejected pack operation (rule id PUB-* in the message)."""


# ---------------------------------------------------------------------------
# Scanning (AC #1)
# ---------------------------------------------------------------------------

def validate_catalog_whitelist(fields) -> None:
    """Fail fast if the catalog whitelist itself carries a forbidden field.

    The whitelist is the load-bearing wall of the publisher: if a future edit
    adds ``abstract`` or ``raw_sources`` to ``CATALOG_FIELDS``, the pack would
    silently start leaking library text. This check runs on every build and is
    directly testable against fraudulent lists.
    """
    field_set = set(fields)
    if field_set != set(CATALOG_FIELDS):
        unknown = sorted(field_set - set(CATALOG_FIELDS))
        missing = sorted(set(CATALOG_FIELDS) - field_set)
        raise PublishError(
            f"PUB-Whitelist: catalog whitelist must be exactly CATALOG_FIELDS "
            f"(unknown additions {unknown}; missing {missing})")
    all_forbidden = FORBIDDEN_FIELD_NAMES | WORK_FORBIDDEN_FIELD_NAMES
    for field in fields:
        if field in all_forbidden or any(p.search(field) for p in _FORBIDDEN_KEY_PATTERNS):
            raise PublishError(
                f"PUB-Whitelist: catalog field {field!r} is forbidden "
                "(abstracts/raw_sources/paths/credentials/child records never enter packs)")


def scan_value(value, label: str, errors: list[str]) -> None:
    """Scan one JSON value (recursively) for local paths and credentials."""
    if isinstance(value, str):
        if _WINDOWS_DRIVE_RE.search(value) or _UNC_PATH_RE.search(value) \
                or _POSIX_USER_PATH_RE.search(value):
            errors.append(
                f"{label}: local filesystem path detected in a packaged string "
                "(PUB-LocalPath; packs are machine-independent)")
        for pattern in _SECRET_RES:
            if pattern.search(value):
                errors.append(
                    f"{label}: credential-shaped material detected "
                    "(PUB-Secret; publisher credentials never travel with packs)")
    elif isinstance(value, dict):
        for key, item in value.items():
            scan_value(item, label, errors)
    elif isinstance(value, list):
        for item in value:
            scan_value(item, label, errors)


def scan_record(record, label: str, errors: list[str], *,
                catalog_record: bool = False) -> None:
    """Scan one packaged record: forbidden field names + value-level content.

    ``catalog_record=True`` additionally rejects the works-internal field names
    that a catalog entry must never carry (``review_status``/``limitations``
    are legitimate asset-envelope/appraisal fields and are only banned here).
    """
    if not isinstance(record, dict):
        errors.append(f"{label}: packaged record is not an object (PUB-Manifest)")
        return
    forbidden = FORBIDDEN_FIELD_NAMES | (WORK_FORBIDDEN_FIELD_NAMES if catalog_record
                                         else frozenset())
    for key in record:
        if key in forbidden:
            errors.append(
                f"{label}: forbidden field {key!r} in a packaged record "
                "(PUB-Whitelist; the pack whitelist must not be bypassed)")
        elif any(pattern.search(key) for pattern in _FORBIDDEN_KEY_PATTERNS):
            errors.append(
                f"{label}: forbidden field pattern in {key!r} "
                "(PUB-Whitelist; abstracts/raw_sources/paths/credentials/child "
                "records never enter packs)")
    scan_value(record, label, errors)


# ---------------------------------------------------------------------------
# Manifest (strict schema + recomputable projection)
# ---------------------------------------------------------------------------

def load_manifest_schema() -> dict:
    """Load the packaged strict manifest schema via importlib.resources."""
    resource = resources.files("research_library.contracts.publish").joinpath(
        "manifest.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pack_hash(manifest_body: dict) -> str:
    canonical = _canonical(manifest_body)
    return "sha256=" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _version_tuple(version: str) -> tuple:
    try:
        return tuple(int(part) for part in str(version).split("."))
    except (TypeError, ValueError):
        return (0, 0, 0)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expected_projection(records_by_file: dict) -> dict:
    """Recompute the file/counts/rights projection from packaged records.

    Used by the builder to create the manifest and by verify to recompute it:
    identical inputs must yield an identical projection (AC #2 哈希和清单可重算).
    """
    catalog = records_by_file.get("catalog.jsonl") or []
    files = []
    for name in JSONL_FILES:
        records = records_by_file.get(name) or []
        payload = "".join(_canonical(record) + "\n" for record in records)
        files.append({"name": name, "sha256": _sha256_bytes(payload.encode("utf-8")),
                      "record_count": len(records)})
    files.sort(key=lambda entry: entry["name"])
    counts = {
        "catalog": len(catalog),
        "evidence_cards": len(records_by_file.get("evidence-cards.jsonl") or []),
    }
    for kind in assets.KINDS:
        counts[kind] = len(records_by_file.get(ASSET_FILE_FOR_KIND[kind]) or [])
    license_unknown = sum(
        1 for entry in catalog
        if not isinstance(entry, dict) or entry.get("license") in (None, "", "license_unknown"))
    rights = {
        "redistribution_scope": "metadata_only",
        "full_text_included": False,
        "abstracts_included": False,
        "license_unknown_count": license_unknown,
    }
    return {"files": files, "counts": counts, "rights": rights}


def _manifest_body(records_by_file: dict, *, pack_version: str, content_class: str,
                   publisher_ref: str, built_at: str) -> dict:
    projection = _expected_projection(records_by_file)
    body = {
        "schema_version": PACK_SCHEMA_VERSION,
        "pack_version": pack_version,
        "pack_id": f"ce-pack-{pack_version}",
        "content_class": content_class,
        "eligible_for_real_user_delivery": False,
        "built_at": built_at,
        "publisher": {"publisher_ref": publisher_ref,
                      "authentication": "external",
                      "credentials_embedded": False},
        "compatibility": {"assets_schema": assets.SCHEMA_VERSION,
                          "evidence_schema": evidence.SCHEMA_VERSION,
                          "min_runner": RUNNER_VERSION},
        "counts": projection["counts"],
        "rights": projection["rights"],
        "files": projection["files"],
    }
    return body


# ---------------------------------------------------------------------------
# Collection (pack content from the library database)
# ---------------------------------------------------------------------------

def _project_work(row: sqlite3.Row) -> dict:
    """Project one works row onto CATALOG_FIELDS (whitelist, not redaction)."""
    full = db.row_to_dict(row)
    projected = {}
    for field in CATALOG_FIELDS:
        value = full.get(field)
        projected[field] = value
    return projected


def _card_for_claim(conn: sqlite3.Connection, claim_id: str) -> dict:
    claim = conn.execute(
        "SELECT claim_id, statement, scope, research_question_id, created_at"
        " FROM evidence_claims WHERE claim_id=?", (claim_id,)).fetchone()
    if claim is None:
        raise PublishError(
            f"PUB-Closure: appraisal targets claim {claim_id!r} which does not exist")
    appraisals = [dict(r) for r in conn.execute(
        "SELECT appraisal_id, target_kind, target_id, quality, biases, limitations,"
        " applicability, review_origin, review_status, release_eligibility, created_at"
        " FROM evidence_appraisals WHERE target_kind='claim' AND target_id=?"
        " ORDER BY appraisal_id", (claim_id,)).fetchall()]
    relations = [dict(r) for r in conn.execute(
        "SELECT relation_id, finding_id, relation FROM evidence_relations"
        " WHERE claim_id=? ORDER BY relation_id", (claim_id,)).fetchall()]
    finding_ids = sorted({r["finding_id"] for r in relations})
    findings, source_versions = [], []
    for finding_id in finding_ids:
        row = conn.execute(
            "SELECT finding_id, statement, study_id, source_version_id,"
            " research_question_id, created_at FROM evidence_findings"
            " WHERE finding_id=?", (finding_id,)).fetchone()
        if row is not None:
            findings.append(dict(row))
    version_ids = sorted({f["source_version_id"] for f in findings})
    for version_id in version_ids:
        row = conn.execute(
            "SELECT version_id, work_id, study_id, source_kind, original_version,"
            " locator_status, origin FROM evidence_source_versions"
            " WHERE version_id=?", (version_id,)).fetchone()
        if row is not None:
            source_versions.append(dict(row))
    findings.sort(key=lambda f: f["finding_id"])
    source_versions.sort(key=lambda sv: sv["version_id"])
    return {
        "schema_version": evidence.SCHEMA_VERSION,
        "claim": {key: claim[key] for key in
                  ("claim_id", "statement", "scope", "research_question_id", "created_at")},
        "relations": relations,
        "findings": findings,
        "source_versions": source_versions,
        "appraisals": appraisals,
    }


def collect_records(conn: sqlite3.Connection, mode: str) -> dict:
    """Collect the pack content for one full snapshot (release or synthetic demo).

    Release mode selects only assets with ``lifecycle_status='released'`` and
    ``release_eligibility='eligible'`` (qualification is read, never granted,
    by this module — GS-01/02/05 stay with governance). Synthetic-demo mode
    selects only ``demo_only`` assets (never retracted) so the engineering
    pack stays separated from real qualification (Issue #16 共同范围). Evidence
    cards are built only from claims whose appraisal records
    ``release_eligibility='eligible'`` (AGENTS #20: unapproved evidence never
    enters a published pack).
    """
    if mode == "release":
        asset_where = "lifecycle_status='released' AND release_eligibility='eligible' AND demo_only=0"
    elif mode == "synthetic_demo":
        asset_where = "demo_only=1 AND lifecycle_status<>'retracted'"
    else:
        raise PublishError(f"PUB-Mode: unknown pack mode {mode!r}")

    records: dict[str, list] = {name: [] for name in JSONL_FILES}
    stats = {"mode": mode, "excluded": {}}

    # Assets, one revision per asset id (a full snapshot never mixes revisions).
    for kind in assets.KINDS:
        table = assets.TABLES[kind]
        rows = conn.execute(
            f"SELECT asset_id, revision FROM {table} WHERE {asset_where}"
            " ORDER BY asset_id, revision").fetchall()
        selected = [assets.get_record(conn, kind, row["asset_id"], row["revision"])
                    for row in rows]
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        stats["excluded"][kind] = max(total - len(selected), 0)
        records[ASSET_FILE_FOR_KIND[kind]] = selected

    # Catalog: closure works cited by included assets and evidence cards.
    work_ids: set[str] = set()
    for kind in assets.KINDS:
        for record in records[ASSET_FILE_FOR_KIND[kind]]:
            for ref in record.get("basis_refs") or []:
                if isinstance(ref, dict) and ref.get("ref_kind") == "work":
                    work_ids.add(ref.get("ref"))

    if mode == "release":
        # Evidence cards: claims with at least one eligible appraisal.
        eligible_rows = conn.execute(
            "SELECT DISTINCT target_id FROM evidence_appraisals"
            " WHERE target_kind='claim' AND release_eligibility='eligible'"
            " ORDER BY target_id").fetchall()
        eligible_claim_ids = [row["target_id"] for row in eligible_rows]
        claim_total = conn.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0]
        stats["excluded"]["evidence_claims"] = max(claim_total - len(eligible_claim_ids), 0)
        cards = [_card_for_claim(conn, claim_id) for claim_id in eligible_claim_ids]
        for card in cards:
            for sv in card["source_versions"]:
                work_ids.add(sv["work_id"])
        records["evidence-cards.jsonl"] = cards
    else:
        records["evidence-cards.jsonl"] = []
        stats["excluded"]["evidence_claims"] = conn.execute(
            "SELECT COUNT(*) FROM evidence_claims").fetchone()[0]

    work_ids.discard(None)
    catalog = []
    missing = []
    for work_id in sorted(work_ids):
        row = conn.execute(
            "SELECT * FROM works WHERE internal_id=? AND record_status='ingested'",
            (work_id,)).fetchone()
        if row is None:
            missing.append(work_id)
        else:
            catalog.append(_project_work(row))
    if missing:
        raise PublishError(
            "PUB-Closure: cited works are missing from the catalog closure or are "
            f"not ingested: {missing} (citation closure must resolve inside the pack)")
    records["catalog.jsonl"] = catalog
    stats["counts_hint"] = {name: len(items) for name, items in records.items()}
    return {"records": records, "stats": stats}


# ---------------------------------------------------------------------------
# Build (full immutable snapshot)
# ---------------------------------------------------------------------------

def _build_validations(records: dict, mode: str) -> None:
    """Pre-write validations shared with verify: scan, dup, mixed, eligibility,
    closure. Raises :class:`PublishError` on the first violated rule group."""
    errors: list[str] = []
    for name in JSONL_FILES:
        for index, record in enumerate(records.get(name) or []):
            scan_record(record, f"{name}[{index}]", errors,
                        catalog_record=(name == "catalog.jsonl"))
    if errors:
        raise PublishError("pack content rejected: " + "; ".join(errors[:5]))

    _check_duplicates(records)
    _check_eligibility(records, mode)
    closure_errors = _closure_errors(records)
    if closure_errors:
        raise PublishError("pack content rejected: " + "; ".join(closure_errors[:5]))


def _asset_entries(records: dict) -> list[tuple[str, dict]]:
    entries = []
    for name in ("strategies.jsonl", "methods.jsonl",
                 "interaction-profiles.jsonl", "evaluation-cases.jsonl"):
        for record in records.get(name) or []:
            if not isinstance(record, dict):
                continue  # malformed records are reported by scan_record
            entries.append((KIND_FOR_FILE[name], record))
    return entries


def _check_duplicates(records: dict) -> None:
    seen_catalog = set()
    for record in records.get("catalog.jsonl") or []:
        if not isinstance(record, dict):
            continue  # malformed records are reported by scan_record
        key = record.get("internal_id")
        if key in seen_catalog:
            raise PublishError(f"PUB-Dup: duplicate catalog entry {key!r}")
        seen_catalog.add(key)
    seen_claims = set()
    for record in records.get("evidence-cards.jsonl") or []:
        if not isinstance(record, dict):
            continue
        key = record.get("claim", {}).get("claim_id") if isinstance(
            record.get("claim"), dict) else None
        if key in seen_claims:
            raise PublishError(f"PUB-Dup: duplicate evidence card {key!r}")
        seen_claims.add(key)
    seen_assets: dict[str, str] = {}
    for kind, record in _asset_entries(records):
        asset_id, revision = record.get("asset_id"), record.get("revision")
        key = (kind, asset_id, revision)
        if key in seen_assets:
            raise PublishError(f"PUB-Dup: duplicate asset {kind} {asset_id!r}@{revision}")
        if asset_id in seen_assets and seen_assets[asset_id] != kind:
            raise PublishError(
                f"PUB-Dup: asset id {asset_id!r} appears in more than one asset kind "
                f"({seen_assets[asset_id]} and {kind})")
        seen_assets[asset_id] = kind
    for name, kind in KIND_FOR_FILE.items():
        revisions: dict[str, int] = {}
        for record in records.get(name) or []:
            if not isinstance(record, dict):
                continue
            asset_id = record.get("asset_id")
            if asset_id in revisions:
                raise PublishError(
                    f"PUB-MixedRevision: pack contains revisions "
                    f"{revisions[asset_id]} and {record.get('revision')} of {kind} "
                    f"{asset_id!r} — a full snapshot carries exactly one revision "
                    "per asset (no mixed-version reading)")
            revisions[asset_id] = record.get("revision")


def _check_eligibility(records: dict, mode: str) -> None:
    """Qualification gate at build time (AC #1: 未获资格资产被拒绝).

    Release packs may only carry released + eligible + non-demo assets — the
    builder *reads* qualification, it never grants it (GS-01/02/05 stay with
    governance). Synthetic-demo packs may only carry ``demo_only`` fixtures,
    so a synthetic engineering pack can never be mistaken for a real one.
    Retracted assets are refused in both modes (GS-03).
    """
    for kind, record in _asset_entries(records):
        label = f"{kind} {record.get('asset_id')}@{record.get('revision')}"
        if record.get("lifecycle_status") == "retracted":
            raise PublishError(
                f"PUB-Eligibility: retracted asset {label} must never be packaged (GS-03)")
        if mode == "release":
            if record.get("demo_only"):
                raise PublishError(
                    f"PUB-Eligibility: demo asset {label} is refused in a release pack "
                    "(demo fixtures carry no real qualification; build a "
                    "content_class=synthetic_demo pack instead)")
            if record.get("lifecycle_status") != "released" \
                    or record.get("release_eligibility") != "eligible":
                raise PublishError(
                    f"PUB-Eligibility: unqualified asset {label} "
                    f"(lifecycle_status={record.get('lifecycle_status')!r}, "
                    f"release_eligibility={record.get('release_eligibility')!r}) — "
                    "release packs carry only released + eligible assets")
        elif mode == "synthetic_demo" and not record.get("demo_only"):
            raise PublishError(
                f"PUB-Eligibility: non-demo asset {label} is refused in a synthetic "
                "demo pack (synthetic packs carry demo_only fixtures only)")


def _closure_errors(records: dict) -> list[str]:
    catalog_ids = {entry.get("internal_id")
                   for entry in records.get("catalog.jsonl") or []
                   if isinstance(entry, dict)}
    card_ids = {card.get("claim", {}).get("claim_id")
                for card in records.get("evidence-cards.jsonl") or []
                if isinstance(card, dict) and isinstance(card.get("claim"), dict)}
    version_ids = set()
    for card in records.get("evidence-cards.jsonl") or []:
        if not isinstance(card, dict):
            continue
        for sv in card.get("source_versions") or []:
            version_ids.add(sv.get("version_id"))
    evaluation_refs_index = set()
    for record in records.get("evaluation-cases.jsonl") or []:
        if isinstance(record, dict):
            evaluation_refs_index.add((record.get("asset_id"), record.get("revision")))
    asset_versions = {(kind, record.get("asset_id"), record.get("revision"))
                      for kind, record in _asset_entries(records)}

    errors: list[str] = []
    for kind, record in _asset_entries(records):
        label = f"{kind} {record.get('asset_id')}@{record.get('revision')}"
        for ref in record.get("basis_refs") or []:
            if not isinstance(ref, dict):
                continue
            ref_kind, ref_value = ref.get("ref_kind"), ref.get("ref")
            if ref_kind == "work" and ref_value not in catalog_ids:
                errors.append(
                    f"PUB-Closure: {label} cites work {ref_value!r} that is not in "
                    "catalog.jsonl (citation closure)")
            elif ref_kind == "claim" and ref_value not in card_ids:
                errors.append(
                    f"PUB-Closure: {label} cites claim {ref_value!r} that has no "
                    "evidence card in the pack (citation closure)")
            elif ref_kind == "source_version" and ref_value not in version_ids:
                errors.append(
                    f"PUB-Closure: {label} cites source version {ref_value!r} that is "
                    "not carried by any evidence card (citation closure)")
            elif ref_kind == "evaluation_case" and not any(
                    case_id == ref_value for case_id, _ in evaluation_refs_index):
                errors.append(
                    f"PUB-Closure: {label} cites evaluation case {ref_value!r} that is "
                    "not in evaluation-cases.jsonl (citation closure)")
        for ref in record.get("evaluation_refs") or []:
            if isinstance(ref, dict) and (ref.get("case_id"), ref.get("revision")) \
                    not in evaluation_refs_index:
                errors.append(
                    f"PUB-Closure: {label} cites evaluation case "
                    f"{ref.get('case_id')!r}@{ref.get('revision')} that is not in "
                    "evaluation-cases.jsonl (citation closure)")
    for record in records.get("evaluation-cases.jsonl") or []:
        if not isinstance(record, dict):
            continue
        label = f"evaluation_case {record.get('asset_id')}@{record.get('revision')}"
        for cover in record.get("covers") or []:
            if not isinstance(cover, dict):
                continue
            target_id, target_revision = cover.get("asset_id"), cover.get("revision")
            if not any(asset_id == target_id and revision == target_revision
                       for _, asset_id, revision in asset_versions):
                errors.append(
                    f"PUB-Closure: {label} covers asset {target_id!r}@{target_revision} "
                    "that is not part of the pack (evaluation closure)")
    # Evidence cards must also resolve inside the pack: every source version a
    # card carries cites a work, and that work must be in catalog.jsonl. The
    # builder guarantees this (``collect_records`` adds card works to the
    # catalog closure); this check keeps hand-assembled or re-stamped packs to
    # the same rule at verify time (AC #2: 缺失引用失败).
    for card in records.get("evidence-cards.jsonl") or []:
        if not isinstance(card, dict):
            continue
        claim = card.get("claim")
        claim_label = claim.get("claim_id") if isinstance(claim, dict) else None
        for sv in card.get("source_versions") or []:
            if not isinstance(sv, dict):
                continue
            work_id = sv.get("work_id")
            if work_id not in catalog_ids:
                errors.append(
                    f"PUB-Closure: evidence card {claim_label!r} carries source "
                    f"version {sv.get('version_id')!r} whose work {work_id!r} is not "
                    "in catalog.jsonl (citation closure)")
    return errors


def build_pack(conn: sqlite3.Connection, pack_version: str, *,
               mode: str = "release",
               publisher_ref: str = DEFAULT_PUBLISHER_REF,
               packs_dir: Path, built_at: str | None = None) -> dict:
    """Build one full immutable pack snapshot into ``packs_dir``.

    Fails closed: whitelist scan, duplicate/mixed-revision, eligibility and
    citation-closure checks run before anything is written; the pack directory
    is refused if it already exists (snapshots are immutable, never rewritten);
    a failed write cleans up the partial directory. The finished pack is
    verified with :func:`verify_pack` before being reported.
    """
    if not isinstance(pack_version, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", pack_version):
        raise PublishError(
            f"PUB-Manifest: pack_version {pack_version!r} must match "
            "[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
    validate_catalog_whitelist(CATALOG_FIELDS)
    packs_dir = Path(packs_dir)
    pack_dir = packs_dir / f"ce-pack-{pack_version}"
    if pack_dir.exists():
        raise PublishError(
            f"PUB-Immutable: pack directory {pack_dir} already exists — packs are "
            "full immutable snapshots and are never overwritten (build a new "
            "pack_version instead)")

    collected = collect_records(conn, mode)
    records = collected["records"]
    _build_validations(records, mode)

    body = _manifest_body(records, pack_version=pack_version,
                          content_class=CONTENT_CLASS_FOR_MODE[mode],
                          publisher_ref=publisher_ref,
                          built_at=built_at or _now_iso())
    manifest = {**body, "pack_hash": _pack_hash(body)}

    packs_dir.mkdir(parents=True, exist_ok=True)
    staging = packs_dir / f".staging-{uuid4().hex[:8]}"
    staging.mkdir()
    try:
        for name in JSONL_FILES:
            payload = "".join(_canonical(record) + "\n"
                              for record in records.get(name) or [])
            # Write bytes, not text: text mode would translate \n to os.linesep
            # on Windows and invalidate the hash computed over the LF payload.
            (staging / name).write_bytes(payload.encode("utf-8"))
        (staging / "manifest.json").write_bytes(
            (json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
             + "\n").encode("utf-8"))
        report = verify_pack(staging)
        if not report["ok"]:
            raise PublishError(
                "PUB-Manifest: freshly built pack failed verification: "
                + "; ".join(report["errors"][:5]))
        staging.rename(pack_dir)
    except PublishError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "pack_dir": str(pack_dir),
        "pack_id": manifest["pack_id"],
        "pack_version": pack_version,
        "content_class": manifest["content_class"],
        "pack_hash": manifest["pack_hash"],
        "counts": manifest["counts"],
        "rights": manifest["rights"],
        "excluded": collected["stats"]["excluded"],
    }


# ---------------------------------------------------------------------------
# Verify (AC #2: missing citations, tampering, duplicate ids, incompatible
# versions, mixed versions all fail; hashes and manifest recomputable)
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path, errors: list[str]) -> list:
    records = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"{path.name}: unreadable ({error}) (PUB-Hash)")
        return records
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            errors.append(
                f"{path.name}:{line_number}: invalid JSON ({error}) (PUB-Manifest)")
    return records


def verify_pack(pack_dir: Path, *, runner_version: str = RUNNER_VERSION,
                supported_pack_schemas: tuple = SUPPORTED_PACK_SCHEMA_VERSIONS) -> dict:
    """Fully verify one pack directory; returns a report with ``ok``/``errors``.

    Recomputes every file hash, re-runs the asset-layer strict validation
    (including each record's ``content_hash``), re-checks duplicate ids, mixed
    revisions, citation closure and schema/runner compatibility, rebuilds the
    manifest projection and the ``pack_hash`` — every mismatch is a named
    ``PUB-*`` error, nothing is silently repaired.
    """
    pack_dir = Path(pack_dir)
    errors: list[str] = []
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "pack_dir": str(pack_dir), "errors":
                ["manifest.json is missing (PUB-Manifest)"], "pack_id": None,
                "pack_version": None, "content_class": None, "pack_hash": None,
                "counts": None}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"ok": False, "pack_dir": str(pack_dir), "errors":
                [f"manifest.json unreadable/invalid: {error} (PUB-Manifest)"],
                "pack_id": None, "pack_version": None, "content_class": None,
                "pack_hash": None, "counts": None}

    schema_errors: list[str] = []
    _strict_validate(manifest, load_manifest_schema(), "manifest", schema_errors)
    errors.extend(f"{error} (PUB-Manifest)" for error in schema_errors)

    scan_value(manifest, "manifest", errors)  # value-level: paths/credentials

    present_files = {entry.name for entry in pack_dir.iterdir() if entry.is_file()}
    allowed = set(JSONL_FILES) | {"manifest.json"}
    for foreign in sorted(present_files - allowed):
        errors.append(
            f"foreign file {foreign!r} in pack directory (PUB-ForeignFile; the pack "
            "carries exactly the manifest files)")
    for stray in sorted(entry.name for entry in pack_dir.iterdir()
                        if not entry.is_file()):
        errors.append(
            f"stray directory entry {stray!r} in pack directory (PUB-ForeignFile)")

    records_by_file: dict[str, list] = {}
    manifest_files = {entry.get("name"): entry for entry in manifest.get("files") or []}
    for name in JSONL_FILES:
        path = pack_dir / name
        if not path.exists():
            errors.append(f"{name}: missing pack file (PUB-Hash)")
            continue
        data = path.read_bytes()
        digest = _sha256_bytes(data)
        records = _read_jsonl(path, errors)
        records_by_file[name] = records
        entry = manifest_files.get(name)
        if entry is None:
            errors.append(f"{name}: not listed in the manifest (PUB-Manifest)")
        else:
            if entry.get("sha256") != digest:
                errors.append(
                    f"{name}: file sha256 mismatch — manifest {entry.get('sha256')!r} "
                    f"!= recomputed {digest!r} (PUB-Hash; the file was modified after "
                    "the pack was built)")
            if entry.get("record_count") != len(records):
                errors.append(
                    f"{name}: record_count mismatch — manifest "
                    f"{entry.get('record_count')} != recomputed {len(records)} "
                    "(PUB-Hash)")

    for name in JSONL_FILES:
        for index, record in enumerate(records_by_file.get(name) or []):
            scan_record(record, f"{name}[{index}]", errors,
                        catalog_record=(name == "catalog.jsonl"))
        kind = KIND_FOR_FILE.get(name)
        if kind is None:
            continue
        for record in records_by_file.get(name) or []:
            if not isinstance(record, dict):
                continue
            asset_errors = assets.validate_record(kind, record)
            errors.extend(
                f"{name} {record.get('asset_id')}@{record.get('revision')}: {error} "
                "(PUB-Record)" for error in asset_errors)

    _dup_and_mixed_into(records_by_file, errors)
    errors.extend(_closure_errors(records_by_file))
    errors.extend(_eligibility_errors(records_by_file,
                                      manifest.get("content_class")))

    # Recomputable projection: identical records must rebuild these fields.
    projection = _expected_projection(records_by_file)
    if manifest.get("counts") != projection["counts"]:
        errors.append(
            f"manifest counts {manifest.get('counts')!r} != recomputed "
            f"{projection['counts']!r} (PUB-Manifest)")
    if manifest.get("rights") != projection["rights"]:
        errors.append(
            f"manifest rights {manifest.get('rights')!r} != recomputed "
            f"{projection['rights']!r} (PUB-Manifest)")
    if manifest.get("files") != projection["files"]:
        errors.append(
            "manifest files section != recomputed from pack records (PUB-Manifest)")

    body = {key: value for key, value in manifest.items() if key != "pack_hash"}
    recomputed_hash = _pack_hash(body)
    if manifest.get("pack_hash") != recomputed_hash:
        errors.append(
            f"pack_hash mismatch — manifest {manifest.get('pack_hash')!r} != recomputed "
            f"{recomputed_hash!r} (PUB-Manifest; the manifest body was modified)")

    if manifest.get("schema_version") not in supported_pack_schemas:
        errors.append(
            f"pack schema_version {manifest.get('schema_version')!r} is not supported "
            f"(supported: {list(supported_pack_schemas)}) (PUB-Schema)")
    compatibility = manifest.get("compatibility") or {}
    if compatibility.get("assets_schema") != assets.SCHEMA_VERSION:
        errors.append(
            f"pack assets_schema {compatibility.get('assets_schema')!r} != reader "
            f"{assets.SCHEMA_VERSION!r} (PUB-Schema; incompatible pack)")
    if compatibility.get("evidence_schema") != evidence.SCHEMA_VERSION:
        errors.append(
            f"pack evidence_schema {compatibility.get('evidence_schema')!r} != reader "
            f"{evidence.SCHEMA_VERSION!r} (PUB-Schema; incompatible pack)")
    min_runner = compatibility.get("min_runner")
    if isinstance(min_runner, str) and _version_tuple(runner_version) < _version_tuple(min_runner):
        errors.append(
            f"runner version {runner_version!r} is below the pack minimum "
            f"{min_runner!r} (PUB-Runner; incompatible pack)")

    return {
        "ok": not errors,
        "pack_dir": str(pack_dir),
        "pack_id": manifest.get("pack_id"),
        "pack_version": manifest.get("pack_version"),
        "content_class": manifest.get("content_class"),
        "pack_hash": manifest.get("pack_hash"),
        "counts": manifest.get("counts"),
        "errors": errors,
    }


def _dup_and_mixed_into(records: dict, errors: list[str]) -> None:
    try:
        _check_duplicates(records)
    except PublishError as error:
        errors.append(str(error))


def _eligibility_errors(records: dict, content_class) -> list[str]:
    """Pack-level qualification scan (AC #1: 未获资格资产在包内被拒绝).

    A ``research_assets`` pack may only carry released + eligible + non-demo
    asset versions; a ``synthetic_demo`` pack may only carry demo fixtures;
    retracted records are refused everywhere (GS-03). Build-time selection
    already enforces this from the database; this scan catches tampered or
    hand-crafted packs at verify time — the same rule, checked against the
    manifest's declared content class.
    """
    errors: list[str] = []
    if content_class not in CONTENT_CLASSES:
        return errors  # schema diagnostics already flag the unknown class
    for kind, record in _asset_entries(records):
        label = f"{kind} {record.get('asset_id')}@{record.get('revision')}"
        if record.get("lifecycle_status") == "retracted":
            errors.append(
                f"{label}: retracted asset must never appear in a pack (PUB-Eligibility; GS-03)")
            continue
        if content_class == "research_assets":
            if record.get("demo_only"):
                errors.append(
                    f"{label}: demo fixture inside a research_assets pack "
                    "(PUB-Eligibility; synthetic content never travels with real "
                    "qualification)")
            elif record.get("lifecycle_status") != "released" \
                    or record.get("release_eligibility") != "eligible":
                errors.append(
                    f"{label}: unqualified asset (lifecycle_status="
                    f"{record.get('lifecycle_status')!r}, release_eligibility="
                    f"{record.get('release_eligibility')!r}) inside a research_assets "
                    "pack (PUB-Eligibility; release packs carry only released + "
                    "eligible assets)")
        elif content_class == "synthetic_demo" and not record.get("demo_only"):
            errors.append(
                f"{label}: non-demo asset inside a synthetic_demo pack "
                "(PUB-Eligibility; synthetic packs carry demo fixtures only)")
    return errors


# ---------------------------------------------------------------------------
# Activation + independent retraction ledger (AC #3)
# ---------------------------------------------------------------------------

_ACTIVE_FILE = "ACTIVE.json"
_RETRACTIONS_FILE = "retractions.jsonl"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Durably replace ``path`` with ``data``: write tmp → fsync → ``os.replace``.

    ``os.replace`` alone is atomic but not durable — after a power loss the
    pointer/ledger file may vanish even though the write "succeeded". The tmp
    file is flushed to disk before the swap; on POSIX the containing directory
    is fsynced too so the rename itself survives (best-effort; NTFS journals
    metadata and directory handles cannot be opened on Windows).
    """
    tmp_path = path.parent / (path.name + f".tmp-{uuid4().hex[:8]}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(tmp_path, flags, 0o666)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, path)
    if os.name == "posix":
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # best effort: some filesystems refuse directory fsync


@contextmanager
def _ledger_lock(consumer_dir: Path):
    """Serialize retraction-ledger read-modify-write cycles across processes.

    ``append_retraction`` is append-only in content but implemented as
    read → validate → rewrite; two concurrent retractions would otherwise each
    start from the same stale snapshot and the later ``os.replace`` would
    silently drop the earlier withdrawal — and one lost withdrawal is exactly
    the "rollback resurrects a retracted asset" window this ledger exists to
    prevent. An exclusive OS-level lock on a sidecar lock file closes that
    race (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows; both
    stdlib, AGENTS #9).
    """
    lock_path = Path(consumer_dir) / (_RETRACTIONS_FILE + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def activate_pack(pack_dir: Path, consumer_dir: Path) -> dict:
    """Atomically activate a verified pack in a consumer area.

    The pack is verified *first*; then copied under ``<consumer>/packs/`` via a
    staging directory; only after a complete, hash-identical copy exists is
    ``ACTIVE.json`` replaced atomically (``os.replace``). A failure anywhere
    before that swap leaves the previous activation untouched — no half
    version is ever active, and previously activated packs stay available for
    rollback (failure/rollback: atomic switch back while retraction constraints
    hold; history is never deleted).
    """
    report = verify_pack(pack_dir)
    if not report["ok"]:
        raise PublishError(
            "PUB-Hash: activation refused — the pack failed verification: "
            + "; ".join(report["errors"][:5]))

    consumer_dir = Path(consumer_dir)
    packs_root = consumer_dir / "packs"
    dest = packs_root / report["pack_id"]
    packs_root.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # An existing pack id is immutable; reading its manifest is how we
        # detect an attempt to re-use the id with different content. A damaged
        # manifest must surface as a named PUB-* error, not a raw
        # ``json.JSONDecodeError`` traceback.
        try:
            existing = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PublishError(
                f"PUB-Hash: pack id {report['pack_id']!r} already exists in the "
                "consumer area but its manifest.json is unreadable/invalid: "
                f"{error} — pack ids are immutable; refusing to touch the damaged "
                "directory (repair or remove it manually)") from error
        if existing.get("pack_hash") != report["pack_hash"]:
            raise PublishError(
                f"PUB-Hash: pack id {report['pack_id']!r} already exists in the "
                "consumer area with a different content hash — pack ids are "
                "immutable; refusing to mix versions")
    else:
        staging = packs_root / f".staging-{report['pack_id']}-{uuid4().hex[:8]}"
        staging.mkdir()
        try:
            for name in sorted(set(JSONL_FILES) | {"manifest.json"}):
                shutil.copyfile(Path(pack_dir) / name, staging / name)
            copied = verify_pack(staging)
            if not copied["ok"]:
                raise PublishError(
                    "PUB-Hash: copied pack failed verification: "
                    + "; ".join(copied["errors"][:5]))
            staging.rename(dest)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    active = {
        "pack_id": report["pack_id"],
        "pack_version": report["pack_version"],
        "pack_hash": report["pack_hash"],
        "activated_at": _now_iso(),
    }
    _atomic_write_bytes(
        consumer_dir / _ACTIVE_FILE,
        (json.dumps(active, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return {"active": active, "consumer_dir": str(consumer_dir),
            "pack_dir": str(dest)}


def read_active(consumer_dir: Path) -> dict:
    """Load and fully verify the active pack of a consumer area.

    The active pointer must match the pack's content hash (a swapped-in
    directory of a different version without re-activation is refused — no
    mixed-version reading across packs).
    """
    consumer_dir = Path(consumer_dir)
    active_path = consumer_dir / _ACTIVE_FILE
    if not active_path.exists():
        raise PublishError(
            f"PUB-Active: no active pack in {consumer_dir} (activate a pack first)")
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError(f"PUB-Active: ACTIVE.json unreadable/invalid: {error}") from error
    if not isinstance(active, dict) or not active.get("pack_id") \
            or not active.get("pack_hash"):
        raise PublishError("PUB-Active: ACTIVE.json is missing pack_id/pack_hash")
    pack_dir = consumer_dir / "packs" / active["pack_id"]
    if not pack_dir.exists():
        raise PublishError(
            f"PUB-Active: active pack directory {pack_dir} does not exist")
    report = verify_pack(pack_dir)
    if not report["ok"]:
        raise PublishError(
            "PUB-Hash: active pack failed verification: "
            + "; ".join(report["errors"][:5]))
    if report["pack_hash"] != active["pack_hash"]:
        raise PublishError(
            "PUB-Active: ACTIVE.json points at a different content version than the "
            f"pack directory carries (active {active['pack_hash']!r} vs pack "
            f"{report['pack_hash']!r}) — re-activate after changing packs; mixed "
            "versions are never read")
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    return {"active": active, "manifest": manifest, "report": report,
            "pack_dir": pack_dir}


def load_retractions(consumer_dir: Path) -> list[dict]:
    """Load the append-only retraction ledger (missing file = empty ledger)."""
    path = Path(consumer_dir) / _RETRACTIONS_FILE
    if not path.exists():
        return []
    entries = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise PublishError(
                f"PUB-Retract: retractions.jsonl:{line_number} invalid JSON: {error}") from error
        _validate_retraction_entry(entry, f"retractions.jsonl:{line_number}")
        entries.append(entry)
    return entries


def _validate_retraction_entry(entry, label: str) -> None:
    if not isinstance(entry, dict):
        raise PublishError(f"PUB-Retract: {label} entry is not an object")
    required = {"asset_id", "revision", "content_hash", "reason",
                "decision_ref", "retracted_at"}
    if set(entry) != required:
        raise PublishError(
            f"PUB-Retract: {label} entry fields {sorted(entry)} != {sorted(required)}")
    if not isinstance(entry["asset_id"], str) or not entry["asset_id"].strip():
        raise PublishError(f"PUB-Retract: {label} asset_id must be a non-empty string")
    revision = entry["revision"]
    if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool)
                                 or revision < 1):
        raise PublishError(
            f"PUB-Retract: {label} revision must be a positive integer or null "
            "(null withdraws every revision of the asset)")
    content_hash = entry["content_hash"]
    if content_hash is not None and (not isinstance(content_hash, str)
                                     or not _CONTENT_HASH_RE.match(content_hash)):
        raise PublishError(
            f"PUB-Retract: {label} content_hash must be 'sha256=<64 hex>' or null")
    for field in ("reason", "decision_ref"):
        if not isinstance(entry[field], str) or not entry[field].strip():
            raise PublishError(
                f"PUB-Retract: {label} {field} must be a non-empty string (GS-03: "
                "append-style withdrawal with explicit reason and decision ref)")
    if not isinstance(entry["retracted_at"], str) or not entry["retracted_at"].strip():
        raise PublishError(f"PUB-Retract: {label} retracted_at must be a timestamp")


def append_retraction(consumer_dir: Path, *, asset_id: str, reason: str,
                      decision_ref: str, revision: int | None = None,
                      content_hash: str | None = None,
                      at: str | None = None) -> dict:
    """Append one withdrawal record to the independent retraction ledger.

    The ledger is independent of pack versions (Issue #16 交付范围 #4): it is
    updated without touching ACTIVE.json or any pack file, and it is
    append-only — entries are never deleted or rewritten (GS-03; AGENTS #2
    spirit). ``revision=None`` withdraws *every* revision of the asset, which
    is what makes rollback unable to resurrect the asset. Duplicate withdrawal
    of the same (asset_id, revision) is rejected, matching the terminal
    semantics of ``assets.retract_asset``. The read-check-rewrite cycle runs
    under an exclusive cross-process lock (:func:`_ledger_lock`), so two
    concurrent retractions can never silently drop each other's entry, and
    the rewrite is fsynced before the atomic swap (:func:`_atomic_write_bytes`).
    """
    entry = {
        "asset_id": asset_id,
        "revision": revision,
        "content_hash": content_hash,
        "reason": reason,
        "decision_ref": decision_ref,
        "retracted_at": at or _now_iso(),
    }
    _validate_retraction_entry(entry, "new entry")
    consumer_dir = Path(consumer_dir)
    consumer_dir.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(consumer_dir):
        existing = load_retractions(consumer_dir)
        for previous in existing:
            if previous["asset_id"] == asset_id and previous["revision"] == revision:
                raise PublishError(
                    f"PUB-Retract: {asset_id!r}@{revision} is already withdrawn "
                    f"({previous['retracted_at']}; {previous['reason']!r}) — withdrawal "
                    "is append-only and terminal, never deleted or reversed")
        path = consumer_dir / _RETRACTIONS_FILE
        payload = "".join(_canonical(previous) + "\n" for previous in existing)
        payload += _canonical(entry) + "\n"
        _atomic_write_bytes(path, payload.encode("utf-8"))
    return {"entry": entry, "ledger_size": len(existing) + 1,
            "ledger_path": str(path)}


def _retraction_blockers(retractions: list[dict], record: dict) -> list[dict]:
    blockers = []
    for entry in retractions:
        if entry["asset_id"] != record.get("asset_id"):
            continue
        if entry["revision"] is not None and entry["revision"] != record.get("revision"):
            continue
        if entry["content_hash"] is not None \
                and entry["content_hash"] != record.get("content_hash"):
            continue
        scope = "asset-wide" if entry["revision"] is None else "revision-specific"
        blockers.append({
            "code": "PUB-Retracted",
            "detail": f"withdrawn via the independent retraction ledger ({scope}): "
                      f"{entry['reason']} [{entry['decision_ref']}]",
        })
        break
    return blockers


def resolve_assets(consumer_dir: Path) -> dict:
    """Resolve every asset in the active pack against the retraction ledger.

    Retraction information takes precedence over version pinning and rollback:
    the ledger is consulted no matter which pack version is active, so an
    older pack activated after a withdrawal cannot make the asset usable
    again. Pack-level honesty blockers (synthetic class, demo fixtures, draft
    lifecycle) are reported alongside, mirroring the asset layer's
    ``asset_blockers`` semantics at the pack boundary.
    """
    active = read_active(consumer_dir)
    manifest = active["manifest"]
    retractions = load_retractions(consumer_dir)
    synthetic_pack = manifest["content_class"] == "synthetic_demo"
    results = []
    for name in ("strategies.jsonl", "methods.jsonl",
                 "interaction-profiles.jsonl", "evaluation-cases.jsonl"):
        kind = KIND_FOR_FILE[name]
        for record in _read_jsonl(active["pack_dir"] / name, []):
            ref = f"{record.get('asset_id')}@{record.get('revision')}"
            blockers = _retraction_blockers(retractions, record)
            if synthetic_pack:
                blockers.append({
                    "code": "PUB-SyntheticPack",
                    "detail": "pack is content_class=synthetic_demo; synthetic packs "
                              "are never used with real users (Issue #16 不做事项)"})
            if record.get("demo_only"):
                blockers.append({
                    "code": "PUB-DemoAsset",
                    "detail": "demo-only synthetic fixture; never for real users"})
            if record.get("lifecycle_status") in ("draft", "superseded"):
                blockers.append({
                    "code": "PUB-Lifecycle",
                    "detail": f"lifecycle_status={record.get('lifecycle_status')!r}; "
                              "only released assets drive behavior"})
            results.append({
                "kind": kind,
                "asset_ref": ref,
                "asset_id": record.get("asset_id"),
                "revision": record.get("revision"),
                "content_hash": record.get("content_hash"),
                "title": record.get("title"),
                "blocked": bool(blockers),
                "blockers": blockers,
                "usable": not blockers,
            })
    results.sort(key=lambda item: (item["kind"], item["asset_ref"]))
    return {
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "content_class": manifest["content_class"],
        "retraction_count": len(retractions),
        "assets": results,
        "usable_count": sum(1 for item in results if item["usable"]),
        "blocked_count": sum(1 for item in results if not item["usable"]),
    }


def pack_status(consumer_dir: Path) -> dict:
    """Active pack summary: identity, counts, rights, retraction ledger size."""
    active = read_active(consumer_dir)
    manifest = active["manifest"]
    retractions = load_retractions(consumer_dir)
    return {
        "consumer_dir": str(consumer_dir),
        "active": active["active"],
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "content_class": manifest["content_class"],
        "eligible_for_real_user_delivery": manifest["eligible_for_real_user_delivery"],
        "counts": manifest["counts"],
        "rights": manifest["rights"],
        "publisher": manifest["publisher"],
        "retraction_count": len(retractions),
    }


# ---------------------------------------------------------------------------
# Diff report (交付范围 #3: full snapshot + diff report)
# ---------------------------------------------------------------------------

def diff_packs(from_dir: Path, to_dir: Path) -> dict:
    """Diff two verified packs (both are fully verified first)."""
    from_report = verify_pack(from_dir)
    if not from_report["ok"]:
        raise PublishError(
            "PUB-Hash: diff source pack failed verification: "
            + "; ".join(from_report["errors"][:5]))
    to_report = verify_pack(to_dir)
    if not to_report["ok"]:
        raise PublishError(
            "PUB-Hash: diff target pack failed verification: "
            + "; ".join(to_report["errors"][:5]))

    def _asset_map(pack_dir: Path) -> dict:
        mapping = {}
        for name in ("strategies.jsonl", "methods.jsonl",
                     "interaction-profiles.jsonl", "evaluation-cases.jsonl"):
            for record in _read_jsonl(Path(pack_dir) / name, []):
                mapping[record.get("asset_id")] = {
                    "kind": KIND_FOR_FILE[name],
                    "revision": record.get("revision"),
                    "content_hash": record.get("content_hash"),
                }
        return mapping

    from_assets, to_assets = _asset_map(from_dir), _asset_map(to_dir)
    added = sorted(set(to_assets) - set(from_assets))
    removed = sorted(set(from_assets) - set(to_assets))
    changed = sorted(
        asset_id for asset_id in set(from_assets) & set(to_assets)
        if from_assets[asset_id] != to_assets[asset_id])

    def _ids(pack_dir: Path, name: str, key: str) -> set:
        return {record.get(key) for record in _read_jsonl(Path(pack_dir) / name, [])}

    def _claim_ids(pack_dir: Path) -> set:
        # Evidence cards nest the claim under ``claim`` (see ``_card_for_claim``
        # and ``_check_duplicates``); a top-level ``claim_id`` key would read
        # ``None`` for every card and silently report an empty delta.
        ids = set()
        for record in _read_jsonl(Path(pack_dir) / "evidence-cards.jsonl", []):
            if isinstance(record, dict) and isinstance(record.get("claim"), dict):
                ids.add(record["claim"].get("claim_id"))
        return ids

    catalog_added = sorted(_ids(to_dir, "catalog.jsonl", "internal_id")
                           - _ids(from_dir, "catalog.jsonl", "internal_id"))
    catalog_removed = sorted(_ids(from_dir, "catalog.jsonl", "internal_id")
                             - _ids(to_dir, "catalog.jsonl", "internal_id"))
    cards_added = sorted(_claim_ids(to_dir) - _claim_ids(from_dir))
    cards_removed = sorted(_claim_ids(from_dir) - _claim_ids(to_dir))
    return {
        "from": {"pack_id": from_report["pack_id"], "pack_hash": from_report["pack_hash"],
                 "content_class": from_report["content_class"]},
        "to": {"pack_id": to_report["pack_id"], "pack_hash": to_report["pack_hash"],
               "content_class": to_report["content_class"]},
        "assets_added": [{"asset_id": asset_id, **to_assets[asset_id]} for asset_id in added],
        "assets_removed": [{"asset_id": asset_id, **from_assets[asset_id]} for asset_id in removed],
        "assets_changed": [{"asset_id": asset_id, "from": from_assets[asset_id],
                            "to": to_assets[asset_id]} for asset_id in changed],
        "catalog_added": catalog_added,
        "catalog_removed": catalog_removed,
        "evidence_cards_added": cards_added,
        "evidence_cards_removed": cards_removed,
    }
