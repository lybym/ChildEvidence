"""Professional assets domain layer (Issue #15).

Strategy / SupportMethod / InteractionProfile / EvaluationCase — the
declarative professional-asset model on top of the existing bibliographic
(``works``) and evidence (Issue #14) layers, implementing
`docs/design/growth-support-mvp/contracts.md` §1 with the governance rules of
CE-GS-01 (``docs/governance/GROWTH-SUPPORT-QUALIFICATION.md``):

- **Common envelope** (Issue #15 交付范围 #1): stable ``asset_id`` across
  immutable ``revision`` content versions, ``content_hash`` over the declared
  content, append-only ``supersedes_revision`` chain, basis nature
  (``basis_kind``: direct_research / research_synthesis / application_inference
  / design_choice), explicit sufficiency marker, ``basis_refs``,
  ``evaluation_refs``, review/qualification fields kept orthogonal
  (contracts.md §1.1). References must carry the target revision, not just a
  display name.
- **GS-04**: every InteractionProfile version (including the first) must carry
  non-empty ``basis_refs`` and ``evaluation_refs``;
  ``runtime_effect='immediate'`` is rejected — any version takes effect only
  as a new version release (no version waiver).
- **Honest insufficiency** (Issue #15 交付范围 #5): research-based
  ``basis_kind`` values without a checkable research reference must stay
  ``basis_sufficiency='insufficient'``; ``design_choice`` assets are always
  marked insufficient. Nothing fabricates citations: a research ref must point
  at an existing evidence/works record (AS-BasisRef).
- **Draft ≠ released** (Issue #15 验收 #1): ``lifecycle_status='released'``
  requires ``release_eligibility='eligible'``, which itself requires
  technical validation, scientific appraisal and a human review origin
  (AS-Release; GS-01/GS-02/GS-05). No code path sets eligibility
  automatically; real release decisions stay governed by CE-GS-01.
- **Unknown never executes as true** (Issue #15 验收 #3): condition specs may
  only declare ``on_unknown: block|needs_information`` — the schema enum makes
  "proceed on unknown" inexpressible; :func:`condition_precheck` implements
  the honest data-layer semantics.
- **Retraction blocks** (GS-03): ``retracted`` requires reason/date/decision
  ref; retracted/superseded/draft assets report concrete blockers via
  :func:`asset_blockers` and are never "usable".
- **Data, not code** (Issue #15 验收 #3): every field of every schema is
  declarative data (strings/lists/objects); ``additionalProperties: false``
  means no executable field can be smuggled in. New action types require a
  versioned schema change plus compatible evaluation fixtures — never runtime
  downloads.

Strictness mirrors Issue #14: records carry ``schema_version`` (const
``ce.assets/1``), all schemas set ``additionalProperties: false``, and the
shared strict validator (``research_library.strict_schema``) rejects extra
fields, bad bounds, wrong patterns and wrong references with explicit
``AS-*`` rule ids.

Storage is additive only (``CREATE TABLE IF NOT EXISTS``; four new
``asset_*`` tables; ``works`` and all evidence tables untouched). Migration
entry: :func:`migrate_with_backup` (backup first via the SQLite backup API,
then apply, then verify). The cross-record revision-chain rule (AS-Chain:
append-only, no gaps, no rewrites) is the storage-layer answer to GS-LIM-01
for assets.

The shipped demo chain (``contracts/assets/fixtures/``, seeded via
:func:`seed_demo`) is a *minimal real method asset chain* with **synthetic**
content: ``demo-*`` ids, ``basis_kind='design_choice'``,
``basis_sufficiency='insufficient'``, draft lifecycle, never eligible. It
proves the model end-to-end without claiming research support or release
qualification (研究依据不足就标记不足，不补造引文).

No network, no model calls, no third-party dependencies (AGENTS #9). This
module never touches child personal data (AGENTS #14): evaluation fixtures
are declared ``synthetic`` by const.
"""
from __future__ import annotations

from importlib import resources
import hashlib
import json
from pathlib import Path
import sqlite3

from .governance import HUMAN_REVIEW_ORIGINS
from .strict_schema import strict_validate as _strict_validate

ISSUE_URL = "https://github.com/lybym/ChildEvidence/issues/15"

SCHEMA_VERSION = "ce.assets/1"

KINDS = ("strategy", "support_method", "interaction_profile", "evaluation_case")

TABLES = {
    "strategy": "asset_strategies",
    "support_method": "asset_support_methods",
    "interaction_profile": "asset_interaction_profiles",
    "evaluation_case": "asset_evaluation_cases",
}

# Finite action vocabulary (contracts.md §1.2). Adding a new action type is a
# versioned schema change plus compatible evaluation fixtures — not a runtime
# download. The per-schema enums and this tuple must stay identical
# (tests/test_asset_model.py asserts it).
ACTIONS = ("ask_clarification", "offer_choice", "explain_with_support",
           "propose_activity", "request_feedback", "pause", "suggest_human_help")

BASIS_KINDS = ("direct_research", "research_synthesis", "application_inference",
               "design_choice")
BASIS_SUFFICIENCY = ("research_supported", "insufficient")
BASIS_REF_KINDS = ("claim", "source_version", "work", "evaluation_case",
                   "design_note", "external")
_RESEARCH_REF_KINDS = ("claim", "source_version", "work")
REVIEW_STATUSES = ("not_reviewed", "ai_reviewed", "human_reviewed")
LIFECYCLE_STATUSES = ("draft", "released", "superseded", "retracted")
# Condition semantics: a condition is resolved against confirmed facts only —
# confirmed present, confirmed absent (explicit "!x" marker; absence is never
# inferred from silence) or unknown. Unknown outcomes may only block or request
# information — never proceed (Issue #15 验收 #3).
CONDITION_EXPECTS = ("available", "absent")
CONDITION_ON_UNKNOWN = ("block", "needs_information")

# Envelope fields excluded from the content hash: identity of the content is
# hashed; lifecycle/review/qualification annotations may change (e.g. draft →
# superseded → retracted) without changing what the content says.
_HASH_EXCLUDED_FIELDS = frozenset({
    "schema_version", "created_at", "content_hash",
    "review_origin", "review_status", "technical_validation",
    "scientific_appraisal", "release_eligibility", "lifecycle_status",
    "retraction_reason", "retracted_at", "retraction_ref", "notes",
})

_ENVELOPE_BASE = (
    "asset_id", "revision", "schema_version", "title", "content_hash",
    "supersedes_revision", "created_by", "created_at", "basis_kind",
    "basis_sufficiency", "basis_refs", "demo_only",
    "review_origin", "review_status", "technical_validation",
    "scientific_appraisal", "release_eligibility", "lifecycle_status",
    "retraction_reason", "retracted_at", "retraction_ref", "notes",
)

_PAYLOAD_COLUMNS = {
    "strategy": ("goal", "applies_when", "excludes_when", "steps",
                 "observed_outcomes", "adjust_when", "stop_when",
                 "evidence_summary"),
    "support_method": ("goal", "required_information", "explanation_dimensions",
                       "states", "initial_state", "allowed_actions",
                       "transitions", "on_user_decline", "on_method_ineffective",
                       "audience_adaptation", "conflict_priority",
                       "review_criteria", "unknown_policy"),
    "interaction_profile": ("expression_norms", "audience_adaptation",
                            "conflict_priority", "runtime_effect"),
    "evaluation_case": ("fixture_kind", "input_fixture", "expected_behaviors",
                        "forbidden_behaviors", "scoring_basis", "covers",
                        "scenarios"),
}


def _columns_for(kind: str) -> tuple[str, ...]:
    """Envelope + payload columns for one kind.

    ``evaluation_refs`` is an envelope field of the three *consumer* kinds
    (strategy / support_method / interaction_profile); an EvaluationCase is
    the cited target and carries no such field (its schema rejects it).
    """
    envelope = list(_ENVELOPE_BASE)
    if kind != "evaluation_case":
        envelope.insert(envelope.index("basis_refs") + 1, "evaluation_refs")
    return tuple(envelope) + _PAYLOAD_COLUMNS[kind]


_COLUMNS = {kind: _columns_for(kind) for kind in KINDS}

_JSON_COLUMNS = {
    "strategy": ("basis_refs", "evaluation_refs", "applies_when", "excludes_when",
                 "steps", "observed_outcomes", "adjust_when", "stop_when"),
    "support_method": ("basis_refs", "evaluation_refs", "required_information",
                       "explanation_dimensions", "states", "allowed_actions",
                       "transitions", "on_user_decline", "on_method_ineffective",
                       "audience_adaptation", "conflict_priority",
                       "review_criteria"),
    "interaction_profile": ("basis_refs", "evaluation_refs", "expression_norms",
                            "audience_adaptation", "conflict_priority"),
    "evaluation_case": ("basis_refs", "input_fixture", "expected_behaviors",
                        "forbidden_behaviors", "covers", "scenarios"),
}

_DEFAULTS = {
    "strategy": {
        "supersedes_revision": None, "created_at": None, "basis_refs": [],
        "evaluation_refs": [], "demo_only": False, "review_origin": None,
        "review_status": "not_reviewed", "technical_validation": "not_run",
        "scientific_appraisal": "not_done", "release_eligibility": "not_eligible",
        "lifecycle_status": "draft", "retraction_reason": None,
        "retracted_at": None, "retraction_ref": None, "notes": None,
        "applies_when": [], "excludes_when": [], "observed_outcomes": [],
    },
    "support_method": {
        "supersedes_revision": None, "created_at": None, "demo_only": False,
        "review_origin": None, "review_status": "not_reviewed",
        "technical_validation": "not_run", "scientific_appraisal": "not_done",
        "release_eligibility": "not_eligible", "lifecycle_status": "draft",
        "retraction_reason": None, "retracted_at": None, "retraction_ref": None,
        "notes": None, "transitions": [],
    },
    "interaction_profile": {
        "supersedes_revision": None, "created_at": None, "demo_only": False,
        "review_origin": None, "review_status": "not_reviewed",
        "technical_validation": "not_run", "scientific_appraisal": "not_done",
        "release_eligibility": "not_eligible", "lifecycle_status": "draft",
        "retraction_reason": None, "retracted_at": None, "retraction_ref": None,
        "notes": None,
    },
    "evaluation_case": {
        "supersedes_revision": None, "created_at": None, "basis_refs": [],
        "demo_only": False, "review_origin": None,
        "review_status": "not_reviewed", "technical_validation": "not_run",
        "scientific_appraisal": "not_done", "release_eligibility": "not_eligible",
        "lifecycle_status": "draft", "retraction_reason": None,
        "retracted_at": None, "retraction_ref": None, "notes": None,
        "scenarios": [],
    },
}

# Additive DDL. Never touches works/, evidence_* or any existing table
# (AGENTS #2, #11). CHECK constraints are the last line of defense behind the
# strict schema validation.
ASSETS_DDL = """
CREATE TABLE IF NOT EXISTS asset_strategies (
  asset_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version TEXT NOT NULL,
  title TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  supersedes_revision INTEGER,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  basis_kind TEXT NOT NULL CHECK (basis_kind IN ('direct_research','research_synthesis','application_inference','design_choice')),
  basis_sufficiency TEXT NOT NULL CHECK (basis_sufficiency IN ('research_supported','insufficient')),
  basis_refs TEXT NOT NULL DEFAULT '[]',
  evaluation_refs TEXT NOT NULL DEFAULT '[]',
  demo_only INTEGER NOT NULL DEFAULT 0,
  review_origin TEXT,
  review_status TEXT NOT NULL DEFAULT 'not_reviewed' CHECK (review_status IN ('not_reviewed','ai_reviewed','human_reviewed')),
  technical_validation TEXT NOT NULL DEFAULT 'not_run' CHECK (technical_validation IN ('not_run','passed','failed')),
  scientific_appraisal TEXT NOT NULL DEFAULT 'not_done' CHECK (scientific_appraisal IN ('not_done','done')),
  release_eligibility TEXT NOT NULL DEFAULT 'not_eligible' CHECK (release_eligibility IN ('not_eligible','eligible')),
  lifecycle_status TEXT NOT NULL DEFAULT 'draft' CHECK (lifecycle_status IN ('draft','released','superseded','retracted')),
  retraction_reason TEXT,
  retracted_at TEXT,
  retraction_ref TEXT,
  notes TEXT,
  goal TEXT NOT NULL,
  applies_when TEXT NOT NULL DEFAULT '[]',
  excludes_when TEXT NOT NULL DEFAULT '[]',
  steps TEXT NOT NULL DEFAULT '[]',
  observed_outcomes TEXT NOT NULL DEFAULT '[]',
  adjust_when TEXT NOT NULL,
  stop_when TEXT NOT NULL,
  evidence_summary TEXT NOT NULL,
  PRIMARY KEY (asset_id, revision)
);

CREATE TABLE IF NOT EXISTS asset_support_methods (
  asset_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version TEXT NOT NULL,
  title TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  supersedes_revision INTEGER,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  basis_kind TEXT NOT NULL CHECK (basis_kind IN ('direct_research','research_synthesis','application_inference','design_choice')),
  basis_sufficiency TEXT NOT NULL CHECK (basis_sufficiency IN ('research_supported','insufficient')),
  basis_refs TEXT NOT NULL DEFAULT '[]',
  evaluation_refs TEXT NOT NULL DEFAULT '[]',
  demo_only INTEGER NOT NULL DEFAULT 0,
  review_origin TEXT,
  review_status TEXT NOT NULL DEFAULT 'not_reviewed' CHECK (review_status IN ('not_reviewed','ai_reviewed','human_reviewed')),
  technical_validation TEXT NOT NULL DEFAULT 'not_run' CHECK (technical_validation IN ('not_run','passed','failed')),
  scientific_appraisal TEXT NOT NULL DEFAULT 'not_done' CHECK (scientific_appraisal IN ('not_done','done')),
  release_eligibility TEXT NOT NULL DEFAULT 'not_eligible' CHECK (release_eligibility IN ('not_eligible','eligible')),
  lifecycle_status TEXT NOT NULL DEFAULT 'draft' CHECK (lifecycle_status IN ('draft','released','superseded','retracted')),
  retraction_reason TEXT,
  retracted_at TEXT,
  retraction_ref TEXT,
  notes TEXT,
  goal TEXT NOT NULL,
  required_information TEXT NOT NULL,
  explanation_dimensions TEXT NOT NULL,
  states TEXT NOT NULL,
  initial_state TEXT NOT NULL,
  allowed_actions TEXT NOT NULL,
  transitions TEXT NOT NULL DEFAULT '[]',
  on_user_decline TEXT NOT NULL,
  on_method_ineffective TEXT NOT NULL,
  audience_adaptation TEXT NOT NULL,
  conflict_priority TEXT NOT NULL,
  review_criteria TEXT NOT NULL,
  unknown_policy TEXT NOT NULL CHECK (unknown_policy = 'block'),
  PRIMARY KEY (asset_id, revision)
);

CREATE TABLE IF NOT EXISTS asset_interaction_profiles (
  asset_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version TEXT NOT NULL,
  title TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  supersedes_revision INTEGER,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  basis_kind TEXT NOT NULL CHECK (basis_kind IN ('direct_research','research_synthesis','application_inference','design_choice')),
  basis_sufficiency TEXT NOT NULL CHECK (basis_sufficiency IN ('research_supported','insufficient')),
  basis_refs TEXT NOT NULL DEFAULT '[]',
  evaluation_refs TEXT NOT NULL DEFAULT '[]',
  demo_only INTEGER NOT NULL DEFAULT 0,
  review_origin TEXT,
  review_status TEXT NOT NULL DEFAULT 'not_reviewed' CHECK (review_status IN ('not_reviewed','ai_reviewed','human_reviewed')),
  technical_validation TEXT NOT NULL DEFAULT 'not_run' CHECK (technical_validation IN ('not_run','passed','failed')),
  scientific_appraisal TEXT NOT NULL DEFAULT 'not_done' CHECK (scientific_appraisal IN ('not_done','done')),
  release_eligibility TEXT NOT NULL DEFAULT 'not_eligible' CHECK (release_eligibility IN ('not_eligible','eligible')),
  lifecycle_status TEXT NOT NULL DEFAULT 'draft' CHECK (lifecycle_status IN ('draft','released','superseded','retracted')),
  retraction_reason TEXT,
  retracted_at TEXT,
  retraction_ref TEXT,
  notes TEXT,
  expression_norms TEXT NOT NULL,
  audience_adaptation TEXT NOT NULL,
  conflict_priority TEXT NOT NULL,
  runtime_effect TEXT NOT NULL CHECK (runtime_effect IN ('new_version_release','immediate')),
  PRIMARY KEY (asset_id, revision)
);

CREATE TABLE IF NOT EXISTS asset_evaluation_cases (
  asset_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version TEXT NOT NULL,
  title TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  supersedes_revision INTEGER,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  basis_kind TEXT NOT NULL CHECK (basis_kind IN ('direct_research','research_synthesis','application_inference','design_choice')),
  basis_sufficiency TEXT NOT NULL CHECK (basis_sufficiency IN ('research_supported','insufficient')),
  basis_refs TEXT NOT NULL DEFAULT '[]',
  demo_only INTEGER NOT NULL DEFAULT 0,
  review_origin TEXT,
  review_status TEXT NOT NULL DEFAULT 'not_reviewed' CHECK (review_status IN ('not_reviewed','ai_reviewed','human_reviewed')),
  technical_validation TEXT NOT NULL DEFAULT 'not_run' CHECK (technical_validation IN ('not_run','passed','failed')),
  scientific_appraisal TEXT NOT NULL DEFAULT 'not_done' CHECK (scientific_appraisal IN ('not_done','done')),
  release_eligibility TEXT NOT NULL DEFAULT 'not_eligible' CHECK (release_eligibility IN ('not_eligible','eligible')),
  lifecycle_status TEXT NOT NULL DEFAULT 'draft' CHECK (lifecycle_status IN ('draft','released','superseded','retracted')),
  retraction_reason TEXT,
  retracted_at TEXT,
  retraction_ref TEXT,
  notes TEXT,
  fixture_kind TEXT NOT NULL CHECK (fixture_kind = 'synthetic'),
  input_fixture TEXT NOT NULL,
  expected_behaviors TEXT NOT NULL,
  forbidden_behaviors TEXT NOT NULL,
  scoring_basis TEXT NOT NULL,
  covers TEXT NOT NULL,
  scenarios TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (asset_id, revision)
);
"""


class AssetsError(ValueError):
    """Raised for any rejected asset record (strict validation or storage rule)."""


# ---------------------------------------------------------------------------
# Strict schema loading (same packaging approach as evidence.py, Issue #14)
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, dict] = {}


def load_schema(kind: str) -> dict:
    """Load the packaged strict schema for ``kind`` via importlib.resources."""
    if kind not in KINDS:
        raise AssetsError(f"unknown asset record kind: {kind!r}")
    if kind not in _SCHEMA_CACHE:
        resource = resources.files("research_library.contracts.assets").joinpath(
            f"{kind}.schema.json")
        _SCHEMA_CACHE[kind] = json.loads(resource.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[kind]


def schema_path(kind: str) -> str:
    """Filesystem path of the packaged schema (diagnostics/tests)."""
    return str(resources.files("research_library.contracts.assets").joinpath(
        f"{kind}.schema.json"))


# ---------------------------------------------------------------------------
# Content hash (immutable content identity, Issue #15 验收 #1)
# ---------------------------------------------------------------------------

def compute_content_hash(record: dict) -> str:
    """sha256 over the canonical JSON of the declared content fields.

    Envelope bookkeeping is excluded (see ``_HASH_EXCLUDED_FIELDS``): the hash
    identifies *what the content says*, so lifecycle/review/qualification
    annotations may evolve without changing the content identity. Any content
    change (including a new revision) produces a different hash.
    """
    payload = {k: v for k, v in record.items() if k not in _HASH_EXCLUDED_FIELDS}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return "sha256=" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Strict validation entry (schema + record-local AS-* rules)
# ---------------------------------------------------------------------------

def validate_record(kind: str, record: dict) -> list[str]:
    """Strictly validate one asset record; returns the error list (empty = valid).

    Record-local cross-field rules (AS-*) are appended to the schema
    diagnostics so the entry stays usable without a database connection.
    Storage-level rules that need the database (duplication, revision chain,
    reference existence, evaluation closure) live in :func:`insert_record`.
    """
    schema = load_schema(kind)
    errors: list[str] = []
    _strict_validate(record, schema, kind, errors)
    if not isinstance(record, dict):
        return errors  # schema diagnostics already cover the type problem

    # AS-Hash: a declared content hash must match the recomputed one.
    if "content_hash" in record:
        expected = compute_content_hash(record)
        if record.get("content_hash") != expected:
            errors.append(
                f"AS-Hash: content_hash {record.get('content_hash')!r} does not match the "
                f"recomputed content hash {expected!r} (immutable content identity)")

    # AS-Revision: append-only chain arithmetic (record-local part).
    revision = record.get("revision")
    supersedes = record.get("supersedes_revision")
    if isinstance(revision, int) and not isinstance(revision, bool):
        if revision == 1 and supersedes is not None:
            errors.append(
                "AS-Revision: revision=1 must not declare supersedes_revision "
                "(there is no earlier revision to supersede)")
        if revision > 1 and supersedes != revision - 1:
            errors.append(
                f"AS-Revision: revision={revision} must declare "
                f"supersedes_revision={revision - 1} (append-only chain without gaps)")

    # AS-GS04: interaction profiles take effect only as new version releases.
    if kind == "interaction_profile" and record.get("runtime_effect") == "immediate":
        errors.append(
            "AS-GS04: interaction_profile runtime_effect='immediate' is rejected — any "
            "version (including the first) takes effect only as a new version release "
            "(GS-04, no version waiver)")

    # AS-Release: eligibility requires the full orthogonal chain (GS-01/02/05).
    if record.get("release_eligibility") == "eligible":
        missing = []
        if record.get("technical_validation") != "passed":
            missing.append("technical_validation='passed'")
        if record.get("scientific_appraisal") != "done":
            missing.append("scientific_appraisal='done'")
        if record.get("review_origin") not in HUMAN_REVIEW_ORIGINS:
            missing.append("a human review origin (" + ", ".join(HUMAN_REVIEW_ORIGINS) + ")")
        if record.get("review_status") != "human_reviewed":
            missing.append("review_status='human_reviewed'")
        if missing:
            errors.append(
                "AS-Release: release_eligibility='eligible' requires " + " and ".join(missing)
                + " (GS-01/GS-02/GS-05; AI review origins never self-qualify)")

    # AS-Lifecycle / AS-Retract: unapproved drafts cannot pose as released
    # assets; retraction must be append-style with explicit reason/date/ref.
    lifecycle = record.get("lifecycle_status")
    if lifecycle == "released" and record.get("release_eligibility") != "eligible":
        errors.append(
            "AS-Lifecycle: lifecycle_status='released' requires release_eligibility="
            "'eligible' — an unapproved draft cannot masquerade as a released asset")
    if lifecycle == "retracted":
        for field in ("retraction_reason", "retracted_at", "retraction_ref"):
            value = record.get(field)
            if not (isinstance(value, str) and value.strip()):
                errors.append(
                    f"AS-Retract: lifecycle_status='retracted' requires non-empty {field} "
                    "(append-style withdrawal, GS-03)")

    # AS-Demo: demo-* identifiers are synthetic-only and never released.
    asset_id = record.get("asset_id")
    if isinstance(asset_id, str) and asset_id.startswith("demo-") \
            and record.get("demo_only") is not True:
        errors.append(
            "AS-Demo: asset_id with the 'demo-' prefix must declare demo_only=true "
            "(demo identifiers are reserved for synthetic fixtures)")
    if record.get("demo_only") is True:
        if record.get("release_eligibility") == "eligible":
            errors.append(
                "AS-Demo: demo_only assets never hold release_eligibility='eligible' "
                "(synthetic fixtures carry no real qualification)")
        if record.get("lifecycle_status") == "released":
            errors.append(
                "AS-Demo: demo_only assets can never be released "
                "(synthetic fixtures stay out of real qualification)")

    # AS-State: declared states bound the initial state and every transition.
    if kind == "support_method":
        states = record.get("states") or []
        initial = record.get("initial_state")
        if states and initial and initial not in states:
            errors.append(
                f"AS-State: initial_state {initial!r} is not one of the declared states")
        for index, transition in enumerate(record.get("transitions") or []):
            if not isinstance(transition, dict):
                continue
            for key in ("from_state", "to_state"):
                value = transition.get(key)
                if states and value and value not in states:
                    errors.append(
                        f"AS-State: transitions[{index}].{key}={value!r} is not one of "
                        "the declared states")
    return errors


# ---------------------------------------------------------------------------
# Storage (additive, append-only; explicit rejection of duplicates/bad refs)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_record(conn: sqlite3.Connection, kind: str, asset_id: str,
               revision: int) -> dict | None:
    """Load one asset version (JSON columns decoded, demo_only as bool)."""
    if kind not in KINDS:
        raise AssetsError(f"unknown asset record kind: {kind!r}")
    row = conn.execute(
        f"SELECT * FROM {TABLES[kind]} WHERE asset_id=? AND revision=?",
        (asset_id, revision)).fetchone()
    if row is None:
        return None
    data = dict(row)
    for column in _JSON_COLUMNS[kind]:
        if column in data and isinstance(data[column], str):
            try:
                data[column] = json.loads(data[column])
            except json.JSONDecodeError:
                data[column] = []
    if "demo_only" in data:
        data["demo_only"] = bool(data["demo_only"])
    return data


def latest_revision(conn: sqlite3.Connection, kind: str, asset_id: str) -> int | None:
    """Highest existing revision for one asset id (None when absent)."""
    row = conn.execute(
        f"SELECT MAX(revision) FROM {TABLES[kind]} WHERE asset_id=?",
        (asset_id,)).fetchone()
    return row[0] if row and row[0] is not None else None


def _check_basis_refs(conn: sqlite3.Connection, stored: dict) -> None:
    """AS-BasisRef: research-flavored refs must point at real records."""
    for ref in stored.get("basis_refs") or []:
        if not isinstance(ref, dict):
            continue
        ref_kind, ref_value = ref.get("ref_kind"), ref.get("ref")
        if ref_kind == "claim":
            table, column, label = "evidence_claims", "claim_id", "evidence_claims"
        elif ref_kind == "source_version":
            table, column, label = ("evidence_source_versions", "version_id",
                                    "evidence_source_versions")
        elif ref_kind == "work":
            table, column, label = "works", "internal_id", "works"
        else:
            continue
        row = conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?",
                           (ref_value,)).fetchone()
        if row is None:
            raise AssetsError(
                f"AS-BasisRef: basis ref kind={ref_kind!r} ref={ref_value!r} does not "
                f"exist in {label} (research refs must point at real records — "
                "research citations are never fabricated)")


def _check_basis_honesty(stored: dict) -> None:
    """AS-Basis: sufficiency markers must match the declared evidence."""
    refs = [ref for ref in (stored.get("basis_refs") or [])
            if isinstance(ref, dict) and ref.get("ref_kind") in _RESEARCH_REF_KINDS]
    if stored.get("basis_sufficiency") == "research_supported" and not refs:
        raise AssetsError(
            "AS-Basis: basis_sufficiency='research_supported' requires at least one "
            "claim/source_version/work basis_ref — research support must be checkable, "
            "not claimed (research citations are never fabricated)")
    if stored.get("basis_kind") == "design_choice" \
            and stored.get("basis_sufficiency") != "insufficient":
        raise AssetsError(
            "AS-Basis: basis_kind='design_choice' must be marked "
            "basis_sufficiency='insufficient' (a design choice is not research support)")


def _check_evaluation_closure(conn: sqlite3.Connection, stored: dict) -> None:
    """AS-EvalRef: cited evaluation cases must exist and cover this version."""
    asset_id, revision = stored["asset_id"], stored["revision"]
    for ref in stored.get("evaluation_refs") or []:
        if not isinstance(ref, dict):
            continue
        row = conn.execute(
            "SELECT covers FROM asset_evaluation_cases WHERE asset_id=? AND revision=?",
            (ref.get("case_id"), ref.get("revision"))).fetchone()
        if row is None:
            raise AssetsError(
                f"AS-EvalRef: evaluation_ref {ref.get('case_id')!r}@{ref.get('revision')} "
                "does not exist in asset_evaluation_cases (evaluation citations must "
                "point at real cases)")
        try:
            covers = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or [])
        except json.JSONDecodeError:
            covers = []
        covered = any(isinstance(entry, dict)
                      and entry.get("asset_id") == asset_id
                      and entry.get("revision") == revision
                      for entry in covers)
        if not covered:
            raise AssetsError(
                f"AS-EvalRef: evaluation case {ref.get('case_id')!r}@{ref.get('revision')} "
                f"does not declare coverage for {asset_id!r}@{revision} in its covers "
                "list (evaluation closure)")


def prepared_record(kind: str, record: dict) -> dict:
    """Apply the envelope defaults exactly as :func:`insert_record` would.

    Returns the prepared record (defaults merged, ``schema_version`` and
    ``created_at`` filled). Use it to compute ``content_hash`` for
    hand-authored records: the hash must cover the *complete stored shape*,
    including keys a partial record leaves to defaults (e.g.
    ``supersedes_revision: null``).
    """
    if kind not in KINDS:
        raise AssetsError(f"unknown asset record kind: {kind!r}")
    if not isinstance(record, dict):
        raise AssetsError(f"{kind} rejected: record must be an object")
    stored = {**_DEFAULTS.get(kind, {}), **record}
    stored.setdefault("schema_version", SCHEMA_VERSION)
    if not stored.get("created_at"):
        stored["created_at"] = _now_iso()
    return stored


def insert_record(conn: sqlite3.Connection, kind: str, record: dict) -> dict:
    """Validate then insert one asset version; returns the stored row dict.

    Strict path: fill defaults → require ``content_hash`` (no silent
    auto-hashing) → strict validation → AS-Dup / AS-Chain (append-only,
    no-gap revision chain) / AS-BasisRef / AS-Basis / AS-EvalRef checks →
    INSERT → mark the superseded previous revision. Any problem raises
    :class:`AssetsError` with an explicit ``AS-*`` rule; nothing is silently
    passed or partially written.
    """
    stored = prepared_record(kind, record)
    if not stored.get("content_hash"):
        raise AssetsError(
            "AS-Hash: content_hash is required at insert time; compute it over "
            "prepared_record(kind, record) with compute_content_hash — no silent "
            "auto-hashing")
    errors = validate_record(kind, stored)
    if errors:
        raise AssetsError(f"{kind} rejected: " + "; ".join(errors))

    asset_id, revision = stored["asset_id"], stored["revision"]
    table = TABLES[kind]

    if stored.get("lifecycle_status") == "superseded":
        raise AssetsError(
            "AS-Lifecycle: 'superseded' is produced only by the revision chain "
            "(a newer revision landing); insert drafts and let supersedes_revision "
            "mark the previous version")

    existing = conn.execute(
        f"SELECT 1 FROM {table} WHERE asset_id=? AND revision=?",
        (asset_id, revision)).fetchone()
    if existing is not None:
        raise AssetsError(f"AS-Dup: {kind} {asset_id!r}@{revision} already exists")

    max_revision = latest_revision(conn, kind, asset_id) or 0
    if revision != max_revision + 1:
        raise AssetsError(
            f"AS-Chain: {kind} {asset_id!r} revision {revision} does not append to "
            f"the revision chain (existing max revision {max_revision}; expected "
            f"{max_revision + 1}); rewriting or inserting gaps into the immutable "
            "revision chain is rejected")

    _check_basis_refs(conn, stored)
    _check_basis_honesty(stored)
    _check_evaluation_closure(conn, stored)

    columns = _COLUMNS[kind]
    values = []
    for column in columns:
        value = stored.get(column)
        if column in _JSON_COLUMNS[kind] and value is not None:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        values.append(value)
    placeholders = ", ".join("?" for _ in columns)
    try:
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            values)
    except sqlite3.IntegrityError as error:
        raise AssetsError(
            f"AS-Dup: {kind} rejected by a database constraint: {error}") from error

    superseded_previous = False
    if revision > 1:
        previous = conn.execute(
            f"SELECT lifecycle_status FROM {table} WHERE asset_id=? AND revision=?",
            (asset_id, revision - 1)).fetchone()
        if previous is not None and previous[0] != "retracted":
            conn.execute(
                f"UPDATE {table} SET lifecycle_status='superseded' "
                "WHERE asset_id=? AND revision=?", (asset_id, revision - 1))
            superseded_previous = True
    conn.commit()
    result = get_record(conn, kind, asset_id, revision)
    result["superseded_previous"] = superseded_previous
    return result


def retract_asset(conn: sqlite3.Connection, kind: str, asset_id: str, revision: int,
                  *, reason: str, ref: str, at: str | None = None) -> dict:
    """Mark one asset version retracted (append-style annotation, GS-03).

    Content is never rewritten: the record keeps its revision and hash, only
    ``lifecycle_status``/``retraction_*`` annotations change. Re-retracting is
    rejected; retraction is terminal for usability (see :func:`asset_blockers`).
    """
    if kind not in KINDS:
        raise AssetsError(f"unknown asset record kind: {kind!r}")
    current = get_record(conn, kind, asset_id, revision)
    if current is None:
        raise AssetsError(f"AS-Retract: {kind} {asset_id!r}@{revision} does not exist")
    if current["lifecycle_status"] == "retracted":
        raise AssetsError(
            f"AS-Retract: {kind} {asset_id!r}@{revision} is already retracted "
            "(append-style; the record is kept as-is)")
    if not isinstance(reason, str) or not reason.strip():
        raise AssetsError("AS-Retract: retraction requires a non-empty reason")
    if not isinstance(ref, str) or not ref.strip():
        raise AssetsError("AS-Retract: retraction requires a non-empty decision ref")
    conn.execute(
        f"UPDATE {TABLES[kind]} SET lifecycle_status='retracted', retraction_reason=?, "
        "retracted_at=?, retraction_ref=? WHERE asset_id=? AND revision=?",
        (reason.strip(), at or _now_iso(), ref.strip(), asset_id, revision))
    conn.commit()
    return get_record(conn, kind, asset_id, revision)


def asset_blockers(conn: sqlite3.Connection, kind: str, asset_id: str,
                   revision: int) -> dict:
    """Runtime-applicability precheck for one asset version (data layer only).

    Returns every concrete reason the version must not drive behavior right
    now: draft/superseded/retracted lifecycle, missing evaluation citations,
    declared insufficient evidence, missing human review, missing release
    eligibility, demo-only fixtures. ``usable`` is true only when no blocker
    remains. The runtime core (Issue #17) consumes this verdict; this module
    never flips an asset to usable.
    """
    ref = f"{asset_id}@{revision}"
    row = get_record(conn, kind, asset_id, revision)
    if row is None:
        return {"asset_ref": ref, "kind": kind, "found": False, "blocked": True,
                "blockers": [{"code": "ASB-Missing",
                              "detail": "asset version does not exist"}],
                "usable": False}
    blockers = []
    status = row["lifecycle_status"]
    if status == "draft":
        blockers.append({
            "code": "ASB-Draft",
            "detail": ("unapproved draft; release_eligibility="
                       + str(row["release_eligibility"]))})
    elif status == "superseded":
        blockers.append({
            "code": "ASB-Superseded",
            "detail": "a newer revision exists; use the latest released version"})
    elif status == "retracted":
        blockers.append({
            "code": "ASB-Retracted",
            "detail": "retracted: " + str(row["retraction_reason"])})
    if kind != "evaluation_case" and not row.get("evaluation_refs"):
        blockers.append({
            "code": "ASB-EvalMissing",
            "detail": ("no evaluation_refs — asset versions must cite evaluation "
                       "cases (GS-04)")})
    if row.get("basis_sufficiency") == "insufficient":
        blockers.append({
            "code": "ASB-EvidenceInsufficient",
            "detail": "declared research basis is insufficient (honest marker)"})
    if row.get("review_status") != "human_reviewed" \
            or row.get("review_origin") not in HUMAN_REVIEW_ORIGINS:
        blockers.append({
            "code": "ASB-ReviewMissing",
            "detail": "no completed human review (AI origins never self-qualify)"})
    if row.get("release_eligibility") != "eligible":
        blockers.append({
            "code": "ASB-NotEligible",
            "detail": "release_eligibility is not 'eligible'"})
    if row.get("demo_only"):
        blockers.append({
            "code": "ASB-DemoAsset",
            "detail": "demo-only synthetic fixture; never for real users"})
    return {"asset_ref": ref, "kind": kind, "found": True,
            "blocked": bool(blockers), "blockers": blockers,
            "usable": not blockers}


# ---------------------------------------------------------------------------
# Declarative condition precheck (Issue #15 验收 #2 / #3, data layer)
# ---------------------------------------------------------------------------

def condition_precheck(record: dict, available_information) -> dict:
    """Evaluate a SupportMethod/Strategy's declared conditions over resolved facts.

    ``available_information`` is the set of *resolved* information items:
    ``"x"`` means x is confirmed present, ``"!x"`` means x is confirmed absent
    (absence must be checked explicitly — it is never inferred from silence).
    Anything neither confirmed present nor confirmed absent is **unknown**.

    For each condition spec:

    - unresolved → **unknown** → ``on_unknown`` governs: ``block`` blocks,
      ``needs_information`` requests the item. Nothing on the unknown path can
      ever return ``can_proceed=True`` — the schema enum does not even contain
      a "proceed" option (Issue #15 验收 #3);
    - ``applies_when`` resolved in favor of ``expect`` → met; resolved against
      → violated → blocked (the method does not apply);
    - ``excludes_when`` resolved in favor of ``expect`` → the exclusion fires
      → blocked; resolved against → no exclusion.

    Missing ``required_information`` keys are reported as
    ``needs_information``. This is a pure function over the declared asset
    data; the runtime core (Issue #17) re-implements these semantics over live
    state and must not weaken them.
    """
    available = set(available_information or ())
    present = {item for item in available
               if isinstance(item, str) and not item.startswith("!")}
    absent = {item[1:] for item in available
              if isinstance(item, str) and item.startswith("!")}
    satisfied: list[dict] = []
    violated: list[dict] = []
    unknown: list[dict] = []
    blocked: list[dict] = []
    needs: list[str] = []

    def evaluate(spec, list_name):
        information, expect = spec["information"], spec["expect"]
        confirmed_present = information in present
        confirmed_absent = information in absent
        if confirmed_present:
            met = expect == "available"
        elif confirmed_absent:
            met = expect == "absent"
        else:
            unknown.append({"condition": information, "expect": expect,
                            "list": list_name, "on_unknown": spec["on_unknown"]})
            if spec["on_unknown"] == "block":
                blocked.append({"condition": information,
                                "detail": f"{list_name} condition unknown — unknown "
                                          "conditions are never treated as true"})
            else:
                needs.append(information)
            return
        if list_name == "applies_when":
            if met:
                satisfied.append({"condition": information, "expect": expect,
                                  "list": list_name})
            else:
                violated.append({"condition": information, "expect": expect,
                                 "list": list_name})
                blocked.append({"condition": information,
                                "detail": f"{list_name} condition violated "
                                          f"(confirmed "
                                          f"{'present' if confirmed_present else 'absent'})"})
        else:  # excludes_when: a resolved match fires the exclusion
            if met:
                blocked.append({"condition": information,
                                "detail": f"{list_name} condition met — method excluded"})
            else:
                satisfied.append({"condition": information, "expect": expect,
                                  "list": list_name})

    for spec in record.get("applies_when") or []:
        evaluate(spec, "applies_when")
    for spec in record.get("excludes_when") or []:
        evaluate(spec, "excludes_when")
    for key in record.get("required_information") or []:
        if key not in present and key not in needs:
            needs.append(key)

    return {
        "can_proceed": not blocked and not needs,
        "satisfied": satisfied,
        "violated": violated,
        "unknown": unknown,
        "needs_information": needs,
        "blocked": blocked,
    }


# ---------------------------------------------------------------------------
# Migration with backup (AGENTS #11; same recorded pattern as evidence.py)
# ---------------------------------------------------------------------------

ASSET_TABLES = tuple(TABLES.values())


def asset_tables_present(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'asset_%'"
        " ORDER BY name").fetchall()
    return [row[0] for row in rows]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply the additive assets DDL (idempotent); returns the table list."""
    conn.executescript(ASSETS_DDL)
    conn.commit()
    return asset_tables_present(conn)


def migrate_with_backup(db_path: Path) -> dict:
    """Recorded migration entry: backup FIRST (SQLite backup API), then apply.

    - A fresh database (file absent) is created directly; no backup is needed.
    - An existing database is snapshotted to
      ``<db parent>/backups/pre-assets-migration-<UTC>.sqlite`` before any DDL
      runs (Issue #15 失败与回滚).
    - ``works`` and all pre-existing tables are never rewritten; compatibility
      is asserted by tests (legacy rows stay byte-identical).
    """
    db_path = Path(db_path)
    backup_path = None
    if db_path.exists():
        from uuid import uuid4
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now_iso().replace("-", "").replace(":", "")
        backup_path = backup_dir / f"pre-assets-migration-{stamp}-{uuid4().hex[:6]}.sqlite"
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
            "asset_tables": tables, "integrity": integrity}


# ---------------------------------------------------------------------------
# Minimal demo asset chain (synthetic fixtures; Issue #15 交付范围 #5)
# ---------------------------------------------------------------------------

_SEED_KIND_ORDER = ("evaluation_case", "support_method", "interaction_profile",
                    "strategy")


def demo_fixture_paths() -> list:
    """Packaged demo fixture files (sorted by name for determinism)."""
    fixtures = resources.files("research_library.contracts.assets").joinpath("fixtures")
    return sorted(fixtures.iterdir(), key=lambda resource: resource.name)


def load_demo_fixtures() -> list[dict]:
    """Load the packaged demo chain as ``{"kind", "record", "source"}`` entries."""
    entries = []
    for resource in demo_fixture_paths():
        if not resource.name.endswith(".json"):
            continue
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "kind" not in payload or "record" not in payload:
            raise AssetsError(
                f"demo fixture {resource.name!r} must be an object with 'kind' and 'record'")
        entries.append({"kind": payload["kind"], "record": payload["record"],
                        "source": resource.name})
    if not entries:
        raise AssetsError("no demo fixtures found in the packaged assets contracts")
    return entries


def seed_demo(conn: sqlite3.Connection) -> dict:
    """Seed the minimal synthetic demo chain into a *synthetic* database.

    The guard refuses any database that already contains ``works`` rows — demo
    assets never enter the real research library (AGENTS #1/#14; ``demo-*``
    identifiers are synthetic-only). Insertion is idempotent: re-running
    reports every record as ``already_present`` instead of duplicating.
    Content hashes are computed at seed time; the records stored are exactly
    the packaged fixtures plus ``content_hash``.
    """
    works_count = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    if works_count:
        raise AssetsError(
            f"seed_demo refuses a database containing {works_count} works row(s): demo "
            "assets are synthetic-only and never enter the real research library")
    inserted, already_present, failed = [], [], []
    entries = {entry["source"]: entry for entry in load_demo_fixtures()}

    def order_key(source: str) -> int:
        kind = entries[source]["kind"]
        return list(_SEED_KIND_ORDER).index(kind)

    for source in sorted(entries, key=lambda name: (order_key(name), name)):
        entry = entries[source]
        kind, record = entry["kind"], entry["record"]
        if kind not in KINDS:
            raise AssetsError(f"demo fixture {source!r} has unknown kind {kind!r}")
        prepared = prepared_record(kind, record)
        prepared.setdefault("content_hash", compute_content_hash(prepared))
        try:
            stored = insert_record(conn, kind, prepared)
        except AssetsError as error:
            if "AS-Dup" in str(error):
                already_present.append(
                    {"source": source, "asset_ref":
                     f"{record.get('asset_id')}@{record.get('revision')}"})
                continue
            failed.append({"source": source, "error": str(error)})
            continue
        inserted.append({"source": source, "kind": kind,
                         "asset_ref": f"{stored['asset_id']}@{stored['revision']}"})
    if failed:
        raise AssetsError("seed_demo failed: " + json.dumps(failed, ensure_ascii=False))
    return {"inserted": inserted, "already_present": already_present,
            "demo_fixture_count": len(entries)}
