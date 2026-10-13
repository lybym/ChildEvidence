"""Physical vs printed page separation and human-correctable page maps.

Policy (issue #3, hard rule):

- The *physical* page (1-based position inside the PDF file) is the only
  localization basis.
- The *printed* page number (what is typeset on the page) is UNKNOWN by
  default and stays ``null``. The pipeline never infers it from a fixed
  offset: real documents mix front-matter offsets, per-chapter restarts and
  roman numerals, and a wrong guessed offset silently corrupts every citation.
- Printed pages enter the record ONLY through a human-written corrections
  file, and the correction is recorded with origin=manual and its source.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CORRECTIONS_FORMAT_VERSION = 1


def empty_page_map(page_count: int) -> dict:
    """A fresh page map: printed pages unknown (null), physical pages 1..N."""
    return {
        "format_version": CORRECTIONS_FORMAT_VERSION,
        "document_id": None,
        "source_sha256": None,
        "policy": (
            "physical pages are the localization basis; printed_page_no stays null "
            "until a human correction supplies it; no fixed-offset inference is used"
        ),
        "entries": [
            {
                "physical_page_no": i + 1,
                "printed_page_no": None,
                "printed_page_origin": None,
                "note": None,
            }
            for i in range(page_count)
        ],
        "manual_corrections_applied": [],
    }


def load_corrections(path: Path) -> list[dict]:
    """Load a manual corrections file.

    Expected format (JSON): a list of objects with integer fields
    ``physical_page_no`` and ``printed_page_no`` (printed may be null to
    explicitly clear a previous value). Any other shape raises ValueError.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("page-map corrections file must be a JSON list")
    out: list[dict] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"corrections[{i}]: must be an object")
        pp = item.get("physical_page_no")
        if not isinstance(pp, int) or pp < 1:
            raise ValueError(f"corrections[{i}].physical_page_no: positive int required")
        printed = item.get("printed_page_no")
        if printed is not None and not isinstance(printed, int):
            raise ValueError(f"corrections[{i}].printed_page_no: int or null required")
        note = item.get("note")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"corrections[{i}].note: string or null required")
        out.append({"physical_page_no": pp, "printed_page_no": printed, "note": note})
    return out


def apply_corrections(page_map: dict, corrections: list[dict], source_file: str | None = None) -> dict:
    """Merge human corrections into a page map (returns a new dict).

    Corrections are additive and auditable: each applied entry is recorded
    under manual_corrections_applied with its source file and time. Applying
    the same correction twice is idempotent (same value, one applied-record
    per input entry per invocation).
    """
    if not corrections:
        return page_map
    merged = json.loads(json.dumps(page_map, ensure_ascii=False))  # deep copy
    by_pp = {e["physical_page_no"]: e for e in merged["entries"]}
    applied = merged.setdefault("manual_corrections_applied", [])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for c in corrections:
        pp = c["physical_page_no"]
        if pp not in by_pp:
            raise ValueError(
                f"correction for physical page {pp} out of range "
                f"(document has {len(merged['entries'])} pages)"
            )
        entry = by_pp[pp]
        entry["printed_page_no"] = c["printed_page_no"]
        entry["printed_page_origin"] = "manual"
        entry["note"] = c.get("note")
        applied.append({
            "physical_page_no": pp,
            "printed_page_no": c["printed_page_no"],
            "origin": "manual",
            "from_file": source_file,
            "applied_at": now,
        })
    return merged


def load_or_create_page_map(path: Path, page_count: int) -> dict:
    """Load an existing page map if valid, else create a fresh one."""
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("format_version") == CORRECTIONS_FORMAT_VERSION \
                    and isinstance(data.get("entries"), list) \
                    and len(data["entries"]) == page_count:
                return data
        except (json.JSONDecodeError, OSError):
            pass
        # invalid/foreign content: caller recreates it (cache pollution policy)
        return None
    return None


def corrections_for_document(corrections_dir: Path, document_id: str) -> tuple[list[dict], str | None]:
    """Find a manual corrections file for a document id.

    Accepted file names: <document_id>.json or <document_id>.page-map.json.
    Returns (corrections, source_path_or_None).
    """
    d = Path(corrections_dir)
    if not d.exists():
        return [], None
    for name in (f"{document_id}.json", f"{document_id}.page-map.json"):
        p = d / name
        if p.exists():
            return load_corrections(p), str(p)
    return [], None


def sync_pages_from_map(doc: dict, page_map: dict) -> None:
    """Copy printed-page info from the page map into result.pages.

    Only manual corrections ever set printed_page_no; origin travels with it.
    """
    entries = {e["physical_page_no"]: e for e in page_map.get("entries", [])}
    for page in doc.get("pages", []):
        e = entries.get(page.get("physical_page_no"))
        if not e:
            continue
        page["printed_page_no"] = e.get("printed_page_no")
        page["printed_page_origin"] = e.get("printed_page_origin")
