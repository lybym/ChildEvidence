"""Normalized parse-result schema (ce03-parse v1) and its validator.

The schema is the *contract* between the parsing layer and every downstream
consumer (search, CE-04 gold benchmark, CE-05 evidence model). Design rules
fixed by issue #3:

- Physical page numbers are the localization basis; printed page numbers are
  stored per page and stay ``null`` until a human correction supplies them.
  No fixed page-offset heuristics anywhere.
- A bbox field records that a coordinate was *extracted*; it never asserts
  that the coordinate is correct. ``localization.verified`` is always false in
  this layer (accuracy measurement belongs to CE-04).
- Missing information is ``null`` with a reason, never invented.
- Every record carries provenance: source SHA-256, parser name/version,
  model/dependency versions, and the transform chain.
"""

from __future__ import annotations

from . import SCHEMA_NAME, SCHEMA_VERSION

STATUSES = ("ok", "degraded", "fallback", "failed")
PARAGRAPH_KINDS = (
    "paragraph", "section_header", "list_item", "footnote", "caption",
    "table_caption", "other",
)
LOCALIZATION_STATUSES = ("recorded", "unavailable")


def new_document_result() -> dict:
    """Skeleton of a normalized result (documents are built by normalize.py)."""
    return {
        "schema": {"name": SCHEMA_NAME, "version": SCHEMA_VERSION},
        "document_id": None,
        "source": {
            "path": None,
            "file_name": None,
            "size_bytes": None,
            "sha256": None,
            "integrity": {"header_ok": None, "eof_ok": None, "validated": None},
        },
        "parser": {
            "name": None,
            "parser_version": None,
            "model_versions": {},
            "dependency_versions": {},
            "options": {},
            "options_hash": None,
        },
        "status": None,
        "failure_reasons": [],
        "warnings": [],
        "issues": [],
        "language": "unknown",
        "page_count": None,
        "pages": [],
        "sections": [],
        "paragraphs": [],
        "tables": [],
        "references": {
            "supported_by_parser": None,
            "items": None,
            "note": None,
        },
        "localization_summary": {
            "paragraphs_total": None,
            "paragraphs_with_bbox": None,
            "tables_total": None,
            "tables_with_bbox": None,
            "bbox_presence_rate": None,
            "localization_accuracy": None,
            "notes": None,
        },
        "provenance": {
            "produced_at_utc": None,
            "duration_sec": None,
            "peak_memory_mb": None,
            "transform_chain": [],
            "normalize_version": f"{SCHEMA_NAME}/{SCHEMA_VERSION}",
        },
        "artifact": {
            "artifact_id": None,
            "output_dir": None,
            "page_map_applied": None,
        },
    }


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _err(errors: list[str], msg: str) -> None:
    errors.append(msg)


def validate_result(doc: dict) -> list[str]:
    """Validate a normalized result document.

    Returns a list of human-readable error strings; empty list means valid.
    Validation is structural and self-consistency only (no content judgment).
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["result: not an object"]

    schema = doc.get("schema") or {}
    if schema.get("name") != SCHEMA_NAME:
        _err(errors, f"schema.name: expected {SCHEMA_NAME!r}")
    if schema.get("version") != SCHEMA_VERSION:
        _err(errors, f"schema.version: expected {SCHEMA_VERSION!r}")

    status = doc.get("status")
    if status not in STATUSES:
        _err(errors, f"status: invalid {status!r}")

    src = doc.get("source") or {}
    sha = src.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        _err(errors, "source.sha256: missing or not a lowercase hex sha256")

    parser = doc.get("parser") or {}
    if not parser.get("name"):
        _err(errors, "parser.name: missing")
    if not parser.get("parser_version"):
        _err(errors, "parser.parser_version: missing")

    page_count = doc.get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        _err(errors, f"page_count: invalid {page_count!r}")

    pages = doc.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        _err(errors, "pages: list length must equal page_count")
        pages = pages if isinstance(pages, list) else []
    page_nos = set()
    for i, p in enumerate(pages):
        pp = p.get("physical_page_no")
        if pp != i + 1:
            _err(errors, f"pages[{i}].physical_page_no: must be {i + 1} (1-based, sequential)")
        page_nos.add(pp)
        # printed page: None is the honest default; manual origin is tracked
        if p.get("printed_page_no") is not None:
            origin = p.get("printed_page_origin")
            if origin != "manual":
                _err(errors,
                     f"pages[{i}].printed_page_no set without printed_page_origin=manual "
                     "(printed pages must never be inferred)")

    for i, par in enumerate(doc.get("paragraphs") or []):
        pid = par.get("paragraph_id")
        if not pid:
            _err(errors, f"paragraphs[{i}].paragraph_id: missing")
        if par.get("kind") not in PARAGRAPH_KINDS:
            _err(errors, f"paragraphs[{i}] ({pid}): invalid kind {par.get('kind')!r}")
        if not isinstance(par.get("text"), str):
            _err(errors, f"paragraphs[{i}] ({pid}): text must be a string (use '' if empty)")
        pp = par.get("physical_page_no")
        if pp is not None and pp not in page_nos:
            _err(errors, f"paragraphs[{i}] ({pid}): physical_page_no {pp!r} not in pages")
        prov = par.get("provenance") or {}
        bbox = prov.get("bbox")
        if bbox is not None:
            if not (isinstance(bbox, list) and len(bbox) == 4
                    and all(isinstance(v, (int, float)) for v in bbox)):
                _err(errors, f"paragraphs[{i}] ({pid}): bbox must be [l,t,r,b] numbers or null")
            if prov.get("localization", {}).get("status") != "recorded":
                _err(errors, f"paragraphs[{i}] ({pid}): bbox present but localization.status != recorded")
            if prov.get("localization", {}).get("verified") is not False:
                _err(errors, f"paragraphs[{i}] ({pid}): localization.verified must be false in parse layer")
        else:
            if prov.get("localization", {}).get("status") != "unavailable":
                _err(errors, f"paragraphs[{i}] ({pid}): no bbox but localization.status != unavailable")

    for i, tbl in enumerate(doc.get("tables") or []):
        tid = tbl.get("table_id")
        if not tid:
            _err(errors, f"tables[{i}].table_id: missing")
        cells = tbl.get("cells")
        if cells is not None:
            if not isinstance(cells, list):
                _err(errors, f"tables[{i}] ({tid}): cells must be list or null")
            elif len(cells) > 1 and len({len(r) for r in cells}) > 1:
                # ragged grids are allowed only when flagged
                if "table_ragged_grid" not in (tbl.get("issues") or []):
                    _err(errors, f"tables[{i}] ({tid}): ragged cells without issue flag table_ragged_grid")
        prov = tbl.get("provenance") or {}
        if prov.get("bbox") is None and (prov.get("localization") or {}).get("status") != "unavailable":
            _err(errors, f"tables[{i}] ({tid}): no bbox but localization.status != unavailable")

    refs = doc.get("references") or {}
    if refs.get("items") is None and not refs.get("note"):
        _err(errors, "references: null items require a note explaining why")

    if status in ("degraded", "fallback", "failed") and not (doc.get("failure_reasons") or doc.get("issues")):
        _err(errors, f"status={status} requires failure_reasons or issues to explain the state")
    if status == "failed" and not doc.get("failure_reasons"):
        _err(errors, "status=failed requires failure_reasons")

    loc = doc.get("localization_summary") or {}
    if loc.get("localization_accuracy") is not None:
        _err(errors,
             "localization_summary.localization_accuracy must be null in the parse layer "
             "(accuracy requires CE-04 human gold)")
    total = loc.get("paragraphs_total")
    with_bbox = loc.get("paragraphs_with_bbox")
    if isinstance(total, int) and isinstance(with_bbox, int):
        if with_bbox > total:
            _err(errors, "localization_summary: paragraphs_with_bbox > paragraphs_total")
        rate = loc.get("bbox_presence_rate")
        if total > 0:
            if rate is None or abs(rate - with_bbox / total) > 1e-9:
                _err(errors, "localization_summary.bbox_presence_rate != with_bbox/total")
    return errors


def compute_localization_summary(doc: dict) -> dict:
    """(Re)compute the localization summary from paragraphs/tables."""
    paras = doc.get("paragraphs") or []
    tables = doc.get("tables") or []
    total = len(paras)
    with_bbox = sum(1 for p in paras if (p.get("provenance") or {}).get("bbox") is not None)
    t_total = len(tables)
    t_bbox = sum(1 for t in tables if (t.get("provenance") or {}).get("bbox") is not None)
    rate = (with_bbox / total) if total else None
    return {
        "paragraphs_total": total,
        "paragraphs_with_bbox": with_bbox,
        "tables_total": t_total,
        "tables_with_bbox": t_bbox,
        "bbox_presence_rate": round(rate, 6) if rate is not None else None,
        "localization_accuracy": None,
        "notes": (
            "bbox_presence_rate is a FIELD-PRESENCE metric only; it does not measure "
            "localization correctness. Accuracy requires the CE-04 independent human "
            "gold benchmark; 12/12 POC AI spot-checks are not human gold and no "
            "production-level >=95% accuracy is claimed anywhere."
        ),
    }
