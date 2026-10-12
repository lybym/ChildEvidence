"""Ingestion: unified records -> SQLite with dedup, classification, provenance."""

from __future__ import annotations

import hashlib
import json
import re

from . import db
from .dedup import find_existing, find_possible_duplicates
from .db import now_iso
from .normalize import first_surname, guess_year, norm_doi, norm_title, safe_internal_id

RCT_RE = re.compile(r"randomi[sz]ed (controlled |cluster )?trial|cluster[- ]randomi[sz]ed", re.I)
META_RE = re.compile(r"meta[- ]?analys", re.I)
SYSTREV_RE = re.compile(r"systematic review|scoping review|living guideline", re.I)


def guess_evidence_category(title, document_type=None, fallback="other_empirical") -> str | None:
    t = title or ""
    if META_RE.search(t):
        return "meta_analysis"
    if SYSTREV_RE.search(t):
        return "systematic_review"
    if RCT_RE.search(t):
        return "rct"
    if "longitudinal" in t.lower():
        return "longitudinal"
    if document_type == "review_article":
        return "narrative_review"
    if document_type in ("report", "practice_guide", "guideline"):
        return "practice_guideline"
    if document_type in ("book", "book_chapter"):
        return "theoretical_conceptual"
    if document_type == "preprint":
        return "preprint_empirical"
    if document_type in ("journal_article", "conference_paper", "eric_document"):
        return fallback
    return None


def _sets(rec, keys):
    return {k: rec.get(k) for k in keys if rec.get(k) is not None}


MERGEABLE_SCALARS = [
    "pmid", "pmcid", "openalex_id", "eric_id", "s2_id", "publication_date",
    "publication_year", "journal_or_publisher", "volume", "issue", "pages",
    "language", "abstract", "document_type", "canonical_url", "cited_by_count",
    "peer_review_status",
]


def ingest(conn, rec: dict, *, source_name: str, raw_payload=None,
           domains=None, tags=None, frameworks=None, record_status="candidate",
           evidence_category=None, peer_review_status=None, ingestion_notes=None,
           query_key=None, document_type=None) -> dict:
    """Insert or merge one unified record. Returns {'internal_id', 'action'}.

    action: created | merged | flagged (created but flagged as possible duplicate)
    """
    title = (rec.get("title") or "").strip()
    if not title:
        raise ValueError("record without title cannot be ingested")
    doi = norm_doi(rec.get("doi"))
    authors = rec.get("authors") or []
    year = rec.get("publication_year") or guess_year(rec.get("publication_date"))
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    now = now_iso()

    existing, method = find_existing(conn, doi=doi, title=title, year=year,
                                     authors_json=authors)
    doc_type = document_type or rec.get("document_type")

    if existing is not None:
        internal_id = existing["internal_id"]
        updates: dict = {"last_checked_at": now}
        for field in MERGEABLE_SCALARS:
            if existing[field] is None and rec.get(field) is not None:
                updates[field] = rec[field]
        if not existing["abstract"] and rec.get("abstract"):
            updates["abstract"] = rec["abstract"]
        if year and existing["publication_year"] and int(existing["publication_year"]) != int(year):
            note = f"publication_year differs across sources: {existing['publication_year']} vs {year}"
            updates["conflicting_metadata"] = ((existing["conflicting_metadata"] or "") + f"; {note}").strip("; ")
            updates["human_review_required"] = 1
        if rec.get("is_retracted"):
            updates["retraction_status"] = "retracted"
            updates["human_review_required"] = 1
        if doi and not existing["doi"]:
            updates["doi"] = doi
        # arrays
        _merge_arrays(existing, rec, updates, domains or [], tags or [], frameworks or [])
        raw = _load_raw(existing)
        if raw_payload is not None:
            raw[source_name] = _trim_payload(raw_payload)
        updates["raw_sources"] = raw
        notes = (existing["ingestion_notes"] or "")
        extra = f"re-ingested from {source_name} ({method})"
        updates["ingestion_notes"] = f"{notes}; {extra}".strip("; ")
        if ingestion_notes:
            updates["ingestion_notes"] += f"; {ingestion_notes}"
        db.update_work(conn, internal_id, **updates)
        return {"internal_id": internal_id, "action": "merged"}

    # new record
    internal_id = safe_internal_id(doi, title)
    if db.get_work(conn, internal_id) is not None:
        n = 2
        while db.get_work(conn, f"{internal_id}-{n}") is not None:
            n += 1
        internal_id = f"{internal_id}-{n}"

    possibles = find_possible_duplicates(conn, title=title, year=year, authors_json=authors)
    flagged = bool(possibles)
    notes_parts = []
    if flagged:
        notes_parts.append("possible duplicate of: " + json.dumps(possibles, ensure_ascii=False))
    if ingestion_notes:
        notes_parts.append(ingestion_notes)

    ev_cat = evidence_category or guess_evidence_category(title, doc_type)
    prs = peer_review_status or rec.get("peer_review_status")
    if prs is None:
        if doc_type == "preprint":
            prs = "preprint_not_peer_reviewed"
        elif doc_type in ("report", "practice_guide", "guideline", "book", "book_chapter"):
            prs = "not_peer_reviewed_grey_literature"
        elif rec.get("journal_or_publisher"):
            prs = "peer_reviewed_journal_source"
        else:
            prs = "unknown"

    row = {
        "internal_id": internal_id,
        "doi": doi,
        "pmid": rec.get("pmid"),
        "pmcid": rec.get("pmcid"),
        "openalex_id": rec.get("openalex_id"),
        "eric_id": rec.get("eric_id"),
        "s2_id": rec.get("s2_id"),
        "title": title,
        "authors": authors,
        "publication_date": rec.get("publication_date"),
        "publication_year": year,
        "journal_or_publisher": rec.get("journal_or_publisher"),
        "volume": rec.get("volume"),
        "issue": rec.get("issue"),
        "pages": rec.get("pages"),
        "issn": rec.get("issn") or [],
        "language": rec.get("language"),
        "abstract": rec.get("abstract"),
        "document_type": doc_type,
        "research_domains": list(domains or []),
        "topic_tags": list(tags or []),
        "theoretical_frameworks": list(frameworks or []),
        "peer_review_status": prs,
        "evidence_category": ev_cat,
        "access_status": "pending",
        "source_urls": rec.get("source_urls") or [],
        "canonical_url": rec.get("canonical_url"),
        "discovered_at": now,
        "last_checked_at": now,
        "retraction_status": "retracted" if rec.get("is_retracted") else "unknown",
        "human_review_required": 1 if (flagged or rec.get("is_retracted")) else 0,
        "title_norm": norm_title(title),
        "first_author_surname": first_surname(authors),
        "record_status": record_status,
        "cited_by_count": rec.get("cited_by_count"),
        "discovery_source": source_name,
        "query_key": query_key,
        "raw_sources": ({source_name: _trim_payload(raw_payload)} if raw_payload is not None else {}),
        "ingestion_notes": "; ".join(p for p in notes_parts if p) or None,
        "metadata_status": "unverified",
    }
    if rec.get("is_oa") is not None:
        row["access_status"] = "open_candidate" if rec["is_oa"] else "pending"

    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO works ({', '.join(cols)}) VALUES ({placeholders})",
        [json.dumps(row[c], ensure_ascii=False) if c in db.JSON_FIELDS | db.JSON_OBJECT_FIELDS
         else row[c] for c in cols],
    )
    conn.commit()
    # store pdf candidates in raw_sources for the acquisition stage
    if rec.get("pdf_candidates"):
        raw = _load_raw(db.get_work(conn, internal_id))
        raw.setdefault("pdf_candidates", [])
        for c in rec["pdf_candidates"]:
            if c not in raw["pdf_candidates"]:
                raw["pdf_candidates"].append(c)
        db.update_work(conn, internal_id, raw_sources=raw)
    return {"internal_id": internal_id, "action": "flagged" if flagged else "created"}


def _merge_arrays(existing, rec, updates, domains, tags, frameworks):
    cur_issn = json.loads(existing["issn"]) if existing["issn"] else []
    new_issn = [v for v in (rec.get("issn") or []) if v and v not in cur_issn]
    if new_issn:
        updates["issn"] = cur_issn + new_issn
    cur_urls = json.loads(existing["source_urls"]) if existing["source_urls"] else []
    new_urls = [u for u in (rec.get("source_urls") or []) if u and u not in cur_urls]
    if new_urls:
        updates["source_urls"] = cur_urls + new_urls
    cur_domains = json.loads(existing["research_domains"]) if existing["research_domains"] else []
    cur_tags = json.loads(existing["topic_tags"]) if existing["topic_tags"] else []
    cur_fw = json.loads(existing["theoretical_frameworks"]) if existing["theoretical_frameworks"] else []
    d2 = cur_domains + [d for d in domains if d not in cur_domains]
    t2 = cur_tags + [t for t in tags if t not in cur_tags]
    f2 = cur_fw + [f for f in frameworks if f not in cur_fw]
    if d2 != cur_domains:
        updates["research_domains"] = d2
    if t2 != cur_tags:
        updates["topic_tags"] = t2
    if f2 != cur_fw:
        updates["theoretical_frameworks"] = f2


def _load_raw(row) -> dict:
    try:
        raw = json.loads(row["raw_sources"]) if row["raw_sources"] else {}
    except (TypeError, json.JSONDecodeError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _trim_payload(payload, limit=60000):
    """Bound raw provenance payload size."""
    try:
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) <= limit:
            return payload
        return {"_truncated": True, "_head": text[:limit]}
    except (TypeError, ValueError):
        return {"_unserializable": True}
