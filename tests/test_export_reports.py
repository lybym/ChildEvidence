import json
import unittest
from pathlib import Path

from research_library import db, exporters, ingest, reports

from helpers import make_tmp_dir


def make_conn():
    return db.connect(make_tmp_dir("db-") / "t.sqlite")


def seed_work(conn, **kw):
    base = {
        "title": "Cognitive Load & Problem_Solving: Effects on Learning",
        "authors": [{"name": "John Sweller", "given": "John", "family": "Sweller", "orcid": None}],
        "publication_year": 1988,
        "journal_or_publisher": "Cognitive Science",
        "doi": "10.1207/s15516709cog1202_4",
        "volume": "12",
        "issue": "2",
        "pages": "257-285",
        "issn": ["0364-0213"],
        "language": "en",
        "document_type": "journal_article",
        "canonical_url": "https://doi.org/10.1207/s15516709cog1202_4",
    }
    base.update(kw)
    return ingest.ingest(conn, base, source_name="test", record_status="ingested",
                         domains=["learning_sciences"], tags=["cognitive_load"])


class ExportReportTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.tmp = make_tmp_dir("exp-")

    def test_exports(self):
        res = seed_work(self.conn)
        db.update_work(self.conn, res["internal_id"], access_status="pdf_downloaded",
                       local_pdf_path="/x/y.pdf", pdf_page_count=12)
        counts = exporters.export_all(self.conn, self.tmp / "exports")
        self.assertEqual(counts["csv"], 1)
        self.assertEqual(counts["jsonl"], 1)
        self.assertEqual(counts["bibtex"], 1)
        csv_text = (self.tmp / "exports" / "works.csv").read_text(encoding="utf-8-sig")
        self.assertIn("Cognitive Load & Problem_Solving", csv_text)
        self.assertIn("John Sweller", csv_text)
        jsonl_lines = (self.tmp / "exports" / "works.jsonl").read_text(encoding="utf-8").strip().splitlines()
        rec = json.loads(jsonl_lines[0])
        self.assertEqual(rec["internal_id"], res["internal_id"])
        self.assertEqual(rec["authors"][0]["family"], "Sweller")
        bib = (self.tmp / "exports" / "works.bib").read_text(encoding="utf-8")
        self.assertIn("@article{", bib)
        self.assertIn("doi = {10.1207/s15516709cog1202_4}", bib)
        # & and _ escaped in BibTeX fields
        self.assertIn("\\&", bib)
        self.assertIn("\\_", bib)

    def test_reports_generated(self):
        seed_work(self.conn)
        class FakeConfig:
            data_dir = self.tmp
            cache_dir = self.tmp / "cache"
        out = reports.write_all(self.conn, self.tmp / "docs", FakeConfig())
        for name in ("literature-catalog.md", "manual-download-queue.md",
                     "acquisition-report.md", "research-taxonomy.md", "methodology.md"):
            self.assertIn(name, out)
            self.assertTrue((self.tmp / "docs" / name).exists())
        catalog = (self.tmp / "docs" / "literature-catalog.md").read_text(encoding="utf-8")
        self.assertIn("B. 教育心理学与学习科学", catalog)
        self.assertIn("Cognitive Load", catalog)
        report = (self.tmp / "docs" / "acquisition-report.md").read_text(encoding="utf-8")
        self.assertIn("正式入库", report)

    def test_rejected_not_exported(self):
        ingest.ingest(self.conn, {
            "title": "Rejected Candidate",
            "authors": [{"name": "X Y", "given": None, "family": None, "orcid": None}],
            "publication_year": 2020,
        }, source_name="test", record_status="rejected")
        counts = exporters.export_all(self.conn, self.tmp / "exports2")
        self.assertEqual(counts["csv"], 0)


if __name__ == "__main__":
    unittest.main()
