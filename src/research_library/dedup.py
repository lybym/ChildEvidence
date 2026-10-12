"""Deduplication: DOI-first, then conservative title+year+author matching.

Uncertain fuzzy matches are NEVER auto-merged; they are flagged for human
review instead (human_review_required=1 with an ingestion note).
"""

from __future__ import annotations

from . import db
from .normalize import first_surname, norm_doi, norm_title, title_similarity


def find_existing(conn, *, doi, title, year, authors_json):
    """Return (work_row, method) where method in {'doi', 'conservative', None}."""
    doi_n = norm_doi(doi)
    if doi_n:
        row = db.find_by_doi(conn, doi_n)
        if row:
            return row, "doi"
    tn = norm_title(title)
    if tn:
        rows = conn.execute(
            "SELECT * FROM works WHERE title_norm=?", (tn,)
        ).fetchall()
        surname = first_surname(authors_json)
        for r in rows:
            same_title = r["title_norm"] == tn
            same_year = year is None or r["publication_year"] is None or int(r["publication_year"] or 0) == int(year)
            same_surname = bool(surname) and (r["first_author_surname"] == surname)
            both_no_surname = not surname and not r["first_author_surname"]
            if same_title and same_year and (same_surname or both_no_surname):
                return r, "conservative"
    return None, None


def find_possible_duplicates(conn, *, title, year, authors_json, exclude_id=None,
                             threshold=0.93) -> list:
    """Fuzzy near-duplicates for human review. Conservative pairing rules:
    similarity >= threshold AND (sim >= 0.98 OR same first-author surname)
    AND publication years within +/-1 (or unknown)."""
    tn = norm_title(title)
    if not tn:
        return []
    surname = first_surname(authors_json)
    out = []
    for r in conn.execute(
        "SELECT internal_id, title, title_norm, publication_year, first_author_surname"
        " FROM works WHERE record_status != 'rejected'"
    ):
        if exclude_id and r["internal_id"] == exclude_id:
            continue
        other = r["title_norm"] or ""
        if not other:
            continue
        sim = title_similarity(tn, other)
        if sim < threshold:
            continue
        if year is not None and r["publication_year"] is not None:
            if abs(int(year) - int(r["publication_year"])) > 1:
                continue
        same_surname = bool(surname) and r["first_author_surname"] == surname
        if sim >= 0.98 or same_surname:
            out.append({
                "internal_id": r["internal_id"],
                "title": r["title"],
                "similarity": round(sim, 3),
            })
    return out
