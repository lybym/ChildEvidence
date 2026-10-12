"""End-to-end smoke test against real APIs (network required).

Usage:
    python scripts/smoke_real.py

Verifies the full pipeline (resolve -> ingest -> verify -> acquire -> export)
with two real works. Uses a temp data directory and prints a summary.
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_library import acquisition, db, discover, exporters, verify  # noqa: E402
from research_library.config import Config  # noqa: E402
from research_library.sources import (  # noqa: E402
    CrossrefClient, EricClient, OpenAlexClient,
)


def main() -> int:
    import uuid
    tmp = ROOT / ".tmp-test" / f"smoke-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    config = Config(data_dir=tmp)
    config.ensure_dirs()
    conn = db.connect(config.db_path)
    http = HttpClientLike = None  # noqa: F841

    from research_library.http_client import HttpClient
    http = HttpClient(config.cache_dir, user_agent=config.user_agent())
    openalex = OpenAlexClient(http, mailto=config.contact_email)
    crossref = CrossrefClient(http, mailto=config.crossref_mailto)
    eric = EricClient(http)

    seeds_cfg = {"seeds": [
        {
            "id": "diamond_2013_executive_functions",
            "title": "Executive Functions",
            "year": 2013,
            "author_surname": "Diamond",
            "doi": "10.1146/annurev-psych-113011-143750",
            "domains": ["child_development"],
            "tags": ["executive_function"],
        },
        {
            "id": "ryan_deci_2020_sdt_education",
            "title": "Intrinsic and extrinsic motivation from a self-determination theory perspective - Definitions, theory, practices, and future directions",
            "year": 2020,
            "author_surname": "Ryan",
            "doi": "10.1016/j.cedpsych.2020.101860",
            "domains": ["learning_sciences"],
            "tags": ["motivation"],
        },
        {
            "id": "sweller_2019_cld_20y",
            "title": "Cognitive Architecture and Instructional Design - 20 Years Later",
            "year": 2019,
            "author_surname": "Sweller",
            "doi": "10.1007/s10648-019-09465-5",
            "domains": ["learning_sciences"],
            "tags": ["cognitive_load"],
        },
    ]}

    stats = discover.run_seeds(conn, seeds_cfg, openalex, eric)
    print("seeds:", json.dumps({k: v for k, v in stats.items() if k != "failures"}))
    assert stats["resolved"] == 3, stats

    for w in conn.execute("SELECT title, doi, publication_year FROM works").fetchall():
        print("resolved:", w["title"], "|", w["doi"], "|", w["publication_year"])

    vstat = verify.verify_all(conn, crossref, openalex)
    print("verify:", vstat)

    astat = acquisition.acquire_all(conn, http, config.pdf_dir, email=config.unpaywall_email)
    print("acquire:", astat)
    queued = acquisition.refresh_manual_queue(conn)
    print("manual queue new:", queued)

    counts = exporters.export_all(conn, tmp / "exports")
    print("export:", counts)

    row = db.row_to_dict(conn.execute(
        "SELECT * FROM works ORDER BY internal_id").fetchall()[-1])
    print(json.dumps({k: row[k] for k in (
        "internal_id", "doi", "title", "metadata_status", "access_status",
        "local_pdf_path", "pdf_file_size", "pdf_page_count", "sha256")}, indent=1))
    print("pdfs in dir:", list((config.pdf_dir).glob("*.pdf")))
    print("smoke data dir:", tmp)
    conn.close()
    ok = row["metadata_status"] == "crossref_verified" and (
        row["access_status"] in ("pdf_downloaded", "open_html_only", "manual_required"))
    any_pdf = bool(list(config.pdf_dir.glob("*.pdf")))
    return 0 if (ok and any_pdf) else 1


if __name__ == "__main__":
    raise SystemExit(main())
