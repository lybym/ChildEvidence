"""Discovery orchestration: seeds, topic queries, citation expansion, selection."""

from __future__ import annotations

import json

from . import db, ingest
from .db import now_iso
from .normalize import norm_doi, norm_title, title_similarity
from .sources import OpenAlexClient
from .sources.eric import EricClient
from .sources.europepmc import EuropePMCClient

EXCLUDE_DOC_TYPES = {"editorial", "letter", "erratum", "paratext",
                     "supplementary_materials"}

CURRENT_YEAR = 2026


def acceptable(rec: dict) -> tuple[bool, str]:
    if not rec.get("title"):
        return False, "no_title"
    if not rec.get("authors"):
        return False, "no_authors"
    year = rec.get("publication_year")
    if year is None:
        return False, "no_year"
    if int(year) < 1900 or int(year) > CURRENT_YEAR + 1:
        return False, "year_out_of_range"
    if rec.get("document_type") in EXCLUDE_DOC_TYPES:
        return False, f"excluded_type:{rec.get('document_type')}"
    if rec.get("is_retracted"):
        return False, "retracted"
    return True, ""


# ------------------------------------------------------------------- seeds
def _attach_direct_pdf(conn, seed: dict, internal_id: str) -> None:
    direct = seed.get("direct_pdf")
    if not direct:
        if seed.get("landing_page"):
            db.append_json_list(conn, internal_id, "source_urls", [seed["landing_page"]])
        return
    row = db.get_work(conn, internal_id)
    raws = {}
    try:
        raws = json.loads(row["raw_sources"] or "{}")
    except (TypeError, json.JSONDecodeError):
        raws = {}
    cands = raws.get("pdf_candidates") or []
    cands.append({
        "url": direct,
        "landing_page": seed.get("landing_page"),
        "source": seed.get("publisher") or "official site",
        "license": seed.get("license"),
        "version": "published_version",
        "origin": "seed_direct",
    })
    raws["pdf_candidates"] = cands
    if seed.get("landing_page"):
        db.append_json_list(conn, internal_id, "source_urls", [seed["landing_page"]])
    db.update_work(conn, internal_id, raw_sources=raws)


def _manual_seed_rec(seed: dict) -> dict:
    authors = []
    if seed.get("author"):
        authors.append({"name": seed["author"], "given": None, "family": None, "orcid": None})
    return {
        "title": seed["title"],
        "authors": authors,
        "publication_year": seed.get("year"),
        "publication_date": str(seed.get("year")) if seed.get("year") else None,
        "journal_or_publisher": seed.get("publisher"),
        "language": seed.get("language") or "en",
        "document_type": seed.get("document_type") or "report",
        "canonical_url": seed.get("landing_page"),
        "source_urls": [seed["landing_page"]] if seed.get("landing_page") else [],
        "pdf_candidates": [],
    }


def resolve_seed(seed: dict, openalex: OpenAlexClient, eric: EricClient | None = None) -> dict:
    """Resolve a seed entry (title/author/year hints) against live APIs.

    Metadata truth comes from the API response, never from the hints.
    """
    title_hint = seed.get("title") or ""
    year_hint = seed.get("year")

    if seed.get("doi"):
        doi = norm_doi(seed["doi"])
        if doi:
            res = openalex.get_work_by_doi(doi)
            if res.get("ok"):
                rec = res["rec"]
                sim = title_similarity(rec.get("title"), title_hint)
                names = " ".join((a.get("name") or "") for a in rec.get("authors") or []).lower()
                names_ok = (not seed.get("author_surname")
                            or seed["author_surname"].lower() in names)
                year_exact = (year_hint is not None and rec.get("publication_year")
                              == year_hint)
                # A DOI hit is authoritative; a lower title similarity is
                # acceptable when the record was located BY that DOI and
                # author surname + exact year corroborate it (subtitle
                # truncation in OpenAlex display names is common).
                if names_ok and (sim >= 0.70 or (year_exact and sim >= 0.45)):
                    return {"ok": True, "rec": rec, "raw": res["raw"],
                            "via": f"openalex_doi(sim={sim:.2f})"}
            # fall through to title search if DOI lookup failed or mismatched

    res = openalex.search(search=title_hint, per_page=10)
    best = None
    if res.get("ok"):
        for raw in res.get("results") or []:
            rec = OpenAlexClient.normalize(raw)
            sim = title_similarity(rec.get("title"), title_hint)
            if sim < 0.75:
                continue
            if year_hint and rec.get("publication_year") and abs(int(rec["publication_year"]) - int(year_hint)) > 3:
                continue
            if seed.get("author_surname"):
                names = " ".join((a.get("name") or "") for a in rec.get("authors") or []).lower()
                if seed["author_surname"].lower() not in names:
                    continue
            if best is None or sim > best[0]:
                best = (sim, rec, raw)
    if best:
        sim, rec, raw = best
        return {"ok": True, "rec": rec, "raw": raw, "via": f"openalex_search(sim={sim:.2f})"}

    if eric is not None:
        res = eric.search(f'title:"{title_hint}"', rows=10)
        if res.get("ok"):
            for doc in res.get("docs") or []:
                rec = EricClient.normalize(doc)
                sim = title_similarity(rec.get("title"), title_hint)
                if sim >= 0.8 and (not year_hint or not rec.get("publication_year")
                                   or abs(int(rec["publication_year"]) - int(year_hint)) <= 3):
                    return {"ok": True, "rec": rec, "raw": doc, "via": f"eric_search(sim={sim:.2f})"}
    return {"ok": False, "error": "seed not resolved"}


def ingest_seed(conn, seed: dict, resolved: dict) -> dict:
    rec = dict(resolved["rec"])
    raw = resolved.get("raw")
    doc_type = seed.get("document_type") or rec.get("document_type")
    if seed.get("document_type") in ("report", "practice_guide", "guideline", "book"):
        rec["document_type"] = seed["document_type"]
    result = ingest.ingest(
        conn, rec,
        source_name=f"seed:{resolved.get('via', 'unknown')}",
        raw_payload=raw,
        domains=seed.get("domains") or [],
        tags=seed.get("tags") or [],
        frameworks=seed.get("frameworks") or [],
        record_status="ingested",
        evidence_category=seed.get("evidence_category"),
        peer_review_status=seed.get("peer_review_status"),
        ingestion_notes=f"seed:{seed.get('id')}",
        query_key=f"seed:{seed.get('id')}",
        document_type=doc_type,
    )
    _attach_direct_pdf(conn, seed, result["internal_id"])
    return result


def run_seeds(conn, seeds_cfg: dict, openalex, eric=None) -> dict:
    stats = {"resolved": 0, "failed": 0, "manual": 0, "failures": []}
    for seed in seeds_cfg.get("seeds") or []:
        if seed.get("manual_entry"):
            result = ingest.ingest(
                conn, _manual_seed_rec(seed),
                source_name="seed:manual_entry",
                raw_payload={"seed_config": {k: v for k, v in seed.items() if k != "direct_pdf"},
                             "note": "institutional entry; verify against official landing page"},
                domains=seed.get("domains") or [],
                tags=seed.get("tags") or [],
                frameworks=seed.get("frameworks") or [],
                record_status="ingested",
                evidence_category=seed.get("evidence_category"),
                peer_review_status=seed.get("peer_review_status")
                or "institutional_report_not_journal_peer_reviewed",
                ingestion_notes=f"seed:{seed.get('id')} (manual institutional entry)",
                query_key=f"seed:{seed.get('id')}",
                document_type=seed.get("document_type") or "report",
            )
            _attach_direct_pdf(conn, seed, result["internal_id"])
            stats["manual"] += 1
            stats["resolved"] += 1
            continue
        resolved = resolve_seed(seed, openalex, eric)
        if not resolved.get("ok"):
            stats["failed"] += 1
            stats["failures"].append({"seed": seed.get("id"), "error": resolved.get("error")})
            continue
        ingest_seed(conn, seed, resolved)
        stats["resolved"] += 1
    return stats


# ------------------------------------------------------------- topic queries
def run_topics(conn, topics_cfg: dict, openalex, eric=None, epmc=None, *,
               domains=None, per_query_limit=10, per_page=15, max_queries_per_domain=None) -> dict:
    stats = {"queries_run": 0, "candidates": 0, "filtered": 0, "queries_failed": 0,
             "per_domain": {}}
    blocks = topics_cfg.get("domains") or {}
    wanted = set(domains) if domains else None
    for domain, block in blocks.items():
        if wanted and domain not in wanted:
            continue
        queries = block.get("queries") or []
        if max_queries_per_domain:
            queries = queries[:max_queries_per_domain]
        dstat = {"queries": 0, "candidates": 0, "filtered": 0, "failed": 0}
        for q in queries:
            qid = q.get("id") or f"{domain}:{len(dstat)}"
            ran = False
            if q.get("openalex"):
                spec = q["openalex"]
                filters = dict(spec.get("filter") or {})
                res = openalex.search(search=spec.get("search"),
                                      filters=filters or None,
                                      sort=spec.get("sort"),
                                      per_page=spec.get("per_page", per_page))
                if not res.get("ok"):
                    dstat["failed"] += 1
                    stats["queries_failed"] += 1
                else:
                    ran = True
                    ingested = 0
                    for raw in res.get("results") or []:
                        rec = OpenAlexClient.normalize(raw)
                        ok, reason = acceptable(rec)
                        if not ok:
                            stats["filtered"] += 1
                            dstat["filtered"] += 1
                            continue
                        if ingested >= q.get("limit", per_query_limit):
                            break
                        ingest.ingest(conn, rec, source_name="openalex",
                                      raw_payload=raw, domains=[domain],
                                      tags=q.get("tags") or [],
                                      frameworks=q.get("frameworks") or [],
                                      record_status="candidate",
                                      query_key=qid)
                        ingested += 1
                        stats["candidates"] += 1
                        dstat["candidates"] += 1
            if q.get("eric") and eric is not None:
                spec = q["eric"]
                res = eric.search(spec.get("query") or "", rows=spec.get("rows", per_page))
                if not res.get("ok"):
                    dstat["failed"] += 1
                else:
                    ran = True
                    ingested = 0
                    for doc in res.get("docs") or []:
                        rec = EricClient.normalize(doc)
                        ok, reason = acceptable(rec)
                        if not ok:
                            stats["filtered"] += 1
                            dstat["filtered"] += 1
                            continue
                        if ingested >= q.get("limit", per_query_limit):
                            break
                        ingest.ingest(conn, rec, source_name="eric", raw_payload=doc,
                                      domains=[domain], tags=q.get("tags") or [],
                                      frameworks=q.get("frameworks") or [],
                                      record_status="candidate", query_key=qid)
                        ingested += 1
                        stats["candidates"] += 1
                        dstat["candidates"] += 1
            if q.get("europepmc") and epmc is not None:
                spec = q["europepmc"]
                res = epmc.search(spec.get("query") or "", rows=spec.get("rows", per_page))
                if not res.get("ok"):
                    dstat["failed"] += 1
                else:
                    ran = True
                    ingested = 0
                    for hit in res.get("results") or []:
                        rec = EuropePMCClient.normalize(hit)
                        ok, reason = acceptable(rec)
                        if not ok:
                            stats["filtered"] += 1
                            dstat["filtered"] += 1
                            continue
                        if ingested >= q.get("limit", per_query_limit):
                            break
                        ingest.ingest(conn, rec, source_name="europepmc", raw_payload=hit,
                                      domains=[domain], tags=q.get("tags") or [],
                                      frameworks=q.get("frameworks") or [],
                                      record_status="candidate", query_key=qid)
                        ingested += 1
                        stats["candidates"] += 1
                        dstat["candidates"] += 1
            if ran:
                dstat["queries"] += 1
                stats["queries_run"] += 1
        stats["per_domain"][domain] = dstat
    return stats


# -------------------------------------------------------- citation expansion
def expand_anchors(conn, seeds_cfg: dict, openalex: OpenAlexClient, *,
                   max_references=12, max_related=4, domains_default=("child_development",)) -> dict:
    stats = {"anchors": 0, "candidates": 0}
    for seed in seeds_cfg.get("seeds") or []:
        if not seed.get("anchor"):
            continue
        doi = norm_doi(seed.get("doi"))
        if not doi:
            continue
        res = openalex.get_work_by_doi(doi)
        if not res.get("ok"):
            continue
        raw = res["raw"]
        ref_ids = [w.rsplit("/", 1)[-1] for w in (raw.get("referenced_works") or [])]
        rel_ids = [w.rsplit("/", 1)[-1] for w in (raw.get("related_works") or [])]
        pick = ref_ids[:max_references] + rel_ids[:max_related]
        if not pick:
            continue
        got = openalex.get_works_by_openalex_ids(pick)
        for raww in got.get("results") or []:
            rec = OpenAlexClient.normalize(raww)
            ok, _ = acceptable(rec)
            if not ok:
                continue
            ingest.ingest(conn, rec, source_name="openalex_citation_expansion",
                          raw_payload=raww,
                          domains=seed.get("domains") or list(domains_default),
                          tags=(seed.get("tags") or []) + ["citation_expansion"],
                          frameworks=seed.get("frameworks") or [],
                          record_status="candidate",
                          query_key=f"expand:{seed.get('id')}")
            stats["candidates"] += 1
        stats["anchors"] += 1
    return stats


# ---------------------------------------------------------------- selection
def score_candidate(work) -> float:
    s = 0.0
    ev = work["evidence_category"]
    s += {"meta_analysis": 3.5, "systematic_review": 3.0, "rct": 2.2,
          "narrative_review": 0.8, "practice_guideline": 1.5}.get(ev, 0.0)
    year = work["publication_year"] or 0
    if year >= 2024:
        s += 1.0
    elif year >= 2023:
        s += 0.5
    domains = json.loads(work["research_domains"] or "[]")
    if "ai_children" in domains and year >= 2024:
        s += 1.5
    cc = work["cited_by_count"] or 0
    if cc >= 300:
        s += 1.5
    elif cc >= 100:
        s += 1.0
    elif cc >= 50:
        s += 0.5
    if work["access_status"] == "open_candidate":
        s += 0.6
    if work["peer_review_status"] == "peer_reviewed_journal_source":
        s += 0.8
    if work["document_type"] == "review_article":
        s += 0.8
    if work["document_type"] == "preprint":
        s -= 1.0
    lang = work["language"] or ""
    if lang == "zh" and "china_family" in domains:
        s += 1.2
    return s


def promote_candidates(conn, topics_cfg: dict, *, dry_run=False) -> dict:
    """Select top candidates per domain quota; reject the rest with reason."""
    quotas = {}
    for domain, block in (topics_cfg.get("domains") or {}).items():
        quotas[domain] = int(block.get("quota", 20))
    stats = {"promoted": 0, "rejected": 0, "per_domain": {}}
    candidates = conn.execute(
        "SELECT * FROM works WHERE record_status='candidate'"
    ).fetchall()
    by_domain: dict[str, list] = {}
    for w in candidates:
        domains = json.loads(w["research_domains"] or "[]")
        primary = domains[0] if domains else "cross_domain"
        by_domain.setdefault(primary, []).append(w)
    for domain, rows in by_domain.items():
        quota = quotas.get(domain, 20)
        rows.sort(key=lambda w: score_candidate(w), reverse=True)
        promoted, rejected = rows[:quota], rows[quota:]
        stats["per_domain"][domain] = {"quota": quota, "available": len(rows),
                                       "promoted": len(promoted), "rejected": len(rejected)}
        if dry_run:
            continue
        for w in promoted:
            db.update_work(conn, w["internal_id"], record_status="ingested",
                           last_checked_at=now_iso())
            stats["promoted"] += 1
        for w in rejected:
            db.update_work(conn, w["internal_id"], record_status="rejected",
                           last_checked_at=now_iso(),
                           ingestion_notes=((w["ingestion_notes"] or "") +
                                            "; below domain quota at selection").strip("; "))
            stats["rejected"] += 1
    return stats
