"""Metadata verification against Crossref (and OpenAlex backfill)."""

from __future__ import annotations

import json
import re

from . import db
from .db import now_iso
from .normalize import norm_doi, title_similarity
from .sources import trim_crossref


def verify_work(conn, work, crossref, openalex=None) -> str:
    """Verify one work row. Returns final metadata_status."""
    internal_id = work["internal_id"]
    doi = norm_doi(work["doi"])
    updates: dict = {"last_checked_at": now_iso()}
    errors = json.loads(work["retrieval_errors"] or "[]")
    raw = {}
    try:
        raw = json.loads(work["raw_sources"] or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    status = "unverified"

    if not doi:
        status = "no_doi_source_only"
        updates["metadata_status"] = status
        db.update_work(conn, internal_id, **updates)
        return status

    res = crossref.get_by_doi(doi)
    if not res.get("ok"):
        err = res.get("error") or "unknown"
        errors.append({"source": "crossref", "at": now_iso(), "error": err})
        updates["retrieval_errors"] = errors
        if "404" in err or "not found" in err.lower():
            # DOI not registered with Crossref: common for CNKI/ISTIC and some
            # institutional prefixes; OpenAlex metadata remains the source.
            status = "doi_not_registered"
            updates["metadata_status"] = status
        else:
            status = "api_error"
            updates["metadata_status"] = status
        db.update_work(conn, internal_id, **updates)
        _openalex_backfill(conn, work, openalex, raw, errors, updates)
        return status

    message = res["message"]
    raw["crossref"] = trim_crossref(message)

    from .sources.crossref import strip_jats
    xref_title = strip_jats((message.get("title") or [""])[0]) or ""
    sim = title_similarity(work["title"], xref_title)
    if sim < 0.75:
        status = "conflict"
        updates["metadata_status"] = status
        updates["conflicting_metadata"] = (
            f"Crossref title similarity {sim:.2f}: '{xref_title}'"
        )
        updates["human_review_required"] = 1
        retraction, _labels = _crossref_retraction(message)
        if retraction:
            _apply_retraction(updates, retraction)
        db.update_work(conn, internal_id, **updates)
        _openalex_backfill(conn, work, openalex, raw, errors, updates)
        return status

    status = "crossref_verified"
    updates["metadata_status"] = status
    updates["conflicting_metadata"] = None

    # fill missing bibliographic fields from Crossref
    xref = _crossref_to_fields(message)
    fillable = [
        "journal_or_publisher", "volume", "issue", "pages", "language",
        "publication_date", "publication_year", "canonical_url",
    ]
    for field in fillable:
        if work[field] is None and xref.get(field) is not None:
            updates[field] = xref[field]
    if not json.loads(work["issn"] or "[]") and xref.get("issn"):
        updates["issn"] = xref["issn"]
    if not json.loads(work["authors"] or "[]") and xref.get("authors"):
        updates["authors"] = xref["authors"]
    if not work["abstract"] and xref.get("abstract"):
        updates["abstract"] = xref["abstract"]
    if work["document_type"] is None and xref.get("document_type"):
        updates["document_type"] = xref["document_type"]

    retraction, labels = _crossref_retraction(message)
    if retraction:
        _apply_retraction(updates, retraction, labels)

    db.update_work(conn, internal_id, **updates)
    _openalex_backfill(conn, work, openalex, raw, errors, updates)
    return status


def _crossref_retraction(message):
    labels = []
    status = None
    for upd in message.get("update-to") or []:
        t = (upd.get("type") or "").lower()
        label = upd.get("label") or t
        if label:
            labels.append(label)
        if "retraction" in t:
            status = "retracted"
        elif "expression" in t and status != "retracted":
            status = "expression_of_concern"
    return status, labels


def _apply_retraction(updates, retraction, labels=None):
    updates["retraction_status"] = retraction
    updates["human_review_required"] = 1
    if retraction == "expression_of_concern":
        updates["expression_of_concern"] = 1
    if labels:
        note = "; ".join(str(x) for x in labels)
        updates["reviewer_notes"] = ((updates.get("reviewer_notes") or "") + f" Crossref update: {note}").strip()


def _crossref_to_fields(message: dict) -> dict:
    from .sources.crossref import CrossrefClient
    return CrossrefClient.normalize(message)


def _openalex_backfill(conn, work, openalex, raw, errors, updates):
    """If we never had an OpenAlex record for this DOI, fetch and store one."""
    if openalex is None:
        return
    if raw.get("openalex") or (work["openalex_id"] and raw.get("openalex")):
        return
    doi = norm_doi(work["doi"])
    if not doi:
        return
    res = openalex.get_work_by_doi(doi)
    if not res.get("ok"):
        errors.append({"source": "openalex", "at": now_iso(), "error": res.get("error") or "unknown"})
        updates["retrieval_errors"] = errors
        db.update_work(conn, work["internal_id"], **updates)
        return
    oa_raw = res["raw"]
    rec = res["rec"]
    raw["openalex"] = _trim_openalex_for_storage(oa_raw)
    updates["raw_sources"] = raw
    if rec.get("openalex_id") and not work["openalex_id"]:
        updates["openalex_id"] = rec["openalex_id"]
    if rec.get("pmid") and not work["pmid"]:
        updates["pmid"] = rec["pmid"]
    if rec.get("pmcid") and not work["pmcid"]:
        updates["pmcid"] = rec["pmcid"]
    if rec.get("cited_by_count") and not work["cited_by_count"]:
        updates["cited_by_count"] = rec["cited_by_count"]
    if rec.get("is_retracted"):
        updates["retraction_status"] = "retracted"
        updates["human_review_required"] = 1
    # append pdf candidates for acquisition
    cands = raw.get("pdf_candidates") or []
    for c in rec.get("pdf_candidates") or []:
        if c.get("url") and c["url"] not in {x.get("url") for x in cands}:
            cands.append(c)
    if cands:
        raw["pdf_candidates"] = cands
        updates["raw_sources"] = raw
    db.update_work(conn, work["internal_id"], **updates)


def _trim_openalex_for_storage(raw: dict) -> dict:
    from .sources.openalex import trim_openalex
    return trim_openalex(raw)


def verify_all(conn, crossref, openalex=None, *, limit=None, include_status=("ingested",),
               force=False) -> dict:
    """Verify works in a loop. Returns counts."""
    q = "SELECT * FROM works WHERE record_status IN (%s)" % ",".join("?" for _ in include_status)
    params = list(include_status)
    if not force:
        q += " AND metadata_status IN ('unverified','api_error')"
    q += " ORDER BY internal_id"
    if limit:
        q += f" LIMIT {int(limit)}"
    stats = {"total": 0, "crossref_verified": 0, "conflict": 0, "api_error": 0,
             "no_doi_source_only": 0}
    for work in conn.execute(q, params).fetchall():
        stats["total"] += 1
        status = verify_work(conn, work, crossref, openalex)
        if status in stats:
            stats[status] += 1
        else:
            stats[status] = 1
    return stats
