"""DoclingParser adapter (primary parser, Docling 2.138.0 baseline).

Docling is imported lazily inside parse() so the zero-dependency core never
loads it. Model weights come from a user-configured artifacts cache directory
(offline-first); no network is used at parse time.

The adapter converts Docling's DoclingDocument into the parser-agnostic
intermediate format with original provenance preserved (page_no, bbox,
charspan, label). Nothing is renamed into "better" values: unknown stays null.
"""

from __future__ import annotations

import importlib.metadata as _md
import json
import os
from pathlib import Path

from .base import DependencyMissing, ModelUnavailable, empty_intermediate

# Docling release the POC validated (issue #3 baseline); a mismatch is a
# warning recorded in the output, not a hard failure (researcher decides).
EXPECTED_DOCLING_VERSION = "2.138.0"

_PKGS_FOR_VERSIONS = (
    "docling", "docling-core", "docling-ibm-models", "docling-parse",
    "docling-pdf-backend" , "pypdfium2", "torch", "transformers",
)

_ITEM_KIND_BY_CLASS = {
    "TextItem": "paragraph",
    "SectionHeaderItem": "section_header",
    "ListItem": "list_item",
    "FootnoteItem": "footnote",
    "CaptionItem": "caption",
    "CodeItem": "paragraph",
    "FormulaItem": "paragraph",
    "TableItem": "table",
    "PictureItem": "picture",
    "KeyValueItem": "other",
    "DocItem": "other",
}


def classify_conversion(status_str: str) -> str:
    """Classify a Docling conversion status string: ok | partial | failure.

    Substring matching against bare "SUCCESS" would silently treat
    PARTIAL_SUCCESS (pages/items dropped by the converter) as a fully
    successful parse; the classification is explicit and unit-tested.
    """
    s = (status_str or "").upper()
    if "PARTIAL_SUCCESS" in s:
        return "partial"
    if "SUCCESS" in s:
        return "ok"
    return "failure"


class DoclingParser:
    name = "docling"

    def __init__(self, models_dir: Path | None = None, offline: bool = True):
        self.models_dir = Path(models_dir) if models_dir else None
        self.offline = offline

    # ------------------------------------------------------------------
    def _import_docling(self):
        try:
            import docling  # noqa: F401
            from docling.document_converter import DocumentConverter  # noqa: F401
        except Exception as e:  # ImportError and heavier broken-install errors
            raise DependencyMissing(
                "docling is not installed in this Python environment. "
                "Install the optional parsing extra in an isolated venv: "
                "pip install 'docling==2.138.0'  (see docs/parsing/README.md). "
                f"Underlying import error: {e!r}"
            ) from e

    def _prepare_offline_env(self) -> None:
        if not self.offline:
            return
        # Must be set before docling/transformers import their HF clients.
        # FORCE (not setdefault): an inherited HF_HUB_OFFLINE=0 from the user
        # environment must never punch a hole through offline.mode=true —
        # parse time has no authorization to fetch anything.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    def _check_models_available(self) -> None:
        if not self.offline:
            return
        if self.models_dir is None:
            raise ModelUnavailable(
                "offline mode requires a Docling artifacts directory "
                "(set offline.artifacts_dir in config/parsing.yaml or "
                "CHILDEVIDENCE_PARSING_MODELS_DIR); run 'research parse models' once "
                "with network access to populate it"
            )
        if not self.models_dir.exists() or not any(self.models_dir.iterdir()):
            raise ModelUnavailable(
                f"model artifacts directory is empty or missing: {self.models_dir}; "
                "run 'research parse models' once with network access to populate it"
            )

    def _models_manifest(self) -> dict:
        """Best-effort manifest of cached weights (written by parse models cmd)."""
        if self.models_dir is None:
            return {}
        p = self.models_dir / "models-manifest.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"manifest_error": "unreadable models-manifest.json"}
        return {"manifest": "missing (weights cache not verified by parse models)"}

    def _dependency_versions(self) -> dict:
        out = {}
        for pkg in _PKGS_FOR_VERSIONS:
            try:
                out[pkg] = _md.version(pkg)
            except _md.PackageNotFoundError:
                out[pkg] = None
        return out

    def _build_converter(self):
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.pipeline_options import TableFormerMode
        from docling.document_converter import DocumentConverter, PdfFormatOption

        opts = PdfPipelineOptions()
        opts.do_ocr = False  # OCR is a deliberate later decision; text layer only
        opts.do_table_structure = True
        mode = (self._table_mode or "accurate").lower()
        opts.table_structure_options.mode = {
            "accurate": TableFormerMode.ACCURATE,
            "fast": TableFormerMode.FAST,
        }.get(mode, TableFormerMode.ACCURATE)
        if self.models_dir is not None:
            opts.artifacts_path = str(self.models_dir)
        opts.accelerator_options = AcceleratorOptions(
            num_threads=self._num_threads, device=AcceleratorDevice.CPU
        )
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )

    # ------------------------------------------------------------------
    def probe(self) -> dict:
        """Lightweight identity: import docling for the version only.

        No converter is built and no model weights are loaded, so this works
        in offline mode and even when the weights cache is not populated.
        """
        self._prepare_offline_env()
        self._import_docling()
        import docling

        return {
            "name": self.name,
            "parser_version": getattr(docling, "__version__", None),
            "model_versions": self._models_manifest(),
        }

    # ------------------------------------------------------------------
    def parse(self, pdf_path: Path, options: dict) -> dict:
        self._table_mode = options.get("table_mode", "accurate")
        self._num_threads = int(options.get("num_threads", 1))
        self._prepare_offline_env()
        self._import_docling()
        self._check_models_available()

        import docling
        from docling.document_converter import DocumentConverter  # noqa: F401

        inter = empty_intermediate()
        parser_info = inter["parser"]
        parser_info["name"] = self.name
        parser_info["parser_version"] = getattr(docling, "__version__", None)
        parser_info["dependency_versions"] = self._dependency_versions()
        parser_info["model_versions"] = self._models_manifest()
        if parser_info["parser_version"] != EXPECTED_DOCLING_VERSION:
            parser_info["warnings"].append(
                f"docling version {parser_info['parser_version']!r} != POC baseline "
                f"{EXPECTED_DOCLING_VERSION!r}; outputs may differ from the archived evaluation"
            )

        converter = self._build_converter()
        result = converter.convert(source=Path(pdf_path))
        conv_status = str(getattr(result, "status", "unknown"))
        conv_class = classify_conversion(conv_status)
        if conv_class == "failure":
            raise RuntimeError(f"docling conversion status: {conv_status}")
        if conv_class == "partial":
            # PARTIAL_SUCCESS: the converter dropped pages/items. Extract what
            # exists, but mark the intermediate so the pipeline downgrades the
            # final status to degraded and records docling's own error list —
            # never a silent partial document.
            conv_errors = [str(e)[:300] for e in (getattr(result, "errors", None) or [])[:20]]
            inter["conversion_partial"] = {
                "conversion_status": conv_status,
                "errors": conv_errors,
            }
            inter["warnings"].append(
                f"docling conversion status {conv_status}; output may be incomplete")

        docres = result.document
        self._extract(docres, inter)
        return inter

    # ------------------------------------------------------------------
    def parse_to_file(self, pdf_path: Path, options: dict, out_json: Path) -> dict:
        inter = self.parse(pdf_path, options)
        Path(out_json).write_text(
            json.dumps(inter, ensure_ascii=False), encoding="utf-8"
        )
        return inter

    # ------------------------------------------------------------------
    def _extract(self, dres, inter: dict) -> None:
        """Walk the DoclingDocument into the intermediate format."""
        pages_out = []
        sizes = {}
        try:
            for pno, page in getattr(dres, "pages", {}).items():
                size = getattr(page, "size", None)
                w = getattr(size, "width", None) if size is not None else None
                h = getattr(size, "height", None) if size is not None else None
                sizes[int(pno)] = (w, h)
        except Exception:
            sizes = {}
        page_count = len(sizes)

        texts_by_page: dict[int, list[str]] = {}
        items_out = inter["items"]
        for item, _level in dres.iterate_items():
            cls = type(item).__name__
            label = str(getattr(item, "label", "") or cls)
            prov = getattr(item, "prov", None)
            prov0 = prov[0] if prov else None
            page_no = int(prov0.page_no) if (prov0 is not None and prov0.page_no) else None
            bbox = None
            if prov0 is not None and getattr(prov0, "bbox", None) is not None:
                b = prov0.bbox
                try:
                    bbox = [round(float(b.l), 2), round(float(b.t), 2),
                            round(float(b.r), 2), round(float(b.b), 2)]
                except (TypeError, ValueError):
                    bbox = None
            char_span = None
            if prov0 is not None and getattr(prov0, "charspan", None):
                try:
                    char_span = [int(prov0.charspan[0]), int(prov0.charspan[1])]
                except (TypeError, ValueError, IndexError):
                    char_span = None
            page_size = sizes.get(page_no) if page_no else None
            page_size = [page_size[0], page_size[1]] if page_size else None

            if cls == "TableItem":
                cells, n_rows, n_cols = self._table_grid(item)
                items_out.append({
                    "kind": "table",
                    "label": label,
                    "physical_page_no": page_no,
                    "bbox": bbox,
                    "bbox_space": "pdf_points_y_down" if bbox else None,
                    "page_size": page_size,
                    "char_span": None,
                    "table": {
                        "n_rows": n_rows,
                        "n_cols": n_cols,
                        "cells": cells,
                        "extraction_method": "docling_tableformer",
                    },
                })
                continue

            if cls == "PictureItem":
                inter.setdefault("warnings", []).append(
                    f"picture item skipped (image content not extracted): page {page_no}"
                )
                continue

            text = getattr(item, "text", None)
            if text is None and hasattr(item, "orig"):
                text = getattr(item, "orig")
            if page_no is not None:
                texts_by_page.setdefault(page_no, []).append(text or "")
            kind = _ITEM_KIND_BY_CLASS.get(cls, "other")
            items_out.append({
                "kind": kind,
                "label": label,
                "physical_page_no": page_no,
                "bbox": bbox,
                "bbox_space": "pdf_points_y_down" if bbox else None,
                "page_size": page_size,
                "char_span": char_span,
                "char_span_space": "page_text_chars" if char_span else None,
                "text": text or "",
                "heading_level": getattr(item, "level", None) if cls == "SectionHeaderItem" else None,
                "table": None,
            })

        inter["page_count"] = page_count
        for pno in sorted(sizes.keys()):
            w, h = sizes[pno]
            pages_out.append({
                "physical_page_no": pno,
                "width": w,
                "height": h,
                "text": "\n".join(texts_by_page.get(pno, [])),
            })
        inter["pages"] = pages_out

    def _table_grid(self, item) -> tuple[list | None, int | None, int | None]:
        data = getattr(item, "data", None)
        if data is None:
            return None, None, None
        n_rows = getattr(data, "num_rows", None)
        n_cols = getattr(data, "num_cols", None)
        grid = None
        try:
            raw_grid = data.grid
        except AttributeError:
            raw_grid = None
        if raw_grid:
            grid = []
            for row in raw_grid:
                grid.append([
                    (getattr(cell, "text", None) or "")
                    for cell in row
                ])
        return grid, n_rows, n_cols
