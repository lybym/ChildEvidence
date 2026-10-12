"""Official metadata source clients (discovery + verification)."""

from __future__ import annotations

from .crossref import CrossrefClient, trim_crossref
from .eric import EricClient
from .europepmc import EuropePMCClient
from .openalex import OpenAlexClient, trim_openalex
from .semanticscholar import SemanticScholarClient

__all__ = [
    "OpenAlexClient",
    "CrossrefClient",
    "EricClient",
    "EuropePMCClient",
    "SemanticScholarClient",
    "trim_openalex",
    "trim_crossref",
]
