"""Normalization helpers: DOIs, titles, authors, years, similarity."""

from __future__ import annotations

import difflib
import re
import unicodedata

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def norm_doi(doi: str | None) -> str | None:
    """Normalize a DOI to lowercase bare form, or None when invalid."""
    if not doi:
        return None
    d = str(doi).strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    d = d.strip().rstrip(".")
    d = re.sub(r"(/)\1+", r"\1", d)  # collapse '//'

    if not DOI_RE.match(d):
        return None
    return d


def norm_pmcid(pmcid: str | None) -> str | None:
    if not pmcid:
        return None
    m = re.match(r"^(PMC\d+)", str(pmcid).upper())
    return m.group(1) if m else None


def norm_pmid(pmid) -> str | None:
    if pmid is None:
        return None
    m = re.search(r"\d+", str(pmid))
    return m.group(0) if m else None


def norm_title(title: str | None) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title).lower()
    t = NONWORD_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def norm_orcid(orcid: str | None) -> str | None:
    if not orcid:
        return None
    m = re.search(r"(\d{4}-\d{4}-\d{4}-[\dX]{4})", str(orcid))
    return m.group(1) if m else None


def _is_cjk_name(s: str) -> bool:
    return bool(CJK_RE.search(s)) and " " not in s.strip()


def split_name(name: str):
    """Split 'Family, Given' or 'Given Family' into (family, given).

    Conservative: CJK single-token names keep family=None.
    """
    name = (name or "").strip()
    if not name:
        return None, None
    if "," in name:
        family, _, given = name.partition(",")
        return family.strip() or None, given.strip() or None
    tokens = name.split()
    if _is_cjk_name(name):
        return None, None  # Chinese names: keep as displayed, no reliable split
    if len(tokens) == 1:
        return tokens[0], None
    return tokens[-1], " ".join(tokens[:-1])


def norm_authors(raw: list, style: str = "name") -> list:
    """Normalize author lists from different sources.

    style='openalex': [{'author': {'display_name':..., 'orcid':...}}, ...]
    style='crossref': [{'given':..., 'family':...} | {'name':...}, ...]
    style='plain':    ['Lastname, Firstname', ...] or [{'name':...}, ...]
    Returns [{'name', 'given', 'family', 'orcid'}, ...] with 'name' required.
    """
    out = []
    for a in raw or []:
        entry = {"name": None, "given": None, "family": None, "orcid": None}
        try:
            if style == "openalex":
                author = (a or {}).get("author") or {}
                entry["name"] = (author.get("display_name") or "").strip() or None
                entry["orcid"] = norm_orcid(author.get("orcid"))
            elif style == "crossref":
                entry["given"] = (a.get("given") or "").strip() or None
                entry["family"] = (a.get("family") or "").strip() or None
                entry["name"] = (a.get("name") or "").strip() or " ".join(
                    x for x in [entry["given"], entry["family"]] if x
                ) or None
                entry["orcid"] = norm_orcid(a.get("orcid"))
            elif style == "plain":
                if isinstance(a, dict):
                    entry["name"] = (a.get("name") or "").strip() or None
                else:
                    entry["name"] = str(a).strip() or None
            if entry["name"] and not (entry["given"] or entry["family"]):
                family, given = split_name(entry["name"])
                entry["family"], entry["given"] = family, given
        except Exception:
            continue
        if entry["name"]:
            out.append(entry)
    return out


def first_surname(authors_json: list | str) -> str | None:
    """Best-effort first author surname from normalized authors JSON."""
    if isinstance(authors_json, str):
        try:
            import json
            authors_json = json.loads(authors_json)
        except Exception:
            authors_json = []
    if not authors_json:
        return None
    a = authors_json[0] or {}
    if a.get("family"):
        return strip_diacritics(a["family"]).lower()
    name = a.get("name") or ""
    if not name:
        return None
    if _is_cjk_name(name):
        return None  # cannot split reliably; do not use for conservative matching
    tokens = name.replace(",", " ").split()
    return strip_diacritics(tokens[-1]).lower() if tokens else None


def guess_year(*date_candidates) -> int | None:
    for c in date_candidates:
        if c is None:
            continue
        m = re.search(r"(19|20)\d{2}", str(c))
        if m:
            return int(m.group(0))
    return None


def safe_internal_id(doi: str | None, title: str | None) -> str:
    """Deterministic internal id from DOI (preferred) or normalized title."""
    import hashlib
    base = doi or norm_title(title) or "unknown"
    return "lt-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
