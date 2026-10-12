"""ERIC client: https://api.ies.ed.gov/eric/ (U.S. Dept. of Education)."""

from __future__ import annotations

from ..normalize import norm_authors

BASE = "https://api.ies.ed.gov/eric/"

FIELDS = ",".join([
    "id", "title", "author", "corporateauthor", "source", "publicationdateyear",
    "description", "subject", "issn", "isbn", "peerreviewed", "fulltextavailable",
    "language", "ed", "ej", "audience", "educationlevel",
])


class EricClient:
    def __init__(self, http):
        self.http = http

    def search(self, query: str, rows: int = 20, start: int = 0) -> dict:
        params = {
            "search": query,
            "format": "json",
            "fields": FIELDS,
            "rows": rows,
            "start": start,
        }
        res = self.http.get(BASE, source="eric", params=params, accept="application/json")
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "docs": [], "error": res.get("error") or f"HTTP {res.get('status')}"}
        js = res.get("json") or {}
        response = js.get("response") or {}
        docs = response.get("docs") or []
        return {"ok": True, "docs": docs, "num_found": response.get("numFound"), "error": None}

    @staticmethod
    def normalize(doc: dict) -> dict:
        eric_id = doc.get("id")
        year = doc.get("publicationdateyear")
        peer = doc.get("peerreviewed") == "T"
        fulltext = doc.get("fulltextavailable") == "T"
        authors = norm_authors(doc.get("author") or [], "plain")
        issn = doc.get("issn") or []
        if isinstance(issn, str):
            issn = [s.strip() for s in issn.split(",") if s.strip()]
        pdf_candidates = []
        source_urls = []
        if eric_id:
            landing = f"https://eric.ed.gov/?id={eric_id}"
            source_urls.append(landing)
            if fulltext:
                pdf_candidates.append({
                    "url": f"https://files.eric.ed.gov/fulltext/{eric_id}.pdf",
                    "landing_page": landing,
                    "source": "ERIC (U.S. Department of Education)",
                    "license": None,
                    "version": None,
                    "origin": "eric",
                })
        return {
            "doi": None,
            "eric_id": eric_id,
            "title": doc.get("title"),
            "authors": authors,
            "publication_year": int(year) if year and str(year).isdigit() else None,
            "publication_date": str(year) if year else None,
            "journal_or_publisher": doc.get("source"),
            "issn": issn,
            "language": (doc.get("language") or [None])[0] if isinstance(doc.get("language"), list) else doc.get("language"),
            "abstract": doc.get("description"),
            "document_type": "journal_article" if peer else "eric_document",
            "peer_review_status": "peer_reviewed_journal_source" if peer else "grey_literature",
            "canonical_url": f"https://eric.ed.gov/?id={eric_id}" if eric_id else None,
            "source_urls": source_urls,
            "pdf_candidates": pdf_candidates,
            "subject": doc.get("subject"),
            "education_level": doc.get("educationlevel"),
        }
