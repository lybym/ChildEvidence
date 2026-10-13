"""CE-03 controlled PDF parsing infrastructure (data-processing layer only).

This package implements the Docling-first PDF parsing pipeline described in
GitHub issue #3 (CE-03): pluggable parser adapters, a normalized, provenance-
carrying output schema, a versioned and idempotent artifact store, printed vs
physical page separation, and reproducible task reports.

Hard boundaries (see AGENTS.md and issue #3):

- Data-processing layer only: no Claim/Evidence semantics, no knowledge-pack
  publishing, no agent behavior changes.
- Local-first: parsing runs offline; only the explicit
  ``research parse models`` command may download Docling model weights into a
  user-configured cache directory (authorized in issue #3 scope). PDF content
  never leaves the machine.
- Zero-dependency core preserved: importing this package or using the CLI does
  NOT require docling/pdfplumber; third-party imports happen lazily inside the
  concrete adapters and fail with a clear DependencyMissing error.
- library.sqlite is never written by this package; parse artifacts live in a
  separate, gitignored output directory.
"""

from __future__ import annotations

SCHEMA_NAME = "childevidence.parse"
SCHEMA_VERSION = 1

__all__ = ["SCHEMA_NAME", "SCHEMA_VERSION"]
