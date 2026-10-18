"""Evidence/Claim research semantic layer (Issue #14).

Domain model, strict validation entry and additive SQLite storage for the
research semantic layer on top of the existing bibliographic ``works`` table:

- Work (existing ``works`` row) vs **SourceVersion** (one concrete version of a
  source document bound to a Work: original version/hash, parsed version/hash,
  locator verification status). Works without DOI (reports, surveys) are
  first-class: every relation references ``works.internal_id``, never a DOI.
- **Study** grouping with study↔report links, so the same study published in
  several reports is counted once, never double-counted as independent
  evidence.
- **Research questions (RQ)**, **Findings**, **Claims**, evidence **relations**
  (supports / refutes / insufficient) and **Appraisals** — with scientific
  quality, human-review origin and release eligibility kept orthogonal
  (documents contracts.md §1.1; mirrors GS-01/GS-02: AI consistency never
  self-qualifies for release).
- **Locator checks** are append-only events; only an explicit verified check
  sets ``locator_status='verified'``. Bbox/coordinate *detection* records
  ``result='detected'`` and never upgrades the status — bbox presence is not
  accuracy (Issue #14 交付范围 #2; CE-03 boundary, AGENTS #20).

Strictness (Issue #14 验收 #2): records carry ``schema_version`` (const
``ce.evidence/1``); every schema sets ``additionalProperties: false``; numeric
bounds, duplicate keys, wrong references and wrong versions are rejected with
explicit ``EV-*`` rule ids. The governance mini-validator
(``research_library.governance.validate``) ignores ``additionalProperties``
and numeric bounds — it is intentionally NOT used as the strict entry here.

Schema changes are additive only (``CREATE TABLE IF NOT EXISTS``): the
``works`` table and all audit/history tables are untouched. Migration entry:
:func:`migrate_with_backup` (backup first via the SQLite backup API, then
apply, then verify) — Issue #14 失败与回滚. Compatibility reading of legacy
data is unchanged (see tests/test_evidence_model.py).

No network, no model calls, no third-party dependencies (AGENTS #9). This
module never fabricates research content: a record either carries verified
data or ``null``/unknown. Nothing here sets ``release_eligibility='eligible'``
automatically; release decisions stay governed by CE-GS-01 (GS-01…GS-06).
"""
from __future__ import annotations

from importlib import resources
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .governance import HUMAN_REVIEW_ORIGINS
from .astra_pilot import ISSUE_URL as PILOT_ISSUE_URL
from .strict_schema import strict_validate as _strict_validate

SCHEMA_VERSION = "ce.evidence/1"

KINDS = ("research_question", "study", "study_report", "source_version",
         "finding", "claim", "relation", "appraisal", "locator_check")

TABLES = {
    "research_question": "evidence_research_questions",
    "study": "evidence_studies",
    "study_report": "evidence_study_reports",
    "source_version": "evidence_source_versions",
    "finding": "evidence_findings",
    "claim": "evidence_claims",
    "relation": "evidence_relations",
    "appraisal": "evidence_appraisals",
    "locator_check": "evidence_locator_checks",
}

ID_FIELD = {
    "research_question": "rq_id",
    "study": "study_id",
    "study_report": None,
    "source_version": "version_id",
    "finding": "finding_id",
    "claim": "claim_id",
    "relation": "relation_id",
    "appraisal": "appraisal_id",
    "locator_check": "check_id",
}

JSON_COLUMNS = {"finding": ("attributes",)}

# Locator methods that only detect the *presence* of coordinates. Their result
# is recorded but must never be recorded as 'verified' (bbox presence ≠ accuracy).
BBOX_ONLY_METHODS = ("bbox_detection", "bbox_presence", "coords_detected")

_AUDIT_SCHEMA_PREFIX = "astra-pilot-audit/"
_SHA_RE = re.compile(r"^sha256=([0-9a-f]{64})$")

# Additive DDL. Never touches works/ or any existing table (AGENTS #2, #11).
EVIDENCE_DDL = """
CREATE TABLE IF NOT EXISTS evidence_research_questions (
  rq_id TEXT PRIMARY KEY,
  statement TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_studies (
  study_id TEXT PRIMARY KEY,
  study_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_study_reports (
  study_id TEXT NOT NULL REFERENCES evidence_studies(study_id),
  work_id TEXT NOT NULL REFERENCES works(internal_id),
  report_role TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (study_id, work_id)
);

CREATE TABLE IF NOT EXISTS evidence_source_versions (
  version_id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL REFERENCES works(internal_id),
  study_id TEXT REFERENCES evidence_studies(study_id),
  source_kind TEXT NOT NULL,
  original_version TEXT,
  original_sha256 TEXT,
  parsed_sha256 TEXT,
  parsed_format TEXT,
  locator_status TEXT NOT NULL DEFAULT 'unknown',
  origin TEXT NOT NULL,
  origin_ref TEXT,
  created_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_findings (
  finding_id TEXT PRIMARY KEY,
  study_id TEXT NOT NULL REFERENCES evidence_studies(study_id),
  source_version_id TEXT NOT NULL REFERENCES evidence_source_versions(version_id),
  research_question_id TEXT REFERENCES evidence_research_questions(rq_id),
  statement TEXT NOT NULL,
  attributes TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  notes TEXT,
  UNIQUE (study_id, source_version_id, statement)
);

CREATE TABLE IF NOT EXISTS evidence_claims (
  claim_id TEXT PRIMARY KEY,
  research_question_id TEXT REFERENCES evidence_research_questions(rq_id),
  statement TEXT NOT NULL,
  scope TEXT,
  created_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_relations (
  relation_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES evidence_claims(claim_id),
  finding_id TEXT NOT NULL REFERENCES evidence_findings(finding_id),
  relation TEXT NOT NULL CHECK (relation IN ('supports','refutes','insufficient')),
  created_at TEXT NOT NULL,
  notes TEXT,
  UNIQUE (claim_id, finding_id)
);

CREATE TABLE IF NOT EXISTS evidence_appraisals (
  appraisal_id TEXT PRIMARY KEY,
  target_kind TEXT NOT NULL CHECK (target_kind IN ('finding','claim')),
  target_id TEXT NOT NULL,
  quality TEXT,
  biases TEXT,
  limitations TEXT,
  applicability TEXT,
  review_origin TEXT,
  review_status TEXT NOT NULL DEFAULT 'not_reviewed',
  release_eligibility TEXT NOT NULL DEFAULT 'not_eligible',
  created_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_locator_checks (
  check_id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES evidence_source_versions(version_id),
  method TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('verified','failed','detected')),
  details TEXT,
  created_at TEXT NOT NULL
);
"""


class EvidenceError(ValueError):
    """Raised for any rejected evidence record (strict validation or storage rule)."""


# ---------------------------------------------------------------------------
# Strict schema loading + validation (Issue #14 验收 #2 / #3)
#
# The strict JSON-Schema-subset validator (``additionalProperties: false``,
# numeric bounds, patterns, const/enum) lives in ``research_library.strict_schema``
# since Issue #15 so the professional-assets layer shares the exact same
# rejection semantics; see that module for the implementation notes.
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, dict] = {}


def load_schema(kind: str) -> dict:
    """Load the packaged strict schema for ``kind`` via importlib.resources.

    Loading goes through the package resource reader, so it works in a
    relocated/installed copy of ``research_library`` without the repository
    checkout (Issue #14 验收 #3).
    """
    if kind not in KINDS:
        raise EvidenceError(f"unknown evidence record kind: {kind!r}")
    if kind not in _SCHEMA_CACHE:
        resource = resources.files("research_library.contracts.evidence").joinpath(
            f"{kind}.schema.json")
        _SCHEMA_CACHE[kind] = json.loads(resource.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[kind]


def schema_path(kind: str) -> str:
    """Filesystem path of the packaged schema (diagnostics/tests)."""
    return str(resources.files("research_library.contracts.evidence").joinpath(
        f"{kind}.schema.json"))


def validate_record(kind: str, record: dict) -> list[str]:
    """Strictly validate one evidence record; returns the error list (empty = valid).

    Envelope: the record must carry ``schema_version == ce.evidence/1``
    (declared ``required`` + ``const`` in the packaged schema). Record-level
    cross-field rules beyond the JSON schema are appended here so the entry
    stays usable without a database connection.
    """
    schema = load_schema(kind)
    errors: list[str] = []
    _strict_validate(record, schema, kind, errors)
    if kind == "appraisal" and isinstance(record, dict):
        eligibility = record.get("release_eligibility", "not_eligible")
        origin = record.get("review_origin")
        review_status = record.get("review_status", "not_reviewed")
        if eligibility == "eligible" and (
                origin not in HUMAN_REVIEW_ORIGINS or review_status != "human_reviewed"):
            errors.append(
                "EV-Release: release_eligibility='eligible' requires a human review origin "
                f"({', '.join(HUMAN_REVIEW_ORIGINS)}) and review_status='human_reviewed'; "
                "AI origins never self-qualify (GS-02, AGENTS #18)")
    if kind == "locator_check" and isinstance(record, dict):
        method = record.get("method") or ""
        result = record.get("result")
        if result == "verified" and method in BBOX_ONLY_METHODS:
            errors.append(
                f"EV-Locator: method {method!r} only detects coordinate presence and must "
                "never be recorded as result='verified' (bbox presence is not accuracy)")
        if result == "verified" and not (record.get("details") or "").strip():
            errors.append("EV-Locator: result='verified' requires a non-empty details statement")
    if kind == "source_version" and isinstance(record, dict):
        if record.get("parsed_sha256") and not record.get("parsed_format"):
            errors.append(
                "EV-Fields: parsed_sha256 without parsed_format is not an honest binding; "
                "record the parsed format or keep both null")
    return errors


# ---------------------------------------------------------------------------
# Storage (additive, append-only; explicit rejection of duplicates/bad refs)
# ---------------------------------------------------------------------------

# kind -> [(field, table, column)] reference checks (EV-Ref)
_REFERENCE_RULES = {
    "study_report": [("study_id", "evidence_studies", "study_id"),
                     ("work_id", "works", "internal_id")],
    "source_version": [("work_id", "works", "internal_id")],
    "finding": [("study_id", "evidence_studies", "study_id"),
                ("source_version_id", "evidence_source_versions", "version_id")],
    "claim": [],
    "relation": [("claim_id", "evidence_claims", "claim_id"),
                 ("finding_id", "evidence_findings", "finding_id")],
    "locator_check": [("version_id", "evidence_source_versions", "version_id")],
}

_NULLABLE_REFERENCE_RULES = {
    "source_version": [("study_id", "evidence_studies", "study_id")],
    "finding": [("research_question_id", "evidence_research_questions", "rq_id")],
    "claim": [("research_question_id", "evidence_research_questions", "rq_id")],
}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_refs(conn: sqlite3.Connection, kind: str, record: dict) -> None:
    rules = list(_REFERENCE_RULES.get(kind, ())) + list(_NULLABLE_REFERENCE_RULES.get(kind, ()))
    for field, table, column in rules:
        value = record.get(field)
        if value is None:
            continue
        row = conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (value,)).fetchone()
        if row is None:
            raise EvidenceError(
                f"EV-Ref: {kind}.{field}={value!r} does not exist in {table}.{column}")


def _check_version_conflict(conn: sqlite3.Connection, record: dict) -> None:
    """Wrong-version rejection (EV-Version).

    A SourceVersion whose ``original_sha256`` is byte-identical to the Work's
    recorded original file (``works.sha256``) must also declare the same
    version label as the Work record (``works.pdf_version``). A *different*
    file (different hash — e.g. a preprint alongside the published version) is
    a legitimate second SourceVersion of the same Work and is not rejected.
    """
    if record.get("original_version") is None or record.get("original_sha256") is None:
        return
    row = conn.execute("SELECT pdf_version, sha256 FROM works WHERE internal_id=?",
                       (record["work_id"],)).fetchone()
    if row is None:
        return  # EV-Ref reports the missing work
    bound_version, bound_sha256 = row
    if (bound_sha256 and record["original_sha256"] == bound_sha256
            and bound_version and bound_version != record["original_version"]):
        raise EvidenceError(
            f"EV-Version: source_version declares original_version="
            f"{record['original_version']!r} but binds the Work's recorded original file "
            f"(sha256 {bound_sha256[:12]}…) whose pdf_version is {bound_version!r} "
            f"for work {record['work_id']!r}; correct the version label or bind a "
            "different file version")


def _check_duplicates(conn: sqlite3.Connection, kind: str, record: dict) -> None:
    if kind == "study_report":
        row = conn.execute(
            "SELECT 1 FROM evidence_study_reports WHERE study_id=? AND work_id=?",
            (record["study_id"], record["work_id"])).fetchone()
        if row is not None:
            raise EvidenceError(
                f"EV-Dup: study_report ({record['study_id']!r}, {record['work_id']!r}) already exists")
        return
    id_field = ID_FIELD[kind]
    table = TABLES[kind]
    row = conn.execute(f"SELECT 1 FROM {table} WHERE {id_field}=?",
                       (record[id_field],)).fetchone()
    if row is not None:
        raise EvidenceError(f"EV-Dup: {kind} {id_field}={record[id_field]!r} already exists")


_COLUMNS: dict[str, tuple[str, ...]] = {
    "research_question": ("rq_id", "statement", "version", "status", "created_at", "notes"),
    "study": ("study_id", "study_key", "created_at", "notes"),
    "study_report": ("study_id", "work_id", "report_role", "created_at"),
    "source_version": ("version_id", "work_id", "study_id", "source_kind", "original_version",
                       "original_sha256", "parsed_sha256", "parsed_format", "locator_status",
                       "origin", "origin_ref", "created_at", "notes"),
    "finding": ("finding_id", "study_id", "source_version_id", "research_question_id",
                "statement", "attributes", "created_at", "notes"),
    "claim": ("claim_id", "research_question_id", "statement", "scope", "created_at", "notes"),
    "relation": ("relation_id", "claim_id", "finding_id", "relation", "created_at", "notes"),
    "appraisal": ("appraisal_id", "target_kind", "target_id", "quality", "biases", "limitations",
                  "applicability", "review_origin", "review_status", "release_eligibility",
                  "created_at", "notes"),
    "locator_check": ("check_id", "version_id", "method", "result", "details", "created_at"),
}

_DEFAULTS = {
    "research_question": {"status": "active"},
    "study": {"study_key": None, "notes": None},
    "study_report": {"report_role": None},
    "source_version": {"study_id": None, "original_version": None, "original_sha256": None,
                       "parsed_sha256": None, "parsed_format": None, "locator_status": "unknown",
                       "origin_ref": None, "notes": None},
    "finding": {"research_question_id": None, "attributes": {}, "notes": None},
    "claim": {"research_question_id": None, "scope": None, "notes": None},
    "relation": {"notes": None},
    "appraisal": {"quality": None, "biases": None, "limitations": None, "applicability": None,
                  "review_origin": None, "review_status": "not_reviewed",
                  "release_eligibility": "not_eligible", "notes": None},
    "locator_check": {"details": None},
}


def insert_record(conn: sqlite3.Connection, kind: str, record: dict) -> dict:
    """Validate then insert one evidence record; returns the stored row dict.

    Strict path: fill defaults → strict schema validation → EV-Ref reference
    checks → EV-Version conflict checks → EV-Dup duplicate checks → INSERT.
    Any problem raises :class:`EvidenceError` with an explicit ``EV-*`` rule;
    nothing is silently passed or partially written (the caller's transaction
    decides whether to roll back other statements).
    """
    if kind not in KINDS:
        raise EvidenceError(f"unknown evidence record kind: {kind!r}")
    stored = {**_DEFAULTS.get(kind, {}), **record}
    stored.setdefault("schema_version", SCHEMA_VERSION)
    stored["created_at"] = stored.get("created_at") or _now_iso()
    errors = validate_record(kind, stored)
    if errors:
        raise EvidenceError(f"{kind} rejected: " + "; ".join(errors))
    if kind == "appraisal":
        table = ("evidence_findings" if stored["target_kind"] == "finding"
                 else "evidence_claims")
        id_col = "finding_id" if stored["target_kind"] == "finding" else "claim_id"
        row = conn.execute(f"SELECT 1 FROM {table} WHERE {id_col}=?",
                           (stored["target_id"],)).fetchone()
        if row is None:
            raise EvidenceError(
                f"EV-Ref: appraisal.target_id={stored['target_id']!r} does not exist in {table}")
    else:
        _require_refs(conn, kind, stored)
    if kind == "source_version":
        _check_version_conflict(conn, stored)
    _check_duplicates(conn, kind, stored)

    columns = _COLUMNS[kind]
    values = []
    for col in columns:
        value = stored.get(col)
        if kind in JSON_COLUMNS and col in JSON_COLUMNS[kind] and value is not None:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        values.append(value)
    placeholders = ", ".join("?" for _ in columns)
    try:
        conn.execute(
            f"INSERT INTO {TABLES[kind]} ({', '.join(columns)}) VALUES ({placeholders})", values)
    except sqlite3.IntegrityError as error:
        # UNIQUE/CHECK constraints are the last line of defense; convert them
        # into an explicit rejection instead of a raw sqlite error.
        raise EvidenceError(f"EV-Dup: {kind} rejected by a database constraint: {error}") from error
    conn.commit()
    id_field = ID_FIELD[kind]
    if id_field is None:  # composite-key kinds (study_report) have no single id
        return stored
    return get_record(conn, kind, stored[id_field])


def get_record(conn: sqlite3.Connection, kind: str, record_id: str) -> dict | None:
    table = TABLES[kind]
    id_field = ID_FIELD[kind]
    row = conn.execute(f"SELECT * FROM {table} WHERE {id_field}=?", (record_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    if kind in JSON_COLUMNS:
        for col in JSON_COLUMNS[kind]:
            if col in data and isinstance(data[col], str):
                try:
                    data[col] = json.loads(data[col])
                except json.JSONDecodeError:
                    data[col] = {}
    return data


def record_locator_check(conn: sqlite3.Connection, record: dict) -> dict:
    """Append one locator check event and update the SourceVersion status.

    ``result='verified'`` (only allowed for a non-bbox-only method with a
    details statement) sets ``locator_status='verified'``; ``result='failed'``
    sets ``'failed'``; ``result='detected'`` never upgrades beyond
    ``'unverified'`` and never clears ``'verified'``/``'failed'``.
    """
    stored = insert_record(conn, "locator_check", record)
    status = {"verified": "verified", "failed": "failed", "detected": None}[stored["result"]]
    if status is None:  # detection: refine 'unknown' → 'unverified' only
        current = conn.execute(
            "SELECT locator_status FROM evidence_source_versions WHERE version_id=?",
            (stored["version_id"],)).fetchone()[0]
        status = "unverified" if current in ("unknown", "unverified") else current
    conn.execute("UPDATE evidence_source_versions SET locator_status=? WHERE version_id=?",
                 (status, stored["version_id"]))
    conn.commit()
    stored["source_locator_status"] = status
    return stored


def evidence_summary(conn: sqlite3.Connection, claim_id: str) -> dict:
    """Evidence summary for one Claim, counted without double counting.

    Findings from the same study (possibly published in several reports /
    source versions) collapse into one distinct study; the report-level
    finding counts stay available for audit. Unknown/contradictory evidence
    is reported per relation type (supports / refutes / insufficient).
    """
    claim = get_record(conn, "claim", claim_id)
    if claim is None:
        raise EvidenceError(f"EV-Ref: claim {claim_id!r} does not exist")
    rows = conn.execute(
        "SELECT r.relation AS rel, COUNT(DISTINCT r.finding_id) AS findings,"
        " COUNT(DISTINCT f.study_id) AS studies"
        " FROM evidence_relations r JOIN evidence_findings f ON f.finding_id = r.finding_id"
        " WHERE r.claim_id = ? GROUP BY r.relation", (claim_id,)).fetchall()
    relations = {name: {"findings": 0, "studies": 0}
                 for name in ("supports", "refutes", "insufficient")}
    for rel, findings, studies in rows:
        relations[rel] = {"findings": findings, "studies": studies}
    distinct_studies = conn.execute(
        "SELECT COUNT(DISTINCT f.study_id) FROM evidence_relations r"
        " JOIN evidence_findings f ON f.finding_id = r.finding_id WHERE r.claim_id=?",
        (claim_id,)).fetchone()[0]
    return {
        "claim_id": claim_id,
        "relations": relations,
        "distinct_studies": distinct_studies,
        "note": ("studies are counted once regardless of how many reports/source "
                 "versions publish them (no double counting)"),
    }


# ---------------------------------------------------------------------------
# Migration with backup (Issue #14 失败与回滚; AGENTS #11)
# ---------------------------------------------------------------------------

EVIDENCE_TABLES = tuple(TABLES.values())


def evidence_tables_present(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'evidence_%'"
        " ORDER BY name").fetchall()
    return [row[0] for row in rows]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply the additive evidence DDL (idempotent); returns the table list."""
    conn.executescript(EVIDENCE_DDL)
    conn.commit()
    return evidence_tables_present(conn)


def migrate_with_backup(db_path: Path) -> dict:
    """Recorded migration entry: backup FIRST (SQLite backup API), then apply.

    - A fresh database (file absent) is created directly; no backup is needed.
    - An existing database is snapshotted to
      ``<db parent>/backups/pre-evidence-migration-<UTC>.sqlite`` before any
      DDL runs, giving a recoverable path (Issue #14 失败与回滚).
    - ``works`` and all pre-existing tables are never rewritten; compatibility
      reading is asserted by tests (upgrade path keeps old IDs and rows).
    """
    db_path = Path(db_path)
    backup_path = None
    if db_path.exists():
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now_iso().replace("-", "").replace(":", "")
        backup_path = backup_dir / f"pre-evidence-migration-{stamp}-{uuid4().hex[:6]}.sqlite"
        source = sqlite3.connect(str(db_path))
        try:
            target = sqlite3.connect(str(backup_path))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    conn = sqlite3.connect(str(db_path))
    try:
        tables = migrate(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return {"db": str(db_path), "backup": str(backup_path) if backup_path else None,
            "evidence_tables": tables, "integrity": integrity}


# ---------------------------------------------------------------------------
# Issue #10 pilot result mapping (Issue #14 验收 #4 — honest, nulls preserved)
# ---------------------------------------------------------------------------

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def map_pilot_run(run_dir: Path, conn: sqlite3.Connection | None = None,
                  *, apply: bool = False, now: str | None = None) -> dict:
    """Map one recorded Issue #10 pilot run into the evidence model, honestly.

    What is mapped (and what deliberately stays unknown):

    - one SourceVersion bound to the audited Work with the run's recorded
      original PDF sha256 (from the ``original_available`` condition detail);
      ``parsed_sha256``/``parsed_format`` stay null (the pilot run records no
      verified parsed-artifact binding), ``study_id`` stays null (no study
      extraction was recorded), ``locator_status`` stays ``unknown`` — nothing
      is inferred from bbox presence or file existence.
    - uncertainty codes from the run's review envelope are preserved verbatim
      in the record notes.
    - research content (Findings/Claims/Appraisals) is NOT synthesized: a
      blocked attempt recorded no model review, and even a completed envelope
      would need the human-approved extraction flow before its content becomes
      evidence records. Missing-evidence fields honestly stay undetermined
      (Issue #14 验收 #4: 不虚构科研结论).

    With ``apply=False`` the mapping is only computed (dry run). With
    ``apply=True`` the SourceVersion is inserted into ``conn``; re-mapping the
    same run is idempotent (``already_mapped``), never a duplicate.
    """
    run_dir = Path(run_dir)
    audit_path = run_dir / "audit.json"
    if not audit_path.exists():
        raise EvidenceError(f"map_pilot_run: audit.json missing under {run_dir}")
    audit = _read_json(audit_path)
    if not str(audit.get("schema", "")).startswith(_AUDIT_SCHEMA_PREFIX):
        raise EvidenceError(
            f"map_pilot_run: unexpected audit schema {audit.get('schema')!r} in {audit_path}")
    if audit.get("issue_url") != PILOT_ISSUE_URL:
        raise EvidenceError(
            f"map_pilot_run: audit.issue_url {audit.get('issue_url')!r} is not the "
            f"Issue #10 pilot contract ({PILOT_ISSUE_URL})")
    run_id = audit["run_id"]
    review_path = run_dir / "review.json"
    review = _read_json(review_path) if review_path.exists() else {}
    uncertainties = [code for code in (review.get("uncertainties") or []) if code]
    model_review_performed = bool(review.get("model_review_performed")
                                  or audit.get("model_review_performed"))

    original_sha256 = None
    for condition in audit.get("conditions", []):
        if condition.get("id") == "original_available" and condition.get("status") == "pass":
            match = _SHA_RE.match(str(condition.get("detail", "")))
            original_sha256 = match.group(1) if match else None
            break
    library_meta = audit.get("library_metadata") or {}
    original_version = library_meta.get("pdf_version")
    verdict = audit.get("verdict")
    version_id = "sv-pilot-" + str(run_id)

    unknowns = ["parsed_sha256", "parsed_format", "study_id", "locator_status",
                "research_content"]
    content_note = ("no research content mapped: pilot verdict=" + str(verdict)
                    + ", model_review_performed=" + str(model_review_performed).lower()
                    + "; content mapping requires the human-approved extraction flow")
    record = {
        "schema_version": SCHEMA_VERSION,
        "version_id": version_id,
        "work_id": audit["work_id"],
        "study_id": None,
        "source_kind": "unspecified",
        "original_version": original_version,
        "original_sha256": original_sha256,
        "parsed_sha256": None,
        "parsed_format": None,
        "locator_status": "unknown",
        "origin": "pilot_mapping",
        "origin_ref": run_id,
        "created_at": now or _now_iso(),
        "notes": ("mapped from Issue #10 pilot run " + str(run_id)
                  + " (verdict=" + str(verdict) + "; uncertainties preserved: "
                  + (", ".join(uncertainties) if uncertainties else "none declared")
                  + "); " + content_note),
    }
    errors = validate_record("source_version", record)
    if errors:
        raise EvidenceError("mapped pilot record rejected: " + "; ".join(errors))

    result = {
        "run_id": run_id,
        "issue_url": PILOT_ISSUE_URL,
        "verdict": verdict,
        "work_id": record["work_id"],
        "version_id": version_id,
        "original_version": original_version,
        "original_sha256": original_sha256,
        "preserved_unknowns": unknowns,
        "uncertainties": uncertainties,
        "model_review_performed": model_review_performed,
        "research_content": content_note,
        "applied": False,
        "already_mapped": False,
    }
    if apply:
        if conn is None:
            raise EvidenceError("map_pilot_run(apply=True) requires a database connection")
        existing = get_record(conn, "source_version", version_id)
        if existing is not None:
            result["already_mapped"] = True
        else:
            insert_record(conn, "source_version", record)
            result["applied"] = True
    return result
