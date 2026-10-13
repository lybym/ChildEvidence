"""Tests for the aggregate task report (presence vs accuracy discipline)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from research_library.parsing import pipeline as pl
from research_library.parsing import report as rpt
from research_library.parsing.adapters.base import AdapterError
from research_library.parsing.config import ParsingConfig
from research_library.config import Config

from helpers import make_pdf, make_tmp_dir
from test_parsing_pipeline import fake_factory, make_inter, make_cfg


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("parsing-report-")
        self.cfg = make_cfg(self.tmp)
        self.pdf = self.tmp / "doc-a.pdf"
        self.pdf.write_bytes(make_pdf(pages=2))
        self.pdf_b = self.tmp / "doc-b.pdf"
        self.pdf_b.write_bytes(make_pdf(pages=3))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_two_docs(self):
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        # doc-b: primary fails, fallback succeeds -> fallback artifact
        inter_fb = make_inter("pdfplumber", version="0.11.7")
        fail = {"fake": AdapterError("primary failed")}
        with mock.patch.object(pl, "get_adapter",
                               fake_factory({"fake": inter_fb, "pdfplumber": inter_fb},
                                            fail=fail)):
            pl.run_document(self.pdf_b, self.cfg, document_id="doc-b")

    def test_report_aggregates_and_metric_discipline(self):
        self._build_two_docs()
        rep = rpt.build_report(self.cfg.output_root)
        self.assertEqual(2, rep["documents_in_artifact_store"])
        self.assertEqual({"ok": 1, "fallback": 1}, rep["status_counts"])
        self.assertEqual({"fake": 1, "pdfplumber": 1}, rep["parser_counts"])
        loc = rep["localization"]
        self.assertIsNone(loc["localization_accuracy"])
        self.assertIn("存在率", loc["metric_scope_note"])
        self.assertIn("CE-04", loc["metric_scope_note"])
        self.assertEqual(8, loc["paragraphs_total"])
        # presence rate = paragraphs with bbox / total (3 of 4 per ok doc, 3 of 4 fallback)
        self.assertAlmostEqual(0.75, loc["bbox_presence_rate_aggregate"])
        self.assertIsNotNone(rep["runtime"]["duration_sec"])
        # fallback failure reasons surface in per-doc rows
        fb = [d for d in rep["documents"] if d["status"] == "fallback"]
        self.assertEqual(1, len(fb))
        self.assertEqual("fake", fb[0]["failure_reasons"][0]["parser"])

    def test_markdown_render_no_text_leakage(self):
        self._build_two_docs()
        rep = rpt.build_report(self.cfg.output_root)
        md = rpt.render_markdown(rep)
        self.assertIn("非定位准确率", md)
        self.assertIn("doc-a", md)
        # aggregate-only discipline: no paragraph text of the documents appears
        self.assertNotIn("This study reports effects", md)
        self.assertNotIn("Methods section content", md)
        self.assertNotIn("validated scale", md)

    def test_report_deterministic_from_artifacts(self):
        self._build_two_docs()
        a = json.dumps(rpt.build_report(self.cfg.output_root), sort_keys=True,
                       ensure_ascii=False)
        b = json.dumps(rpt.build_report(self.cfg.output_root), sort_keys=True,
                       ensure_ascii=False)
        # only generated_utc differs; documents/status identical
        da = json.loads(a)
        db = json.loads(b)
        da.pop("report_generated_utc")
        db.pop("report_generated_utc")
        self.assertEqual(da, db)

    def test_manifest_enriches_categories(self):
        self._build_two_docs()
        manifest = self.tmp / "m.json"
        manifest.write_text(json.dumps({"documents": [
            {"document_id": "doc-a", "category": "en_regular",
             "sha256": "0" * 64},
        ]}), encoding="utf-8")
        rep = rpt.build_report(self.cfg.output_root,
                               manifest_entries=pl.load_manifest(manifest))
        cats = rep["category_declared_counts"]
        self.assertIn("undeclared", cats)  # sha in manifest doesn't match real sha
        self.assertTrue(cats.get("undeclared", 0) >= 1)


if __name__ == "__main__":
    unittest.main()
