"""Parser adapter contract and shared error types.

An adapter turns a PDF file into an *intermediate document* (plain dict, JSON-
round-trippable) which normalize.py converts into the final normalized result.
The intermediate format is the stable seam: adapters stay replaceable
(Docling main, pdfplumber fallback, future GROBID) without touching the
pipeline or schema.

Adapter responsibilities:
- lazy third-party imports (raise DependencyMissing when absent)
- faithful extraction with original provenance (page_no, bbox, label)
- honest nulls: anything the parser does not provide stays null
- NO interpretation beyond what the parser itself reports
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AdapterError(Exception):
    """A parsing failure that is not about missing dependencies."""


class DependencyMissing(AdapterError):
    """The adapter's third-party dependency is not importable.

    Raised lazily on first use so the zero-dependency core never imports
    docling/pdfplumber. The message tells the user how to install the extra.
    """


class ModelUnavailable(AdapterError):
    """The adapter's model weights are not available in offline mode."""


class ParseTimeout(AdapterError):
    """The adapter (or its subprocess) exceeded the configured timeout."""


INTERMEDIATE_FORMAT_VERSION = 1


def empty_intermediate() -> dict:
    """Skeleton of the intermediate document produced by every adapter."""
    return {
        "format_version": INTERMEDIATE_FORMAT_VERSION,
        "parser": {
            "name": None,
            "parser_version": None,
            "model_versions": {},
            "dependency_versions": {},
            "options": {},
            "warnings": [],
        },
        "page_count": None,
        "pages": [],      # {physical_page_no, width|null, height|null, text: str}
        "items": [],      # reading-order text/table items, see README of parsing/
        "language_hint": None,
        "warnings": [],
    }


class ParserAdapter(Protocol):
    """Structural interface every adapter implements."""

    name: str

    def parse(self, pdf_path: Path, options: dict) -> dict:  # -> intermediate doc
        ...

    def parse_to_file(self, pdf_path: Path, options: dict, out_json: Path) -> dict:
        """Parse and write the intermediate document to out_json (subprocess use)."""
        ...
