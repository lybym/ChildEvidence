"""Governance contract validation for CE-01R (standard library only).

Machine-checkable counterpart of the DRAFT v1.1 governance documents:

- ``validate(data, schema)``: a minimal JSON-Schema subset validator
  (type / enum / const / properties / required / items / minItems / maxItems /
  minLength / maxLength / pattern) — enough for the CE-01R contracts, zero
  third-party dependencies (AGENTS #9).
- Domain validators for decision records, research questions and label records
  (contract files under ``docs/governance/contracts/``).
- ``check_governance_docs(root)``: cross-file consistency checks over the four
  DRAFT v1.1 protocol documents, AGENTS.md, the governance documents and the
  POC errata pointer (see ``tests/test_governance_contracts.py``).

This module validates *contract files*; it never mutates data, the database or
the protocol documents. All DRAFT governance documents remain pending human
approval and must never be treated as effective rules by agents (AGENTS #23).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = ROOT / "docs" / "governance"
CONTRACTS_DIR = GOVERNANCE_DIR / "contracts"
POC_DIR = ROOT / "docs" / "assessment" / "2026-10-13-poc-tech-evaluation"

PROTOCOL_FILES = (
    "RESEARCH_METHODOLOGY.md",
    "SCREENING_PROTOCOL.md",
    "ANNOTATION_GUIDE.md",
    "KNOWLEDGE_GOVERNANCE.md",
)

DRAFT_VERSION = "DRAFT v1.1"

CONTRACT_FILES = {
    "decision-scope": "CE-01R-decision-scope.contract.json",
    "rq-registry": "CE-01R-rq-registry.contract.json",
    "example-rqs": "CE-01R-example-research-questions.json",
    "label-tiers": "CE-01R-label-tiers.contract.json",
    "poc-metrics-latest": "CE-01R-poc-metrics-latest.json",
}


# ---------------------------------------------------------------------------
# Minimal JSON-Schema subset validator
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value, expected, errors, path):
    allowed = [expected] if isinstance(expected, str) else list(expected)
    for name in allowed:
        if isinstance(value, bool) and name != "boolean":
            continue  # bool is an int subclass; only match an explicit boolean
        if isinstance(value, _TYPE_MAP[name]):
            return
    errors.append(f"{path}: expected type {'/'.join(allowed)}, got {type(value).__name__}")


def validate(data, schema, path="$"):
    """Validate ``data`` against the mini JSON-Schema subset. Returns error list."""
    errors: list[str] = []
    _validate(data, schema, path, errors)
    return errors


def _validate(data, schema, path, errors):
    if not isinstance(schema, dict):
        errors.append(f"{path}: invalid schema node (not an object)")
        return
    before = len(errors)
    if "type" in schema:
        _check_type(data, schema["type"], errors, path)
        if len(errors) > before:
            return  # type mismatch: dependent checks would cascade
    if "const" in schema and data != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {data!r}")
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} not in enum {schema['enum']!r}")
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength={schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength={schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], data) is None:
            errors.append(f"{path}: {data!r} does not match pattern {schema['pattern']!r}")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems={schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems={schema['maxItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                _validate(item, item_schema, f"{path}[{i}]", errors)
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required property {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in data:
                _validate(data[key], sub, f"{path}.{key}", errors)


# ---------------------------------------------------------------------------
# Contract file loading
# ---------------------------------------------------------------------------


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_contract(name: str):
    """Load a CE-01R contract file by short name and validate its envelope."""
    path = CONTRACTS_DIR / CONTRACT_FILES[name]
    data = load_json(path)
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append(f"{path.name}: contract root is not an object")
        return data, errors
    if data.get("$schema_version") != 1:
        errors.append(f"{path.name}: unsupported $schema_version {data.get('$schema_version')!r}")
    if not data.get("$schema_name", "").startswith("childevidence-ce01r-"):
        errors.append(f"{path.name}: unexpected $schema_name {data.get('$schema_name')!r}")
    if "status" not in data:
        errors.append(f"{path.name}: missing status header (draft-pending marker)")
    elif "pending human approval" not in data["status"]:
        errors.append(f"{path.name}: status must declare 'pending human approval'")
    return data, errors


def validate_with_embedded_schema(data, schema_owner, errors, label):
    schema = schema_owner.get("schema")
    if not isinstance(schema, dict):
        errors.append(f"{label}: contract has no embedded schema")
        return
    errors.extend(validate(data, schema, label))


# ---------------------------------------------------------------------------
# Domain validators (contract + cross-field rules)
# ---------------------------------------------------------------------------


def validate_decision_record(record: dict) -> list[str]:
    """Validate a catalog/review decision record against the decision-scope contract."""
    contract, errors = load_contract("decision-scope")
    validate_with_embedded_schema(record, contract, errors, "decision_record")
    layer = record.get("layer")
    decision = record.get("decision")
    if layer == "catalog":
        if decision not in ("ingested", "rejected", "pending"):
            errors.append("DS-01: catalog decision must be ingested/rejected/pending")
        if record.get("rq_id") is not None:
            errors.append("DS-01: catalog record must not carry rq_id")
    elif layer == "review":
        if decision not in ("included", "excluded", "pending"):
            errors.append("DS-02: review decision must be included/excluded/pending")
        if not record.get("rq_id") or record.get("rq_version") is None:
            errors.append("DS-02: review record requires rq_id and rq_version")
        if record.get("track") != "review":
            errors.append("DS-02: review record must set track='review'")
    tier = record.get("label_tier")
    if tier == "gold" and record.get("produced_by_kind") not in (None, "adjudicated_human", "independent_double_human"):
        errors.append("LT-03/LT-04: gold requires adjudicated or independently double-reviewed human origin")
    return errors


def validate_research_question(rq: dict) -> list[str]:
    """Validate one research question against the rq-registry contract."""
    contract, errors = load_contract("rq-registry")
    validate_with_embedded_schema(rq, contract, errors, "research_question")
    if rq.get("status") == "active" and not rq.get("approved_by"):
        errors.append("RQ-01: active RQ requires human approved_by")
    if rq.get("status") == "retired" and not rq.get("retire_reason"):
        errors.append("RQ-02: retired RQ requires retire_reason")
    history = rq.get("history") or []
    if not any(h.get("version") == rq.get("version") for h in history):
        errors.append("RQ-03: history must contain a record for the current version")
    return errors


def validate_label_record(record: dict) -> list[str]:
    """Validate a label record against the label-tiers contract."""
    contract, errors = load_contract("label-tiers")
    validate_with_embedded_schema(record, contract, errors, "label_record")
    tier = record.get("label_tier")
    kind = record.get("produced_by_kind")
    if tier == "silver" and kind not in ("model", "rule"):
        errors.append("LT-01: silver requires model/rule origin")
    if tier == "provisional" and kind != "single_human":
        errors.append("LT-02: provisional requires single_human origin")
    if tier == "gold":
        if kind not in ("adjudicated_human", "independent_double_human"):
            errors.append("LT-03: gold requires adjudicated_human/independent_double_human")
        if not record.get("sign_off_by") or not record.get("sign_off_date"):
            errors.append("LT-03: gold requires human sign-off (by + date)")
    if kind in ("model", "rule") and tier in ("provisional", "gold"):
        errors.append("LT-04: model/rule output must not self-confirm provisional/gold")
    return errors


# ---------------------------------------------------------------------------
# POC errata pointer cross-check
# ---------------------------------------------------------------------------


def check_poc_metrics_pointer() -> tuple[list[str], list[str]]:
    """Verify the machine-readable errata pointer against the v2 summary CSV."""
    errors: list[str] = []
    warnings: list[str] = []
    pointer, perr = load_contract("poc-metrics-latest")
    errors.extend(f"poc-metrics-latest: {e}" for e in perr)
    if errors:
        return errors, warnings

    for key in ("source_of_truth", "values", "models", "supersedes"):
        if key not in pointer:
            errors.append(f"poc-metrics-latest: missing {key!r}")
    if errors:
        return errors, warnings

    csv_path = ROOT / pointer["source_of_truth"]["v2_summary_csv"]
    if not csv_path.exists():
        return [f"poc-metrics-latest: v2 summary CSV missing: {csv_path}"], warnings

    with open(csv_path, "r", encoding="utf-8", newline="") as fh:
        rows = {row["model"]: row for row in csv.DictReader(fh)}

    colmap = pointer.get("values_source_columns", {})
    for model in pointer["models"]:
        row = rows.get(model)
        if row is None:
            errors.append(f"poc-metrics-latest: model {model!r} missing in v2 summary CSV")
            continue
        for field, columns in colmap.items():
            expected_raw = row.get(columns)
            got = pointer["values"].get(model, {}).get(field)
            if expected_raw is None or got is None:
                errors.append(f"poc-metrics-latest: {model}.{field} missing on either side")
                continue
            expected = float(expected_raw)
            if abs(float(got) - expected) > 1e-9:
                errors.append(
                    f"poc-metrics-latest: {model}.{field} pointer={got} != CSV {expected}"
                )

    for item in pointer["supersedes"]:
        sup_path = ROOT / item["file"]
        if not sup_path.exists():
            errors.append(f"poc-metrics-latest: superseded file missing: {item['file']}")

    final_rec = POC_DIR / "FINAL_RECOMMENDATION.md"
    if not final_rec.exists():
        errors.append("poc-metrics-latest: FINAL_RECOMMENDATION.md missing")
    else:
        text = final_rec.read_text(encoding="utf-8")
        if "CE-01R-ERRATA.md" not in text:
            errors.append("errata: FINAL_RECOMMENDATION.md lacks the errata pointer header")
        # Original v1 numbers must be preserved (never rewritten).
        for probe in ("0.118±.018", "0.152±.011", "| 59 | 68 | 71 | 127 | 136 |"):
            if probe not in text:
                errors.append(f"errata: original v1 record was altered (missing {probe!r})")
    return errors, warnings


# ---------------------------------------------------------------------------
# Cross-document consistency
# ---------------------------------------------------------------------------


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def check_governance_docs(root: Path | None = None) -> tuple[list[str], list[str]]:
    """Cross-file consistency checks for the CE-01R DRAFT v1.1 document set.

    Returns ``(errors, warnings)``; empty errors means the document set is
    self-consistent (still pending human approval).
    """
    root = root or ROOT
    errors: list[str] = []
    warnings: list[str] = []

    # 1) Four protocol documents share the DRAFT v1.1 pending-approval header.
    for rel in PROTOCOL_FILES:
        try:
            text = _read(root, rel)
        except OSError as exc:
            errors.append(f"{rel}: unreadable ({exc})")
            continue
        if DRAFT_VERSION not in text:
            errors.append(f"{rel}: missing {DRAFT_VERSION} status header")
        if "待人工审核" not in text:
            errors.append(f"{rel}: missing pending-human-review marker")
        if "CE-01R-REVIEW.md" not in text and "CE-01R-CHECKLIST.md" not in text:
            errors.append(f"{rel}: missing pointer to governance review/checklist docs")
        if not re.search(r"\|\s*DRAFT v1\.1\s*\|\s*2026-10-13\s*\|", text):
            errors.append(f"{rel}: missing v1.1 change-log row")
        for banned in ("APPROVED", "已生效", "EFFECTIVE v1.1"):
            if banned in text:
                errors.append(f"{rel}: must not auto-approve itself (found {banned!r})")

    # 2) Governance documents exist with the right roles.
    for rel, marker in (
        ("docs/governance/CE-01R-REVIEW.md", "R1"),
        ("docs/governance/CE-01R-CHECKLIST.md", "最终生效签署"),
        ("docs/governance/CE-01R-ERRATA.md", "supersedes"),
    ):
        try:
            text = _read(root, rel)
        except OSError as exc:
            errors.append(f"{rel}: unreadable ({exc})")
            continue
        if marker not in text:
            errors.append(f"{rel}: missing expected marker {marker!r}")

    # 3) Contracts exist, parse, and carry the pending-approval envelope.
    contracts = {}
    for name, rel in CONTRACT_FILES.items():
        path = root / "docs" / "governance" / "contracts" / rel
        if not path.exists():
            errors.append(f"contracts: missing {rel}")
            continue
        try:
            data, cerr = load_contract(name) if root == ROOT else (load_json(path), [])
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel}: invalid JSON ({exc})")
            continue
        for e in cerr:
            errors.append(f"{rel}: {e}")
        contracts[name] = data

    if len(contracts) == len(CONTRACT_FILES):
        # 3a) Example RQs validate against the registry contract + rules.
        rqs = contracts["example-rqs"].get("research_questions", [])
        if len(rqs) != 3:
            errors.append(f"example-rqs: expected 3 example RQs, got {len(rqs)}")
        ids = [rq.get("rq_id") for rq in rqs]
        if len(set(ids)) != len(ids):
            errors.append("example-rqs: duplicate rq_id values")
        for rq in rqs:
            for e in validate_research_question(rq):
                errors.append(f"example-rqs[{rq.get('rq_id')}]: {e}")
        if not any("task-initiation" in (i or "") for i in ids):
            errors.append("example-rqs: missing task-initiation/avoidance example")
        if not any("emotion-regulation" in (i or "") for i in ids):
            errors.append("example-rqs: missing emotion-regulation example")
        if not any("ai-companion" in (i or "") for i in ids):
            errors.append("example-rqs: missing child-AI-companion example")
        # 3b) decision-scope examples validate; review example must cite a real RQ.
        for ex in contracts["decision-scope"].get("examples", []):
            for e in validate_decision_record(ex):
                errors.append(f"decision-scope examples: {e}")
        review_examples = [
            ex for ex in contracts["decision-scope"].get("examples", [])
            if ex.get("layer") == "review"
        ]
        for ex in review_examples:
            if ex.get("rq_id") not in ids:
                errors.append(
                    f"decision-scope examples: rq_id {ex.get('rq_id')!r} not in example RQ registry"
                )
        # 3c) label-tiers examples validate.
        for ex in contracts["label-tiers"].get("examples", []):
            for e in validate_label_record(ex):
                errors.append(f"label-tiers examples: {e}")
        # 3d) POC errata pointer cross-checked against the v2 CSV.
        perr, pwarn = check_poc_metrics_pointer()
        errors.extend(perr)
        warnings.extend(pwarn)

    # 4) AGENTS.md states the agent-side constraints.
    try:
        agents = _read(root, "AGENTS.md")
    except OSError as exc:
        errors.append(f"AGENTS.md: unreadable ({exc})")
        agents = ""
    if DRAFT_VERSION not in agents:
        errors.append("AGENTS.md: governance section not updated to DRAFT v1.1")
    if "被当作不可变规范引用" not in agents:
        errors.append("AGENTS.md: derived-snapshot rule (#22) missing")
    if "DRAFT 规程不可被 Agent 当作生效准则" not in agents:
        errors.append("AGENTS.md: draft-not-effective rule (#23) missing")
    if "test_governance_contracts.py" not in agents:
        errors.append("AGENTS.md: consistency-test rule (#24) missing")
    if "证据分级遵循\n   `docs/research/research-taxonomy.md`。" in agents:
        errors.append("AGENTS.md: rule 5 still cites a generated snapshot as the norm")
    # The pending-approval checklist must stay unsigned and forbid auto-approval.
    try:
        checklist = _read(root, "docs/governance/CE-01R-CHECKLIST.md")
    except OSError as exc:
        errors.append(f"docs/governance/CE-01R-CHECKLIST.md: unreadable ({exc})")
    else:
        if "不得自动勾选、代签" not in checklist:
            errors.append("CHECKLIST: missing no-auto-sign guard")
        if re.search(r"\|\s*(APPROVE)\s*\|", checklist):
            errors.append("CHECKLIST: an APPROVE decision appears to be pre-filled")

    return errors, warnings
