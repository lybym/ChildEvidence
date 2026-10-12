"""OpenAlex client: https://docs.openalex.org (polite pool via mailto)."""

from __future__ import annotations

import re

from ..normalize import norm_authors

BASE = "https://api.openalex.org"

TYPE_MAP = {
    "article": "journal_article",
    "review": "review_article",
    "preprint": "preprint",
    "book-chapter": "book_chapter",
    "book": "book",
    "report": "report",
    "dissertation": "dissertation",
    "editorial": "editorial",
    "letter": "letter",
    "erratum": "erratum",
    "paratext": "paratext",
    "supplementary-materials": "supplementary_materials",
    "reference-entry": "reference_entry",
    "standard": "standard",
}

SELECT_FIELDS = ",".join([
    "id", "doi", "title", "display_name", "publication_year", "publication_date",
    "type", "language", "authorships", "primary_location", "locations",
    "best_oa_location", "open_access", "biblio", "ids", "cited_by_count",
    "is_retracted", "abstract_inverted_index",
])


def trim_openalex(raw: dict) -> dict:
    """Keep a compact but complete-enough provenance payload."""
    if not isinstance(raw, dict):
        return {}
    keep = {
        "id": raw.get("id"),
        "doi": raw.get("doi"),
        "title": raw.get("display_name") or raw.get("title"),
        "publication_year": raw.get("publication_year"),
        "publication_date": raw.get("publication_date"),
        "type": raw.get("type"),
        "language": raw.get("language"),
        "cited_by_count": raw.get("cited_by_count"),
        "is_retracted": raw.get("is_retracted"),
        "ids": raw.get("ids"),
        "open_access": raw.get("open_access"),
        "best_oa_location": raw.get("best_oa_location"),
        "primary_location": raw.get("primary_location"),
        "locations": raw.get("locations"),
        "biblio": raw.get("biblio"),
    }
    authorships = []
    for a in raw.get("authorships") or []:
        author = a.get("author") or {}
        authorships.append({
            "name": author.get("display_name"),
            "orcid": author.get("orcid"),
        })
    keep["authorships"] = authorships
    return keep


class OpenAlexClient:
    def __init__(self, http, mailto: str, api_key: str | None = None):
        self.http = http
        self.mailto = mailto
        self.api_key = api_key

    def _params(self, extra: dict | None = None) -> dict:
        p = dict(extra or {})
        p["mailto"] = self.mailto
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    # ------------------------------------------------------------------ read
    def get_work_by_doi(self, doi: str) -> dict:
        res = self.http.get(f"{BASE}/works/doi:{doi}", source="openalex",
                            params=self._params())
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "error": res.get("error") or f"HTTP {res.get('status')}"}
        raw = res.get("json")
        if not raw or raw.get("error"):
            return {"ok": False, "error": (raw or {}).get("error") or "not_found"}
        return {"ok": True, "raw": raw, "rec": self.normalize(raw)}

    def search(self, *, search: str | None = None, filters: dict | None = None,
               sort: str | None = None, per_page: int = 25, cursor: str = "*") -> dict:
        params = self._params({"per-page": per_page, "cursor": cursor,
                               "select": SELECT_FIELDS})
        if search:
            params["search"] = search
        if filters:
            filter_str = ",".join(f"{k}:{v}" for k, v in filters.items())
            params["filter"] = filter_str
        if sort:
            params["sort"] = sort
        res = self.http.get(f"{BASE}/works", source="openalex", params=params)
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "results": [], "error": res.get("error") or f"HTTP {res.get('status')}"}
        js = res.get("json") or {}
        meta = js.get("meta") or {}
        return {"ok": True, "results": js.get("results") or [],
                "meta": meta, "next_cursor": meta.get("next_cursor"), "error": None}

    def get_works_by_openalex_ids(self, ids: list[str]) -> dict:
        """Fetch works by OpenAlex ID (bare W-ids)."""
        id_str = "|".join(i for i in ids if i)
        if not id_str:
            return {"ok": True, "results": [], "error": None}
        return self.search(filters={"openalex_id": id_str}, per_page=max(len(ids), 1))

    # ------------------------------------------------------------ normalize
    @staticmethod
    def rebuild_abstract(inv_idx: dict | None) -> str | None:
        if not inv_idx:
            return None
        pos: dict[int, str] = {}
        for word, idxs in inv_idx.items():
            for i in idxs:
                pos[i] = word
        if not pos:
            return None
        text = " ".join(pos[i] for i in sorted(pos))
        return text[:4000]

    @staticmethod
    def normalize(raw: dict) -> dict:
        ids = raw.get("ids") or {}
        biblio = raw.get("biblio") or {}
        primary = raw.get("primary_location") or {}
        source = primary.get("source") or {}
        pages = None
        if biblio.get("last_page"):
            pages = f"{biblio.get('first_page') or ''}-{biblio.get('last_page')}"
        elif biblio.get("first_page"):
            pages = str(biblio.get("first_page"))
        doi = raw.get("doi") or ""
        doi = re.sub(r"^https://doi\.org/", "", doi).lower() or None

        source_urls = []
        pdf_candidates = []
        locations = []
        if raw.get("best_oa_location"):
            locations.append(raw["best_oa_location"])
        for loc in raw.get("locations") or []:
            locations.append(loc)
        seen = set()
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            landing = loc.get("landing_page_url")
            pdf_url = loc.get("pdf_url")
            if landing and landing not in seen:
                seen.add(landing)
                source_urls.append(landing)
            if pdf_url and pdf_url not in {c.get("url") for c in pdf_candidates}:
                pdf_candidates.append({
                    "url": pdf_url,
                    "landing_page": landing,
                    "source": (loc.get("source") or {}).get("display_name"),
                    "license": loc.get("license"),
                    "version": loc.get("version"),
                    "is_oa": loc.get("is_oa"),
                    "origin": "openalex",
                })
        oa = raw.get("open_access") or {}
        canonical = raw.get("doi") or raw.get("id")
        return {
            "openalex_id": (raw.get("id") or "").rsplit("/", 1)[-1] or None,
            "doi": doi,
            "pmid": (ids.get("pmid") or "").rsplit("/", 1)[-1] or None,
            "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None,
            "s2_id": None,
            "eric_id": None,
            "title": raw.get("display_name") or raw.get("title"),
            "authors": norm_authors(raw.get("authorships") or [], "openalex"),
            "publication_date": raw.get("publication_date"),
            "publication_year": raw.get("publication_year"),
            "journal_or_publisher": source.get("display_name"),
            "volume": biblio.get("volume"),
            "issue": biblio.get("issue"),
            "pages": pages,
            "issn": [source["issn_l"]] if source.get("issn_l") else [],
            "language": raw.get("language"),
            "abstract": OpenAlexClient.rebuild_abstract(raw.get("abstract_inverted_index")),
            "document_type": TYPE_MAP.get(raw.get("type"), raw.get("type")),
            "cited_by_count": raw.get("cited_by_count"),
            "is_retracted": bool(raw.get("is_retracted")),
            "is_oa": oa.get("is_oa"),
            "oa_status": oa.get("oa_status"),
            "canonical_url": canonical,
            "source_urls": source_urls,
            "pdf_candidates": pdf_candidates,
            "license": (raw.get("best_oa_location") or {}).get("license"),
        }
