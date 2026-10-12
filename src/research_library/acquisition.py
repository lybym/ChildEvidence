"""Acquisition: locate legal open PDFs and download with full validation.

Sources consulted per work, in priority order:
  1. Europe PMC full-text PDF (official archive, requires PMCID)
  2. OpenAlex best OA location / locations (publisher or repository)
  3. Unpaywall (DOI-based OA lookup)
  4. Crossref full-text links (content-type application/pdf, vor/am)
  5. ERIC full text (U.S. Dept. of Education)
  6. Semantic Scholar openAccessPdf (last resort)
Never touches paywalled/protected content: only URLs advertised by these
official APIs as open access are attempted, and each file must pass PDF
validation before it is accepted.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import db
from .db import now_iso
from .pdfcheck import sha256_file, validate_pdf
from .sources.europepmc import EuropePMCClient

VERSION_MAP = {
    "publishedVersion": "published_version",
    "acceptedVersion": "accepted_manuscript",
    "acceptedManuscript": "accepted_manuscript",
    "submittedVersion": "submitted_version",
}

ORIGIN_PRIORITY = {
    "europepmc": 0,
    "openalex": 1,
    "unpaywall": 2,
    "crossref": 3,
    "eric": 4,
    "semanticscholar": 5,
    "seed_direct": 0,
    "manual_hint": 6,
}


def ensure_unpaywall(conn, work, http, email) -> list:
    """Add Unpaywall PDF candidates (and store trimmed provenance). Returns candidates."""
    doi = work["doi"]
    if not doi or not email:
        return []
    try:
        raw = json.loads(work["raw_sources"] or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if raw.get("unpaywall"):
        return raw.get("pdf_candidates") or []
    res = http.get(f"https://api.unpaywall.org/v2/{doi}", source="unpaywall",
                   params={"email": email})
    js = res.get("json")
    if not js or res.get("error"):
        return raw.get("pdf_candidates") or []
    cands = raw.get("pdf_candidates") or []
    seen = {c.get("url") for c in cands}
    locs = []
    if js.get("best_oa_location"):
        locs.append(js["best_oa_location"])
    for loc in js.get("oa_locations") or []:
        locs.append(loc)
    for loc in locs:
        url = loc.get("url_for_pdf") or (
            loc.get("url") if (loc.get("url") or "").lower().endswith(".pdf") else None
        )
        if url and url not in seen:
            seen.add(url)
            cands.append({
                "url": url,
                "landing_page": loc.get("url_for_landing_page"),
                "source": f"Unpaywall ({loc.get('host_type') or 'unknown host'})",
                "license": loc.get("license"),
                "version": VERSION_MAP.get(loc.get("version"), loc.get("version")),
                "evidence": loc.get("evidence"),
                "origin": "unpaywall",
            })
    raw["pdf_candidates"] = cands
    raw["unpaywall"] = {
        "doi": js.get("doi"),
        "is_oa": js.get("is_oa"),
        "oa_status": js.get("oa_status"),
        "journal_is_oa": js.get("journal_is_oa"),
        "best_oa_location": {
            "url_for_pdf": (js.get("best_oa_location") or {}).get("url_for_pdf"),
            "url_for_landing_page": (js.get("best_oa_location") or {}).get("url_for_landing_page"),
            "license": (js.get("best_oa_location") or {}).get("license"),
            "version": (js.get("best_oa_location") or {}).get("version"),
            "host_type": (js.get("best_oa_location") or {}).get("host_type"),
            "evidence": (js.get("best_oa_location") or {}).get("evidence"),
        } if js.get("best_oa_location") else None,
    }
    db.update_work(conn, work["internal_id"], raw_sources=raw)
    return cands


def ensure_pmcid(conn, work, http) -> None:
    """Resolve a PMCID via Europe PMC when OpenAlex/Unpaywall lacked one.

    Many PMC-deposited works only expose landing pages in OpenAlex/Unpaywall;
    Europe PMC's official full-text archive then provides the PDF.
    """
    if work["pmcid"] or not work["doi"]:
        return
    try:
        raw = json.loads(work["raw_sources"] or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if "europepmc_doi_lookup" in raw:
        return
    epmc = EuropePMCClient(http)
    res = epmc.search(f'DOI:"{work["doi"]}"', rows=3)
    raw["europepmc_doi_lookup"] = {"at": now_iso(), "ok": bool(res.get("ok"))}
    if res.get("ok"):
        for hit in res.get("results") or []:
            if hit.get("pmcid") and hit.get("inEPMC") == "Y" and hit.get("hasPDF") == "Y":
                pmcid = hit["pmcid"]
                raw["europepmc_doi_lookup"]["pmcid"] = pmcid
                cands = raw.get("pdf_candidates") or []
                seen = {c.get("url") for c in cands}
                added = False
                full_urls = (hit.get("fullTextUrlList") or {}).get("fullTextUrl") or []
                for u in full_urls:
                    url = u.get("url")
                    if (u.get("documentStyle") == "pdf" and u.get("availabilityCode") in ("OA", "F")
                            and url and url not in seen):
                        cands.append({
                            "url": url,
                            "landing_page": f"https://europepmc.org/article/PMC/{pmcid}",
                            "source": "Europe PMC (PubMed Central full text)",
                            "license": hit.get("license"),
                            "version": "published_version",
                            "origin": "europepmc",
                        })
                        seen.add(url)
                        added = True
                if added:
                    raw["pdf_candidates"] = cands
                    db.update_work(conn, work["internal_id"], pmcid=pmcid, raw_sources=raw)
                return
    db.update_work(conn, work["internal_id"], raw_sources=raw)


def build_candidates(conn, work) -> list:
    """Merge candidates from raw_sources + derived PMC/ERIC URLs, deduped and sorted."""
    try:
        raw = json.loads(work["raw_sources"] or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    cands = [c for c in (raw.get("pdf_candidates") or []) if isinstance(c, dict)]
    seen = {c.get("url") for c in cands}
    # NOTE: Europe PMC candidates come from official fullTextUrlList entries
    # (added during enrichment / discovery); no synthetic URL is derived here.
    eric_id = work["eric_id"]
    if eric_id:
        url = f"https://files.eric.ed.gov/fulltext/{eric_id}.pdf"
        if url not in seen:
            cands.append({
                "url": url,
                "landing_page": f"https://eric.ed.gov/?id={eric_id}",
                "source": "ERIC (U.S. Department of Education)",
                "license": None,
                "version": "published_version",
                "origin": "eric",
            })
            seen.add(url)

    def priority(c):
        return (ORIGIN_PRIORITY.get(c.get("origin"), 9),
                0 if (c.get("version") == "published_version") else 1)

    cands.sort(key=priority)
    return cands


def acquire_work(conn, work, http, pdf_dir: Path, *, email=None,
                 min_size: int = 8192) -> str:
    """Try to download a validated open PDF for one work.

    Returns one of: already | downloaded | duplicate_content | no_candidate |
    failed | open_html_only
    """
    internal_id = work["internal_id"]
    pdf_dir = Path(pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    final_path = pdf_dir / f"{internal_id}.pdf"

    if work["local_pdf_path"] and Path(work["local_pdf_path"]).exists():
        return "already"

    if work["doi"]:
        ensure_unpaywall(conn, work, http, email)
        ensure_pmcid(conn, work, http)
        work = db.get_work(conn, internal_id)  # refresh after enrichment

    candidates = build_candidates(conn, work)
    if not candidates:
        db.update_work(conn, internal_id, access_status="no_open_pdf_found",
                       last_checked_at=now_iso())
        return "no_candidate"

    sha_owner = {}
    for r in conn.execute(
        "SELECT internal_id, sha256 FROM works WHERE sha256 IS NOT NULL"
    ):
        if r["sha256"]:
            sha_owner[r["sha256"]] = r["internal_id"]

    errors = []
    tmp_path = pdf_dir / f".tmp-{internal_id}.pdf"
    succeeded = False
    try:
        for cand in candidates:
            url = cand.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            res = http.download_to(url, tmp_path, source="acquisition")
            ok_http = not res.get("error") and res.get("status") == 200
            ctype = (res.get("content_type") or "").lower()
            if not ok_http:
                msg = f"{url} -> {res.get('error') or res.get('status')}"
                errors.append({"stage": "download", "url": url, "at": now_iso(), "error": msg})
                db.log_download(conn, internal_id, url, 1, "failed", res.get("status"),
                                ctype, 0, None, msg[:400])
                continue
            if "text/html" in ctype:
                msg = f"{url} -> returned HTML, not a PDF (rejected)"
                errors.append({"stage": "content_type", "url": url, "at": now_iso(), "error": msg})
                db.log_download(conn, internal_id, url, 1, "rejected", res.get("status"),
                                ctype, res.get("file_size", 0), None, msg[:400])
                continue
            validation = validate_pdf(tmp_path, min_size=min_size)
            if not validation["ok"]:
                msg = f"{url} -> invalid PDF: {validation['checks']}"
                errors.append({"stage": "validation", "url": url, "at": now_iso(), "error": msg})
                db.log_download(conn, internal_id, url, 1, "rejected", res.get("status"),
                                ctype, validation.get("size"), None, msg[:400])
                continue
            sha = res.get("sha256") or sha256_file(tmp_path)
            owner = sha_owner.get(sha)
            if owner and owner != internal_id:
                msg = f"{url} -> duplicate content of {owner}"
                errors.append({"stage": "dedup", "url": url, "at": now_iso(), "error": msg})
                db.log_download(conn, internal_id, url, 1, "duplicate", res.get("status"),
                                ctype, validation.get("size"), sha, msg[:400])
                continue
            shutil.move(str(tmp_path), str(final_path))
            version = cand.get("version")
            if isinstance(version, str):
                version = VERSION_MAP.get(version, version)
            license_val = cand.get("license") or "license_unknown"
            db.update_work(
                conn, internal_id,
                access_status="pdf_downloaded",
                pdf_url=url,
                local_pdf_path=str(final_path),
                pdf_version=version or ("published_version" if cand.get("origin") in ("europepmc", "eric") else None),
                license=license_val,
                sha256=sha,
                pdf_file_size=validation["size"],
                pdf_page_count=validation.get("page_count"),
                downloaded_at=now_iso(),
                last_checked_at=now_iso(),
            )
            if cand.get("landing_page"):
                db.append_json_list(conn, internal_id, "source_urls", [cand["landing_page"]])
            db.log_download(conn, internal_id, url, 1, "downloaded", res.get("status"),
                            ctype, validation["size"], sha,
                            f"version={version or 'unknown'}; origin={cand.get('origin')}")
            succeeded = True
            break
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    if succeeded:
        return "downloaded"

    # record failures and set an accurate access status
    updates: dict = {"last_checked_at": now_iso()}
    if errors:
        existing = json.loads(work["retrieval_errors"] or "[]")
        updates["retrieval_errors"] = (existing + errors)[-30:]
    is_oa = False
    try:
        raw = json.loads(work["raw_sources"] or "{}")
        is_oa = bool((raw.get("unpaywall") or {}).get("is_oa")) or bool(raw.get("openalex", {}).get("open_access", {}).get("is_oa"))
    except (TypeError, json.JSONDecodeError):
        pass
    if is_oa:
        updates["access_status"] = "open_html_only"
    else:
        updates["access_status"] = "manual_required"
    db.update_work(conn, internal_id, **updates)
    return "open_html_only" if is_oa else "manual_required"


def acquire_all(conn, http, pdf_dir: Path, *, email=None, limit=None,
                only_record_status=("ingested",), include_terminal: bool = False) -> dict:
    stats = {"already": 0, "downloaded": 0, "duplicate_content": 0,
             "no_candidate": 0, "failed": 0, "open_html_only": 0,
             "manual_required": 0, "total": 0}
    q = "SELECT * FROM works WHERE record_status IN (%s)" % ",".join("?" for _ in only_record_status)
    params = list(only_record_status)
    if include_terminal:
        q += " AND (access_status IS NULL OR access_status != 'pdf_downloaded')"
    else:
        # terminal statuses (manual_required / open_html_only / no_open_pdf_found)
        # were set after trying all known candidates; skip them unless forced
        q += " AND (access_status IS NULL OR access_status IN ('pending','open_candidate','no_open_pdf_found','failed'))"
    q += " ORDER BY internal_id"
    if limit:
        q += f" LIMIT {int(limit)}"
    for work in conn.execute(q, params).fetchall():
        stats["total"] += 1
        try:
            outcome = acquire_work(conn, work, http, pdf_dir, email=email)
        except Exception as e:  # defensive: one bad record must not stop the batch
            db.append_json_list(conn, work["internal_id"], "retrieval_errors",
                                [{"stage": "exception", "at": now_iso(), "error": repr(e)[:300]}])
            outcome = "failed"
        if outcome in ("failed", "duplicate_content"):
            stats["failed"] += 1
        elif outcome in stats:
            stats[outcome] += 1
        else:
            stats["failed"] += 1
    return stats


def refresh_manual_queue(conn) -> int:
    """Ensure every non-downloaded ingested work has a manual_queue row."""
    rows = conn.execute(
        "SELECT * FROM works WHERE record_status='ingested' AND access_status IN"
        " ('manual_required','open_html_only','no_open_pdf_found','failed')"
    ).fetchall()
    now = now_iso()
    n = 0
    existing_ids = {r["internal_id"] for r in conn.execute("SELECT internal_id FROM manual_queue")}
    for w in rows:
        if w["internal_id"] in existing_ids:
            continue
        priority = {
            "meta_analysis": 1, "systematic_review": 2, "rct": 3,
            "practice_guideline": 4, "narrative_review": 4, "policy_report": 5,
            "longitudinal": 5, "other_empirical": 6, "theoretical_conceptual": 7,
            "preprint_empirical": 8,
        }.get(w["evidence_category"], 6)
        reason = {
            "manual_required": "无合法开放 PDF（可能需要机构订阅）",
            "open_html_only": "存在开放 HTML 全文，但未能自动获取 PDF",
            "no_open_pdf_found": "官方 API 未列出开放 PDF",
            "pending": "尚未尝试获取",
        }.get(w["access_status"], w["access_status"] or "unknown")
        if w["language"] == "zh":
            hint = "知网/万方检索标题获取；或通过期刊官网"
        elif w["doi"]:
            hint = f"https://doi.org/{w['doi']} -> 出版商页面；图书馆订阅下载"
        else:
            hint = "官方出版机构页面下载"
        conn.execute(
            "INSERT OR REPLACE INTO manual_queue (internal_id, priority, reason, search_hint, created_at)"
            " VALUES (?,?,?,?,?)",
            (w["internal_id"], priority, reason, hint, now),
        )
        n += 1
    conn.commit()
    return n
