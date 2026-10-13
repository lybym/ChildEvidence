"""Intermediate document -> normalized ce03-parse v1 result (pure functions).

This layer owns IDs, reading order, section grouping, localization records,
honest nulls (references), CID/mojibake flags and the transform chain. It is
parser-agnostic: the same code path serves Docling, pdfplumber and any future
adapter. It never invents content: unknown stays null.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .. import SCHEMA_NAME, SCHEMA_VERSION
from .. import cidcheck
from .base import INTERMEDIATE_FORMAT_VERSION

_KIND_MAP = {
    "paragraph": "paragraph",
    "section_header": "section_header",
    "list_item": "list_item",
    "footnote": "footnote",
    "caption": "caption",
    "text": "paragraph",
    "other": "other",
}


def options_hash(options: dict) -> str:
    payload = json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_intermediate(
    inter: dict,
    *,
    source: dict,
    document_id: str | None,
    options: dict,
    status: str,
    failure_reasons: list[dict] | None = None,
    duration_sec: float | None = None,
    peak_memory_mb: float | None = None,
) -> dict:
    """Build the normalized result from an adapter intermediate document."""
    if inter.get("format_version") != INTERMEDIATE_FORMAT_VERSION:
        raise ValueError(
            f"intermediate format_version {inter.get('format_version')!r} != {INTERMEDIATE_FORMAT_VERSION}"
        )
    parser_info = inter.get("parser") or {}
    pages_in = inter.get("pages") or []
    items_in = inter.get("items") or []

    doc: dict = {
        "schema": {"name": SCHEMA_NAME, "version": SCHEMA_VERSION},
        "document_id": document_id,
        "source": {
            "path": source.get("path"),
            "file_name": source.get("file_name"),
            "size_bytes": source.get("size_bytes"),
            "sha256": source.get("sha256"),
            "integrity": {
                "header_ok": source.get("header_ok"),
                "eof_ok": source.get("eof_ok"),
                "validated": source.get("validated"),
            },
        },
        "parser": {
            "name": parser_info.get("name"),
            "parser_version": parser_info.get("parser_version"),
            "model_versions": parser_info.get("model_versions") or {},
            "dependency_versions": parser_info.get("dependency_versions") or {},
            "options": options,
            "options_hash": options_hash(options),
        },
        "status": status,
        "failure_reasons": failure_reasons or [],
        "warnings": list(inter.get("warnings") or []) + list(parser_info.get("warnings") or []),
        "issues": [],
        "language": inter.get("language_hint") or "unknown",
        "page_count": inter.get("page_count"),
        "pages": [],
        "sections": [],
        "paragraphs": [],
        "tables": [],
        "references": {
            "supported_by_parser": bool(parser_info.get("references_supported", False)),
            "items": None,
            "note": (
                "reference segmentation is not provided by this parser version; "
                "recorded as null instead of guessing (issue #3 honest-missing rule)"
            ),
        },
        "localization_summary": {},
        "provenance": {
            "produced_at_utc": _now_utc(),
            "duration_sec": round(duration_sec, 3) if duration_sec is not None else None,
            "peak_memory_mb": round(peak_memory_mb, 1) if peak_memory_mb is not None else None,
            "transform_chain": [
                {
                    "step": f"{parser_info.get('name')}.parse",
                    "parser_version": parser_info.get("parser_version"),
                },
                {
                    "step": "normalize_intermediate",
                    "version": f"{SCHEMA_NAME}/{SCHEMA_VERSION}",
                },
            ],
            "source_item_labels": _collect_labels(items_in),
        },
        "artifact": {
            "artifact_id": None,
            "output_dir": None,
            "page_map_applied": None,
        },
    }

    # ---- pages ----------------------------------------------------------
    total_chars = 0
    pages_issues: list[list[str]] = []
    for i, p in enumerate(pages_in):
        text = p.get("text") or ""
        total_chars += len(text)
        p_issues = cidcheck.page_text_issues(text)
        pages_issues.append(p_issues)
        page_issues = list(p_issues)
        if "page_no_text" in page_issues:
            page_issues.remove("page_no_text")
            page_issues.append("no_text_layer_suspected")
        doc["pages"].append({
            "physical_page_no": p.get("physical_page_no", i + 1),
            "printed_page_no": None,          # filled only from manual page map
            "printed_page_origin": None,
            "width": p.get("width"),
            "height": p.get("height"),
            "text_present": len(text) > 0,
            "char_count": len(text),
            "issues": page_issues,
        })
    doc["language"] = inter.get("language_hint") or cidcheck.document_language(
        [p.get("text") or "" for p in pages_in]
    )
    doc["issues"] = cidcheck.document_issues(pages_issues, total_chars)
    if total_chars < cidcheck.ZERO_TEXT_DOC_CHARS and doc["status"] == "ok":
        doc["status"] = "degraded"
        doc["failure_reasons"].append({
            "stage": "normalize",
            "code": "no_text_extracted",
            "message": "extracted text below threshold; document may be scanned or empty",
        })
    if doc["issues"] and doc["status"] == "ok":
        doc["status"] = "degraded"
        doc["failure_reasons"].append({
            "stage": "normalize",
            "code": "quality_flags_present",
            "message": "text-quality flags present (see issues); content kept, flagged for review",
        })

    # ---- items (reading order preserved) --------------------------------
    par_idx = 0
    sec_idx = 0
    tbl_idx = 0
    open_section = None
    ro = 0
    for item in items_in:
        ro += 1
        kind_raw = item.get("kind") or "other"
        page_no = item.get("physical_page_no")
        bbox = item.get("bbox")
        char_span = item.get("char_span")

        if item.get("table") is not None:
            tbl_idx += 1
            tinfo = item["table"]
            cells = tinfo.get("cells")
            t_issues: list[str] = []
            if cells is not None and len(cells) > 1 and len({len(r) for r in cells}) > 1:
                t_issues.append("table_ragged_grid")
            flat = "".join(c or "" for row in (cells or []) for c in row)
            if flat:
                t_issues.extend(cidcheck.page_text_issues(flat))
            if cells is not None and cells:
                n_cells = sum(len(r) for r in cells)
                empty = sum(1 for row in cells for c in row if not (c or "").strip())
                if n_cells and empty / n_cells > 0.8:
                    t_issues.append("table_structure_uncertain")
            doc["tables"].append({
                "table_id": f"tbl-{tbl_idx:04d}",
                "reading_order_index": ro,
                "physical_page_no": page_no,
                "printed_page_no": None,
                "n_rows": tinfo.get("n_rows"),
                "n_cols": tinfo.get("n_cols"),
                "cells": cells,
                "extraction_method": tinfo.get("extraction_method"),
                "issues": t_issues,
                "provenance": _prov(bbox, char_span, item),
            })
            continue

        text = item.get("text")
        if text is None:
            text = ""
        kind = _KIND_MAP.get(kind_raw, "other")
        t_issues = cidcheck.page_text_issues(text)
        par_idx += 1
        par = {
            "paragraph_id": f"par-{par_idx:04d}",
            "kind": kind,
            "text": text,
            "reading_order_index": ro,
            "section_id": None,
            "physical_page_no": page_no,
            "printed_page_no": None,
            "char_span": char_span,
            "issues": [c for c in t_issues if c != "page_no_text"],
            "provenance": _prov(bbox, char_span, item),
        }
        if kind == "section_header":
            sec_idx += 1
            section = {
                "section_id": f"sec-{sec_idx:04d}",
                "title": text,
                "heading_level": item.get("heading_level"),
                "reading_order_index": ro,
                "paragraph_ids": [],
                "provenance": _prov(bbox, char_span, item),
            }
            doc["sections"].append(section)
            open_section = section["section_id"]
            par["section_id"] = open_section
        elif open_section is not None:
            par["section_id"] = open_section
        doc["paragraphs"].append(par)

    doc["localization_summary"] = _summary(doc)
    return doc


def _prov(bbox, char_span, item: dict) -> dict:
    if bbox is None:
        loc = {"status": "unavailable", "verified": False}
    else:
        loc = {"status": "recorded", "verified": False}
    return {
        "origin": item.get("label"),
        "bbox": bbox,
        "bbox_space": item.get("bbox_space") or ("pdf_points_y_down" if bbox else None),
        "page_size": item.get("page_size"),
        "char_span_space": item.get("char_span_space"),
        "localization": loc,
    }


def _summary(doc: dict) -> dict:
    paras = doc["paragraphs"]
    tables = doc["tables"]
    total = len(paras)
    with_bbox = sum(1 for p in paras if p["provenance"]["bbox"] is not None)
    t_total = len(tables)
    t_bbox = sum(1 for t in tables if t["provenance"]["bbox"] is not None)
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
            "gold benchmark; the POC 12/12 AI spot-checks are not human gold and no "
            "production-level accuracy (>=95%) is claimed."
        ),
    }


def _collect_labels(items_in: list[dict]) -> dict:
    labels: dict[str, int] = {}
    for item in items_in:
        lab = item.get("label") or "none"
        labels[lab] = labels.get(lab, 0) + 1
    return labels
