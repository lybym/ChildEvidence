"""PdfPlumberParser adapter (configurable fallback, line-level coordinates).

pdfplumber is imported lazily. It provides text lines and table bboxes but no
document structure (no sections, no reading order beyond its own line order,
no reference segmentation). The intermediate document records exactly that:
line-level "paragraph" items flagged as line granularity, sections empty, and
honest nulls everywhere else.
"""

from __future__ import annotations

import importlib.metadata as _md
import json
from pathlib import Path

from .base import DependencyMissing, empty_intermediate


class PdfPlumberParser:
    name = "pdfplumber"

    def probe(self) -> dict:
        """Lightweight identity probe (import only, no file access)."""
        try:
            import pdfplumber
            version = getattr(pdfplumber, "__version__", None)
            if version is None:
                version = _md.version("pdfplumber")
        except Exception as e:
            raise DependencyMissing(
                f"pdfplumber is not installed in this Python environment: {e!r}"
            ) from e
        return {"name": self.name, "parser_version": version, "model_versions": {}}

    def parse(self, pdf_path: Path, options: dict) -> dict:
        try:
            import pdfplumber
        except Exception as e:
            raise DependencyMissing(
                "pdfplumber is not installed in this Python environment. "
                "Install the optional parsing extra in an isolated venv "
                "(see docs/parsing/README.md). "
                f"Underlying import error: {e!r}"
            ) from e

        inter = empty_intermediate()
        parser_info = inter["parser"]
        parser_info["name"] = self.name
        try:
            parser_info["parser_version"] = _md.version("pdfplumber")
        except _md.PackageNotFoundError:
            parser_info["parser_version"] = None
        parser_info["model_versions"] = {}  # pdfplumber ships no models
        parser_info["dependency_versions"] = {"pdfplumber": parser_info["parser_version"]}
        parser_info["references_supported"] = False
        parser_info["warnings"].append(
            "pdfplumber fallback: line-level extraction, no document structure; "
            "sections/reading order beyond line order are unavailable"
        )

        items_out = inter["items"]
        pages_out = []
        page_count = 0
        with pdfplumber.open(str(pdf_path)) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages, start=1):
                page_text_parts: list[str] = []
                try:
                    lines = page.extract_text_lines(layout=False, return_chars=False) or []
                except Exception:
                    lines = []
                for ln in lines:
                    text = (ln.get("text") or "").strip()
                    if not text:
                        continue
                    page_text_parts.append(text)
                    bbox = None
                    try:
                        bbox = [
                            round(float(ln["x0"]), 2), round(float(ln["top"]), 2),
                            round(float(ln["x1"]), 2), round(float(ln["bottom"]), 2),
                        ]
                    except (KeyError, TypeError, ValueError):
                        bbox = None
                    items_out.append({
                        "kind": "paragraph",
                        "label": "pdfplumber_line",
                        "physical_page_no": i,
                        "bbox": bbox,
                        "bbox_space": "pdf_points_y_down" if bbox else None,
                        "page_size": [page.width, page.height],
                        "char_span": None,
                        "char_span_space": None,
                        "text": text,
                        "heading_level": None,
                        "table": None,
                    })
                for tbl_obj in _find_tables(page):
                    rows = _table_rows(tbl_obj)
                    bbox = _table_bbox(tbl_obj)
                    items_out.append({
                        "kind": "table",
                        "label": "pdfplumber_find_tables",
                        "physical_page_no": i,
                        "bbox": bbox,
                        "bbox_space": "pdf_points_y_down" if bbox else None,
                        "page_size": [page.width, page.height],
                        "char_span": None,
                        "table": {
                            "n_rows": len(rows) if rows else None,
                            "n_cols": (max((len(r) for r in rows), default=None) if rows else None),
                            "cells": rows,
                            "extraction_method": "pdfplumber_find_tables",
                        },
                    })
                pages_out.append({
                    "physical_page_no": i,
                    "width": page.width,
                    "height": page.height,
                    "text": "\n".join(page_text_parts),
                })

        inter["page_count"] = page_count
        inter["pages"] = pages_out
        inter["language_hint"] = None  # normalize layer derives it
        return inter

    def parse_to_file(self, pdf_path: Path, options: dict, out_json: Path) -> dict:
        inter = self.parse(pdf_path, options)
        Path(out_json).write_text(
            json.dumps(inter, ensure_ascii=False), encoding="utf-8"
        )
        return inter


def _find_tables(page):
    try:
        return page.find_tables() or []
    except Exception:
        return []


def _table_rows(tbl_obj):
    try:
        data = tbl_obj.extract() or []
        return [[("" if c is None else str(c)) for c in row] for row in data]
    except Exception:
        return None


def _table_bbox(tbl_obj):
    try:
        b = tbl_obj.bbox  # (x0, top, x1, bottom)
        return [round(float(b[0]), 2), round(float(b[1]), 2),
                round(float(b[2]), 2), round(float(b[3]), 2)]
    except Exception:
        return None
