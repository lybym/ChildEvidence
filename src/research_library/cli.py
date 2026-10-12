"""CLI entry: python -m research_library <command>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import acquisition, db, discover, exporters, reports, verify
from .config import Config
from .http_client import HttpClient
from .normalize import norm_doi, norm_title, title_similarity
from .pdfcheck import sha256_file, validate_pdf
from .sources import CrossrefClient, EricClient, EuropePMCClient, OpenAlexClient, SemanticScholarClient


def make_api_logger(conn):
    def log(source=None, endpoint=None, http_status=None, ok=None, ms=None, error=None):
        try:
            conn.execute(
                "INSERT INTO api_log (source, endpoint, http_status, ok, ms, at, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (source, (endpoint or "")[:500], http_status, 1 if ok else 0, ms,
                 db.now_iso(), (error or "")[:300]),
            )
            conn.commit()
        except Exception:
            pass
    return log


def build_clients(conn, config: Config):
    http = HttpClient(
        config.cache_dir,
        user_agent=config.user_agent(),
        host_min_interval=config.host_rate_limits(),
        api_log_fn=make_api_logger(conn),
    )
    return {
        "http": http,
        "openalex": OpenAlexClient(http, mailto=config.contact_email,
                                   api_key=config.openalex_api_key),
        "crossref": CrossrefClient(http, mailto=config.crossref_mailto),
        "eric": EricClient(http),
        "europepmc": EuropePMCClient(http),
        "semanticscholar": SemanticScholarClient(http),
    }


# ------------------------------------------------------------------ commands
def cmd_discover(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    clients = build_clients(conn, config)
    run_id = db.start_run(conn, "discover")
    try:
        stats = {"seeds": None, "topics": None, "anchors": None, "promotion": None}
        if not args.no_seeds:
            stats["seeds"] = discover.run_seeds(conn, config.seeds, clients["openalex"], clients["eric"])
            print(f"[seeds] resolved={stats['seeds']['resolved']} failed={stats['seeds']['failed']}")
            for f in stats["seeds"]["failures"]:
                print(f"  - seed failure: {f['seed']}: {f['error']}")
        if not args.no_topics:
            stats["topics"] = discover.run_topics(
                conn, config.topics, clients["openalex"], clients["eric"], clients["europepmc"],
                domains=args.domains.split(",") if args.domains else None,
                per_query_limit=args.per_query_limit,
                max_queries_per_domain=args.max_queries_per_domain)
            print(f"[topics] queries={stats['topics']['queries_run']}"
                  f" candidates={stats['topics']['candidates']} filtered={stats['topics']['filtered']}"
                  f" failed={stats['topics']['queries_failed']}")
        if not args.no_anchors:
            stats["anchors"] = discover.expand_anchors(conn, config.seeds, clients["openalex"])
            print(f"[anchors] expanded={stats['anchors']['anchors']} candidates={stats['anchors']['candidates']}")
        if not args.no_promote:
            stats["promotion"] = discover.promote_candidates(conn, config.topics, dry_run=args.dry_run)
            for d, s in (stats["promotion"]["per_domain"] or {}).items():
                print(f"[promote] {d}: available={s['available']} promoted={s['promoted']} rejected={s['rejected']}")
        db.finish_run(conn, run_id, json.dumps({k: (v if not isinstance(v, dict) else "ok") for k, v in stats.items()},
                                               ensure_ascii=False)[:1000])
    except Exception as e:
        db.finish_run(conn, run_id, f"error: {e!r}")
        raise
    finally:
        conn.close()
    return 0


def cmd_verify(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    clients = build_clients(conn, config)
    run_id = db.start_run(conn, "verify")
    include = ("ingested", "candidate") if args.include_candidates else ("ingested",)
    stats = verify.verify_all(conn, clients["crossref"], clients["openalex"],
                              limit=args.limit, include_status=include, force=args.force)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    db.finish_run(conn, run_id, json.dumps(stats))
    conn.close()
    return 0


def cmd_acquire(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    clients = build_clients(conn, config)
    run_id = db.start_run(conn, "acquire")
    stats = acquisition.acquire_all(conn, clients["http"], config.pdf_dir,
                                    email=config.unpaywall_email, limit=args.limit,
                                    include_terminal=args.include_terminal)
    queued = acquisition.refresh_manual_queue(conn)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"[manual-queue] new entries: {queued}")
    db.finish_run(conn, run_id, json.dumps({**stats, "manual_queue_new": queued}))
    conn.close()
    return 0


def cmd_verify_pdfs(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    run_id = db.start_run(conn, "verify-pdfs")
    rows = conn.execute(
        "SELECT internal_id, local_pdf_path, sha256, pdf_file_size FROM works"
        " WHERE access_status='pdf_downloaded'"
    ).fetchall()
    stats = {"checked": 0, "ok": 0, "missing": 0, "corrupt": 0, "sha_mismatch": 0}
    for r in rows:
        stats["checked"] += 1
        p = Path(r["local_pdf_path"] or "")
        if not p.exists():
            stats["missing"] += 1
            db.append_json_list(conn, r["internal_id"], "retrieval_errors",
                                [{"stage": "verify_pdf", "at": db.now_iso(), "error": f"missing file {p}"}])
            continue
        v = validate_pdf(p)
        if not v["ok"]:
            stats["corrupt"] += 1
            db.append_json_list(conn, r["internal_id"], "retrieval_errors",
                                [{"stage": "verify_pdf", "at": db.now_iso(), "error": f"invalid: {v['checks']}"}])
            continue
        if r["sha256"]:
            current = sha256_file(p)
            if current != r["sha256"]:
                stats["sha_mismatch"] += 1
                db.update_work(conn, r["internal_id"], sha256=current, last_checked_at=db.now_iso())
                continue
        stats["ok"] += 1
        db.update_work(conn, r["internal_id"], last_checked_at=db.now_iso())
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    db.finish_run(conn, run_id, json.dumps(stats))
    conn.close()
    return 0


def cmd_export(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    outdir = Path(args.outdir) if args.outdir else config.exports_dir
    counts = exporters.export_all(conn, outdir)
    print(json.dumps(counts, ensure_ascii=False, indent=1))
    print(f"exports -> {outdir}")
    conn.close()
    return 0


def cmd_import_pdf(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    path = Path(args.pdf_path)
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 2
    v = validate_pdf(path)
    if not v["ok"]:
        print(f"ERROR: not a valid PDF: {v['checks']}")
        return 2
    work = None
    if args.doi:
        work = db.find_by_doi(conn, norm_doi(args.doi) or "")
    elif args.id_:
        work = db.get_work(conn, args.id_)
    elif args.title:
        rows = conn.execute("SELECT * FROM works WHERE record_status='ingested'").fetchall()
        best = None
        for r in rows:
            sim = title_similarity(args.title, r["title"])
            if best is None or sim > best[0]:
                best = (sim, r)
        if best and best[0] >= 0.90:
            work = best[1]
        else:
            print("ERROR: no confident title match; use --doi or --id")
            return 2
    else:
        print("ERROR: provide --doi, --id or --title to match the PDF to an entry")
        return 2
    if work is None:
        print("ERROR: matching work not found in database; run discover first")
        return 2
    sha = sha256_file(path)
    if work["local_pdf_path"] and Path(work["local_pdf_path"]).exists() and work["sha256"] == sha:
        print(f"already imported: {work['internal_id']}")
        return 0
    if work["local_pdf_path"] and Path(work["local_pdf_path"]).exists() and not args.force:
        print(f"ERROR: {work['internal_id']} already has a different PDF; use --force to replace")
        return 2
    dest = config.pdf_dir / f"{work['internal_id']}.pdf"
    config.pdf_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(path, dest)
    db.update_work(
        conn, work["internal_id"],
        access_status="pdf_downloaded",
        local_pdf_path=str(dest),
        pdf_version=args.pdf_version or "manual_import_version_unspecified",
        license=args.license or "license_unknown",
        sha256=sha,
        pdf_file_size=v["size"],
        pdf_page_count=v.get("page_count"),
        downloaded_at=db.now_iso(),
        last_checked_at=db.now_iso(),
        pdf_url=None,
    )
    conn.execute("DELETE FROM manual_queue WHERE internal_id=?", (work["internal_id"],))
    conn.commit()
    db.log_download(conn, work["internal_id"], None, 1, "imported_manual", None,
                    "application/pdf", v["size"], sha, f"manual import from {path}")
    print(f"imported: {work['internal_id']} -> {dest}")
    conn.close()
    return 0


def cmd_status(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    q = lambda sql: conn.execute(sql).fetchone()[0]
    print(f"db: {config.db_path}")
    print(f"pdf dir: {config.pdf_dir} ({sum(1 for _ in config.pdf_dir.glob('*.pdf')) if config.pdf_dir.exists() else 0} files)")
    counts = conn.execute("SELECT record_status, COUNT(*) FROM works GROUP BY 1").fetchall()
    for r in counts:
        print(f"  {r[0]}: {r[1]}")
    acc = conn.execute("SELECT access_status, COUNT(*) FROM works WHERE record_status='ingested' GROUP BY 1").fetchall()
    print("access_status (ingested):")
    for r in acc:
        print(f"  {r[0]}: {r[1]}")
    ver = conn.execute("SELECT metadata_status, COUNT(*) FROM works WHERE record_status='ingested' GROUP BY 1").fetchall()
    print("metadata_status (ingested):")
    for r in ver:
        print(f"  {r[0]}: {r[1]}")
    dom = conn.execute(
        "SELECT j.value, COUNT(*) FROM works w, json_each(w.research_domains) j"
        " WHERE w.record_status='ingested' GROUP BY j.value").fetchall()
    print("domains (ingested, may overlap):")
    for r in dom:
        print(f"  {r[0]}: {r[1]}")
    print(f"manual_queue rows: {q('SELECT COUNT(*) FROM manual_queue')}")
    print(f"api_log rows: {q('SELECT COUNT(*) FROM api_log')}")
    print(f"download_log rows: {q('SELECT COUNT(*) FROM download_log')}")
    conn.close()
    return 0


def cmd_docs(args, config: Config) -> int:
    conn = db.connect(config.db_path)
    out = reports.write_all(conn, config.docs_dir, config)
    for k, v in out.items():
        print(f"wrote {v}")
    conn.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="research", description="ChildEvidence Research Library v0.1")
    parser.add_argument("--data-dir", default=None, help="data directory (default: <project>/data/research-library, override with CHILDEVIDENCE_DATA_DIR)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="seed + topic discovery, citation expansion, promotion")
    p.add_argument("--domains", default=None)
    p.add_argument("--per-query-limit", type=int, default=10)
    p.add_argument("--max-queries-per-domain", type=int, default=None)
    p.add_argument("--no-seeds", action="store_true")
    p.add_argument("--no-topics", action="store_true")
    p.add_argument("--no-anchors", action="store_true")
    p.add_argument("--no-promote", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("verify", help="Crossref metadata verification + OpenAlex backfill")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--include-candidates", action="store_true")

    p = sub.add_parser("acquire", help="download legal open PDFs with validation")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--include-terminal", action="store_true",
                   help="also retry works whose access status is already terminal")

    p = sub.add_parser("verify-pdfs", help="validate existing local PDFs")
    p = sub.add_parser("export", help="export CSV/JSONL/BibTeX")
    p.add_argument("--outdir", default=None)

    p = sub.add_parser("import-pdf", help="import a manually downloaded PDF")
    p.add_argument("pdf_path")
    p.add_argument("--doi", default=None)
    p.add_argument("--id", dest="id_", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--pdf-version", default=None)
    p.add_argument("--license", default=None)
    p.add_argument("--force", action="store_true")

    sub.add_parser("status", help="show library status")
    sub.add_parser("docs", help="regenerate docs/research/*.md deliverables")

    args = parser.parse_args(argv)
    config = Config(data_dir=Path(args.data_dir) if args.data_dir else None)
    config.ensure_dirs()
    handlers = {
        "discover": cmd_discover, "verify": cmd_verify, "acquire": cmd_acquire,
        "verify-pdfs": cmd_verify_pdfs, "export": cmd_export, "import-pdf": cmd_import_pdf,
        "status": cmd_status, "docs": cmd_docs,
    }
    return handlers[args.command](args, config)


if __name__ == "__main__":
    sys.exit(main())
