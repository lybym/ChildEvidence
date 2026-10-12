"""Crossref client: https://api.crossref.org (polite pool via mailto UA)."""

from __future__ import annotations

import html
import re

from ..normalize import norm_authors

BASE = "https://api.crossref.org"

TRIM_KEYS = [
    "DOI", "title", "subtitle", "author", "container-title", "short-container-title",
    "volume", "issue", "page", "ISSN", "publisher", "published", "published-print",
    "published-online", "issued", "type", "language", "license", "link",
    "update-to", "updated-by", "is-referenced-by-count", "abstract", "subject",
    "editor", "event",
]

XREF_TYPE_MAP = {
    "journal-article": "journal_article",
    "book-chapter": "book_chapter",
    "book": "book",
    "monograph": "book",
    "report": "report",
    "report-component": "report",
    "proceedings-article": "conference_paper",
    "posted-content": "posted_content",
    "preprint": "preprint",
    "dissertation": "dissertation",
    "standard": "standard",
    "edited-book": "book",
    "reference-entry": "reference_entry",
}


def trim_crossref(message: dict) -> dict:
    if not isinstance(message, dict):
        return {}
    return {k: message.get(k) for k in TRIM_KEYS if message.get(k) is not None}


def strip_jats(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"<[^>]+>", " ", text)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


class CrossrefClient:
    def __init__(self, http, mailto: str):
        self.http = http
        self.mailto = mailto

    def get_by_doi(self, doi: str) -> dict:
        res = self.http.get(f"{BASE}/works/{doi}", source="crossref")
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "error": res.get("error") or f"HTTP {res.get('status')}"}
        js = res.get("json") or {}
        message = js.get("message")
        if not message:
            return {"ok": False, "error": "empty_message"}
        return {"ok": True, "message": message}

    def search(self, *, query: str | None = None, query_bibliographic: str | None = None,
               rows: int = 20, filters: dict | None = None) -> dict:
        params = {"rows": rows, "mailto": self.mailto}
        if query:
            params["query"] = query
        if query_bibliographic:
            params["query.bibliographic"] = query_bibliographic
        if filters:
            params["filter"] = ",".join(f"{k}:{v}" for k, v in filters.items())
        res = self.http.get(f"{BASE}/works", source="crossref", params=params)
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "items": [], "error": res.get("error") or f"HTTP {res.get('status')}"}
        js = res.get("json") or {}
        return {"ok": True, "items": (js.get("message") or {}).get("items") or [], "error": None}

    @staticmethod
    def normalize(message: dict) -> dict:
        titles = message.get("title") or []
        containers = message.get("container-title") or []
        issued = (message.get("issued") or {}).get("date-parts") or []
        pub = (message.get("published") or {}).get("date-parts") or issued
        pub_online = (message.get("published-online") or {}).get("date-parts") or []
        pub_print = (message.get("published-print") or {}).get("date-parts") or []
        date_parts = pub_online or pub_print or pub
        year = None
        pub_date = None
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            year = parts[0]
            if len(parts) >= 2:
                pub_date = f"{parts[0]:04d}-{parts[1]:02d}"
            else:
                pub_date = str(parts[0])
        pages = message.get("page")
        authors = norm_authors(message.get("author") or [], "crossref")
        issn = message.get("ISSN") or []
        links = []
        for link in message.get("link") or []:
            url = link.get("URL")
            if url:
                links.append({
                    "url": url,
                    "content_type": link.get("content-type"),
                    "content_version": link.get("content-version"),
                    "intended_application": link.get("intended-application"),
                    "origin": "crossref",
                })
        licenses = []
        for lic in message.get("license") or []:
            if lic.get("URL"):
                licenses.append(lic["URL"])
        abstract = strip_jats(message.get("abstract"))
        return {
            "doi": (message.get("DOI") or "").lower() or None,
            "title": titles[0] if titles else None,
            "authors": authors,
            "publication_date": pub_date,
            "publication_year": year,
            "journal_or_publisher": (containers[0] if containers else None) or message.get("publisher"),
            "volume": message.get("volume"),
            "issue": message.get("issue"),
            "pages": pages,
            "issn": list(issn),
            "language": message.get("language"),
            "abstract": abstract,
            "document_type": XREF_TYPE_MAP.get(message.get("type"), message.get("type")),
            "canonical_url": f"https://doi.org/{message.get('DOI')}" if message.get("DOI") else None,
            "source_urls": [f"https://doi.org/{message.get('DOI')}"] if message.get("DOI") else [],
            "pdf_candidates": links,
            "license": licenses[0] if licenses else None,
            "publisher": message.get("publisher"),
            "is_referenced_by_count": message.get("is-referenced-by-count"),
        }

    @staticmethod
    def retraction_status(message: dict):
        """Return ('retracted'|'expression_of_concern'|None, labels)."""
        labels = []
        status = None
        for upd in (message.get("update-to") or []):
            t = (upd.get("type") or "").lower()
            labels.append(upd.get("label") or t)
            if "retraction" in t:
                status = "retracted"
            elif "expression" in t and status != "retracted":
                status = "expression_of_concern"
        return status, labels
