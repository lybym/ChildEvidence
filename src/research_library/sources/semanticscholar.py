"""Semantic Scholar client (used sparingly for cross-verification).

Unauthenticated tier is heavily rate-limited (~1 request/second); the HTTP
client enforces a per-host minimum interval.
"""

from __future__ import annotations

BASE = "https://api.semanticscholar.org/graph/v1"

FIELDS = "title,externalIds,year,venue,publicationTypes,journal,authors,abstract,openAccessPdf,isOpenAccess"


class SemanticScholarClient:
    def __init__(self, http):
        self.http = http

    def get_paper_by_doi(self, doi: str) -> dict:
        res = self.http.get(f"{BASE}/paper/DOI:{doi}", source="semanticscholar",
                            params={"fields": FIELDS})
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "error": res.get("error") or f"HTTP {res.get('status')}"}
        raw = res.get("json")
        if not raw:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "raw": raw, "rec": self.normalize(raw)}

    @staticmethod
    def normalize(raw: dict) -> dict:
        ext = raw.get("externalIds") or {}
        journal = raw.get("journal") or {}
        oa = raw.get("openAccessPdf") or {}
        pdf_candidates = []
        if oa.get("url"):
            pdf_candidates.append({
                "url": oa["url"],
                "landing_page": None,
                "source": "Semantic Scholar (openAccessPdf)",
                "license": oa.get("status"),
                "version": None,
                "origin": "semanticscholar",
            })
        authors = []
        for a in raw.get("authors") or []:
            name = a.get("name")
            if name:
                authors.append({"name": name, "given": None, "family": None, "orcid": None})
        return {
            "doi": (ext.get("DOI") or "").lower() or None,
            "pmid": ext.get("PubMed"),
            "pmcid": ext.get("PubMedCentral"),
            "s2_id": raw.get("paperId"),
            "title": raw.get("title"),
            "authors": authors,
            "publication_year": raw.get("year"),
            "journal_or_publisher": journal.get("name") or raw.get("venue") or None,
            "abstract": raw.get("abstract"),
            "document_type": "review_article" if "Review" in (raw.get("publicationTypes") or []) else "journal_article",
            "is_oa": raw.get("isOpenAccess"),
            "pdf_candidates": pdf_candidates,
        }
