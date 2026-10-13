"""CLI tests: `research parse` is zero-dependency and works with injected fakes."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from research_library import cli
from research_library.parsing import pipeline as pl

from helpers import make_pdf, make_tmp_dir
from test_parsing_pipeline import fake_factory, make_inter, make_cfg


class ParseCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("parsing-cli-")
        self.pdf = self.tmp / "doc-a.pdf"
        self.pdf.write_bytes(make_pdf(pages=1))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(argv)
        return rc, buf.getvalue()

    def test_parse_help_is_zero_dependency(self):
        # no docling/pdfplumber anywhere in the environment for this suite;
        # --data-dir keeps the test hermetic even when the developer's real
        # data dir already holds parse artifacts (e.g. after an E2E run)
        rc, out = self.run_cli(["--data-dir", str(self.tmp / "data"),
                                "parse", "report", "--format", "json"])
        self.assertEqual(0, rc)
        data = json.loads(out)
        self.assertEqual(0, data["documents_in_artifact_store"])

    def test_parse_run_with_fake_adapter(self):
        import os

        inter = make_inter()
        argv = ["--data-dir", str(self.tmp / "data"),
                "parse", "run", "--pdf", str(self.pdf), "--document-id", "doc-a"]
        env = {
            "CHILDEVIDENCE_PARSING_EXECUTION": "inprocess",
            "CHILDEVIDENCE_PARSING_PRIMARY": "fake",
            "CHILDEVIDENCE_PARSING_FALLBACK": "pdfplumber",
        }
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            rc, out = self.run_cli(argv)
        self.assertEqual(0, rc)
        self.assertIn('"parsed": 1', out)

    def test_parse_run_missing_file_fails_cleanly(self):
        rc, out = self.run_cli(["--data-dir", str(self.tmp / "data"),
                                "parse", "run", "--pdf", str(self.tmp / "nope.pdf")])
        self.assertEqual(1, rc)

    def test_parse_report_md_written(self):
        import os

        inter = make_inter()
        out_md = self.tmp / "report.md"
        argv_run = ["--data-dir", str(self.tmp / "data"),
                    "parse", "run", "--pdf", str(self.pdf), "--document-id", "doc-a"]
        argv_report = ["--data-dir", str(self.tmp / "data"),
                       "parse", "report", "--format", "md", "--out", str(out_md)]
        env = {
            "CHILDEVIDENCE_PARSING_EXECUTION": "inprocess",
            "CHILDEVIDENCE_PARSING_PRIMARY": "fake",
            "CHILDEVIDENCE_PARSING_FALLBACK": "pdfplumber",
        }
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            rc1, _ = self.run_cli(argv_run)
            rc2, out = self.run_cli(argv_report)
        self.assertEqual(0, rc1)
        self.assertEqual(0, rc2)
        text = out_md.read_text(encoding="utf-8")
        self.assertIn("存在率", text)
        self.assertIn("doc-a", text)

    def test_parse_models_offline_guard(self):
        rc, out = self.run_cli(["--data-dir", str(self.tmp / "data"),
                                "parse", "models", "--offline"])
        self.assertEqual(2, rc)
        self.assertIn("explicit", out)

    def test_parse_models_verify_only_no_manifest(self):
        rc, out = self.run_cli(["--data-dir", str(self.tmp / "data"),
                                "parse", "models", "--verify-only",
                                "--artifacts-dir", str(self.tmp / "empty")])
        self.assertEqual(1, rc)
        self.assertIn("not found", out)


if __name__ == "__main__":
    unittest.main()
