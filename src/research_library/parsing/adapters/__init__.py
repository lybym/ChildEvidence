"""Adapter registry. Only stdlib at import time; adapters import lazily."""

from __future__ import annotations

from pathlib import Path

from .base import AdapterError, DependencyMissing, ModelUnavailable, ParseTimeout  # noqa: F401

_REGISTRY = {
    "docling": "research_library.parsing.adapters.docling_adapter.DoclingParser",
    "pdfplumber": "research_library.parsing.adapters.pdfplumber_adapter.PdfPlumberParser",
}


def known_parsers() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter(name: str, *, models_dir: Path | None = None, offline: bool = True):
    """Instantiate an adapter by name (lazy import inside the adapter class)."""
    if name not in _REGISTRY:
        raise AdapterError(
            f"unknown parser {name!r}; known parsers: {', '.join(known_parsers())}"
        )
    module_path, cls_name = _REGISTRY[name].rsplit(".", 1)
    import importlib

    cls = getattr(importlib.import_module(module_path), cls_name)
    if name == "docling":
        return cls(models_dir=models_dir, offline=offline)
    return cls()
