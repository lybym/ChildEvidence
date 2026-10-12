"""Europe PMC client: https://europepmc.org/RestfulWebService"""

from __future__ import annotations

import re

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

TAG_RE = re.compile(r"<[^>]+>")


def clean_abstract(text: str | None) -> str | None:
    if not text:
        return None
    t = TAG_RE.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


class EuropePMCClient:
    def __init__(self, http):
        self.http = http

    def search(self, query: str, rows: int = 25, result_type: str = "core") -> dict:
        params = {
            "query": query,
            "format": "json",
            "pageSize": rows,
            "resultType": result_type,
        }
        res = self.http.get(f"{BASE}/search", source="europepmc", params=params)
        if res.get("error") or res.get("status") != 200:
            return {"ok": False, "results": [], "error": res.get("error") or f"HTTP {res.get('status')}"}
        js = res.get("json") or {}
        results = ((js.get("resultList") or {}).get("result")) or []
        return {"ok": True, "results": results, "hit_count": js.get("hitCount"), "error": None}

    @staticmethod
    def fulltext_pdf_url(pmcid: str) -> str:
        return f"{BASE}/PMC/{pmcid}/fullTextPDF"

    @staticmethod
    def normalize(hit: dict) -> dict:
        """Normalize an Europe PMC search hit into a unified record."""
        src = hit.get("source")  # MED, PMC, PPR, Pre ...
        pmid = hit.get("pmid")
        pmcid = hit.get("pmcid")
        doi = hit.get("doi")
        author_string = hit.get("authorString") or ""
        authors = []
        for part in author_string.split(";"):
            part = part.strip().rstrip(".")
            if part:
                authors.append({"name": part, "given": None, "family": None, "orcid": None})
        journal = ((hit.get("journalInfo") or {}).get("journal") or {}).get("title")
        pub_types = hit.get("pubTypeList") or []
        doc_type = "journal_article"
        for pt in pub_types:
            ptl = pt.lower()
            if "review" in ptl and "systematic" in ptl:
                doc_type = "review_article"
                break
            if "review" in ptl:
                doc_type = "review_article"
        is_preprint = src == "PPR" or (hit.get("bookOrBookChapter") == "Preprint")
        pdf_candidates = []
        landing = None
        full_urls = (hit.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        for u in full_urls:
            style = u.get("documentStyle")
            code = u.get("availabilityCode")
            url = u.get("url")
            if style == "html" and code in ("OA", "F") and not landing and url:
                landing = url
            if style == "pdf" and code in ("OA", "F") and url:
                pdf_candidates.append({
                    "url": url,
                    "landing_page": landing,
                    "source": f"Europe PMC ({u.get('site') or 'official'})",
                    "license": hit.get("license"),
                    "version": "published_version",
                    "origin": "europepmc",
                })
        return {
            "doi": doi.lower() if doi else None,
            "pmid": pmid,
            "pmcid": pmcid,
            "title": hit.get("title"),
            "authors": authors,
            "publication_year": int(hit["pubYear"]) if hit.get("pubYear") and str(hit["pubYear"]).isdigit() else None,
            "publication_date": hit.get("firstPublicationDate"),
            "journal_or_publisher": journal,
            "volume": (hit.get("journalInfo") or {}).get("volume"),
            "issue": (hit.get("journalInfo") or {}).get("issue"),
            "pages": hit.get("pageInfo"),
            "language": hit.get("language"),
            "abstract": clean_abstract(hit.get("abstractText")),
            "document_type": "preprint" if is_preprint else doc_type,
            "is_oa": hit.get("isOpenAccess") == "Y",
            "canonical_url": f"https://europepmc.org/article/{src}/{pmid or pmcid}" if (pmid or pmcid) else None,
            "source_urls": [landing] if landing else [],
            "pdf_candidates": pdf_candidates,
        }
