"""Offline end-to-end smoke test for ChildEvidence (no network).

Flow: build a temp database with clearly-labelled synthetic fixture records ->
CLI import-pdf of a generated PDF -> validate mapping/sha -> export CSV/JSONL/
BibTeX -> generate reports to a temp docs dir. Exercises the same code paths as
the real pipeline without touching network or the production database.

Usage:  python scripts/smoke_offline.py
"""

import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from helpers import make_pdf  # noqa: E402  (test helper, offline)

from research_library import db, exporters, reports  # noqa: E402
from research_library.cli import main as cli_main  # noqa: E402
from research_library.config import Config  # noqa: E402
from research_library.ingest import ingest  # noqa: E402
from research_library.pdfcheck import sha256_file, validate_pdf  # noqa: E402


def main() -> int:
    tmp = ROOT / ".tmp-test" / f"offline-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    config = Config(data_dir=tmp)
    config.ensure_dirs()
    conn = db.connect(config.db_path)

    fixtures = [
        {
            "title": "Fixture Work A (synthetic test record - not a real publication)",
            "authors": [{"name": "Fixture Author", "given": None, "family": "Author", "orcid": None}],
            "publication_year": 2024,
            "journal_or_publisher": "Fixture Journal",
            "doi": None,
            "document_type": "journal_article",
        },
        {
            "title": "Fixture Work B (synthetic test record - not a real publication)",
            "authors": [{"name": "Fixture Author B", "given": None, "family": "Author", "orcid": None}],
            "publication_year": 2023,
            "journal_or_publisher": "Fixture Journal",
            "doi": "10.1000/fixture.b",  # reserved example DOI prefix for docs
            "document_type": "journal_article",
        },
    ]
    ids = []
    for rec in fixtures:
        res = ingest(conn, rec, source_name="fixture", raw_payload={"fixture": True},
                     domains=["learning_sciences"], tags=["fixture"],
                     record_status="ingested", evidence_category="other_empirical",
                     ingestion_notes="synthetic offline smoke fixture")
        ids.append(res["internal_id"])
    print("fixtures ingested:", ids)

    # manual import path via the real CLI (offline)
    pdf = tmp / "fixture-a.pdf"
    pdf.write_bytes(make_pdf(2))
    rc = cli_main(["--data-dir", str(tmp), "import-pdf", str(pdf), "--id", ids[0],
                   "--pdf-version", "published_version", "--license", "CC0-fixture"])
    assert rc == 0, "import-pdf failed"
    row = db.row_to_dict(db.get_work(conn, ids[0]))
    assert row["access_status"] == "pdf_downloaded" and row["pdf_page_count"] == 2
    assert row["sha256"] == sha256_file(row["local_pdf_path"])
    assert Path(row["local_pdf_path"]).exists()
    print("import-pdf OK:", row["local_pdf_path"])

    # re-import same file is idempotent
    rc = cli_main(["--data-dir", str(tmp), "import-pdf", str(pdf), "--id", ids[0]])
    assert rc == 0, "re-import should be a no-op success"

    # invalid pdf rejected
    bad = tmp / "bad.pdf"
    bad.write_bytes(b"<html>not a pdf</html>" * 200)
    rc = cli_main(["--data-dir", str(tmp), "import-pdf", str(bad), "--id", ids[1]])
    assert rc != 0, "html masquerading as pdf must be rejected"
    print("html-as-pdf rejected OK")

    # exports
    counts = exporters.export_all(conn, tmp / "exports")
    assert counts == {"csv": 2, "jsonl": 2, "bibtex": 2}, counts
    js = [json.loads(l) for l in (tmp / "exports" / "works.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["internal_id"] for r in js} == set(ids)
    print("exports OK:", counts)

    # reports to temp docs dir
    class Cfg:  # minimal stand-in with needed attrs
        data_dir = tmp
        cache_dir = tmp / "cache"
    out = reports.write_all(conn, tmp / "docs", Cfg())
    assert (tmp / "docs" / "literature-catalog.md").exists()
    catalog = (tmp / "docs" / "literature-catalog.md").read_text(encoding="utf-8")
    assert "Fixture Work A" in catalog
    print("reports OK:", sorted(out))

    conn.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print("SMOKE_OFFLINE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
