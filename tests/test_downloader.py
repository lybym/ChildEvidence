import http.server
import json
import threading
import unittest
from pathlib import Path

from research_library import acquisition, db, ingest
from research_library.http_client import HttpClient

from helpers import HTML_BYTES, JUNK_BYTES, make_pdf, make_tmp_dir


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok.pdf":
            body = make_pdf(2)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/html.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(HTML_BYTES)))
            self.end_headers()
            self.wfile.write(HTML_BYTES)
        elif self.path == "/junk.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(JUNK_BYTES)))
            self.end_headers()
            self.wfile.write(JUNK_BYTES)
        elif self.path == "/ok2.pdf":
            body = make_pdf(1)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect-html":
            self.send_response(302)
            self.send_header("Location", "/html.pdf")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class DownloaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = make_tmp_dir("dl-")
        self.conn = db.connect(self.tmp / "t.sqlite")
        self.http = HttpClient(self.tmp / "cache", user_agent="test-agent",
                               host_min_interval={"127.0.0.1": 0.01})
        self.pdf_dir = self.tmp / "pdf"

    def _ingest_with_candidate(self, title, url, doi=None, oa=False):
        res = ingest.ingest(self.conn, {
            "title": title,
            "authors": [{"name": "A Author", "given": None, "family": "Author", "orcid": None}],
            "publication_year": 2020,
            "journal_or_publisher": "Test Journal",
        }, source_name="test", record_status="ingested")
        work = db.get_work(self.conn, res["internal_id"])
        raws = {}
        try:
            raws = json.loads(work["raw_sources"] or "{}")
        except (TypeError, json.JSONDecodeError):
            raws = {}
        raws["pdf_candidates"] = [{"url": url, "origin": "openalex",
                                   "version": "publishedVersion", "license": "cc-by"}]
        raws["openalex"] = {"open_access": {"is_oa": oa}}
        db.update_work(self.conn, res["internal_id"], raw_sources=raws, doi=doi,
                       access_status="open_candidate" if oa else "pending")
        return res["internal_id"]

    def test_successful_download(self):
        iid = self._ingest_with_candidate("Work One", f"http://127.0.0.1:{self.port}/ok.pdf")
        work = db.get_work(self.conn, iid)
        outcome = acquisition.acquire_work(self.conn, work, self.http, self.pdf_dir)
        self.assertEqual(outcome, "downloaded")
        row = db.row_to_dict(db.get_work(self.conn, iid))
        self.assertEqual(row["access_status"], "pdf_downloaded")
        self.assertTrue(Path(row["local_pdf_path"]).exists())
        self.assertEqual(row["pdf_page_count"], 2)
        self.assertTrue(row["sha256"])
        self.assertEqual(len(row["sha256"]), 64)
        self.assertEqual(row["pdf_version"], "published_version")
        self.assertEqual(row["license"], "cc-by")
        # second run is a no-op
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "already")

    def test_html_login_page_rejected(self):
        iid = self._ingest_with_candidate("Work Two", f"http://127.0.0.1:{self.port}/html.pdf")
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "manual_required")
        row = db.get_work(self.conn, iid)
        self.assertNotEqual(row["access_status"], "pdf_downloaded")
        self.assertFalse((self.pdf_dir / f"{iid}.pdf").exists())

    def test_junk_pdf_rejected(self):
        iid = self._ingest_with_candidate("Work Three", f"http://127.0.0.1:{self.port}/junk.pdf")
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "manual_required")
        self.assertFalse((self.pdf_dir / f"{iid}.pdf").exists())

    def test_octet_stream_accepted_with_pdf_header(self):
        iid = self._ingest_with_candidate("Work Four", f"http://127.0.0.1:{self.port}/ok2.pdf")
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "downloaded")

    def test_404_logged_as_failure(self):
        iid = self._ingest_with_candidate("Work Five", f"http://127.0.0.1:{self.port}/missing.pdf")
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "manual_required")
        logs = self.conn.execute(
            "SELECT * FROM download_log WHERE internal_id=?", (iid,)).fetchall()
        self.assertTrue(len(logs) >= 1)
        self.assertEqual(logs[-1]["status"], "failed")

    def test_duplicate_content_not_attached_twice(self):
        iid1 = self._ingest_with_candidate("Dup One", f"http://127.0.0.1:{self.port}/ok.pdf")
        iid2 = self._ingest_with_candidate("Dup Two", f"http://127.0.0.1:{self.port}/ok.pdf")
        out1 = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid1),
                                        self.http, self.pdf_dir)
        self.assertEqual(out1, "downloaded")
        out2 = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid2),
                                        self.http, self.pdf_dir)
        self.assertEqual(out2, "manual_required")
        err = json.loads(db.get_work(self.conn, iid2)["retrieval_errors"])
        self.assertTrue(any("duplicate content" in str(e.get("error", "")) for e in err))

    def test_no_candidates(self):
        res = ingest.ingest(self.conn, {
            "title": "No Candidate Work",
            "authors": [{"name": "A Author", "given": None, "family": "Author", "orcid": None}],
            "publication_year": 2019,
        }, source_name="test", record_status="ingested")
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, res["internal_id"]),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "no_candidate")

    def test_manual_queue_refresh(self):
        iid = self._ingest_with_candidate("Queue Work", f"http://127.0.0.1:{self.port}/html.pdf",
                                          doi="10.5555/fake.1")
        acquisition.acquire_work(self.conn, db.get_work(self.conn, iid), self.http, self.pdf_dir)
        n = acquisition.refresh_manual_queue(self.conn)
        self.assertEqual(n, 1)
        q = self.conn.execute("SELECT * FROM manual_queue WHERE internal_id=?", (iid,)).fetchone()
        self.assertIsNotNone(q)
        self.assertTrue(q["search_hint"].startswith("https://doi.org/"))
        # idempotent
        n = acquisition.refresh_manual_queue(self.conn)
        self.assertEqual(n, 0)

    def test_open_html_only_status(self):
        iid = self._ingest_with_candidate("Html Only Work",
                                          f"http://127.0.0.1:{self.port}/html.pdf", oa=True)
        outcome = acquisition.acquire_work(self.conn, db.get_work(self.conn, iid),
                                           self.http, self.pdf_dir)
        self.assertEqual(outcome, "open_html_only")
        self.assertEqual(db.get_work(self.conn, iid)["access_status"], "open_html_only")


if __name__ == "__main__":
    unittest.main()
