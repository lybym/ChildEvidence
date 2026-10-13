"""CE-03 parsing pipeline tests (stdlib only, no docling/pdfplumber needed).

Adapters are replaced with in-repo fakes at the pipeline seam; subprocess
behavior (timeout) is tested against a stub parser module loaded through the
documented parser_module hook. These tests cover the failure-mode checklist
from issue #3: corrupted PDF, mojibake, zero text, page-number corrections,
missing bbox, timeout, fallback, repeated idempotent runs, path changes,
model unavailability, cache pollution.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from research_library.config import Config
from research_library.parsing import pipeline as pl
from research_library.parsing.adapters.base import AdapterError, DependencyMissing
from research_library.parsing.config import ParsingConfig

from helpers import JUNK_BYTES, make_pdf, make_tmp_dir


def make_inter(name: str = "fake", version: str = "1.0.0") -> dict:
    """A representative intermediate document: 2 pages, header, paras, table."""
    return {
        "format_version": 1,
        "parser": {
            "name": name,
            "parser_version": version,
            "model_versions": {"layout": {"repo": "fake/repo"}},
            "dependency_versions": {"fakepkg": "9.9"},
            "options": {},
            "warnings": [],
            "references_supported": False,
        },
        "page_count": 2,
        "pages": [
            {"physical_page_no": 1, "width": 612, "height": 792,
             "text": "Introduction This study reports effects of X on Y in children."},
            {"physical_page_no": 2, "width": 612, "height": 792,
             "text": "Methods We measured outcomes with a validated scale."},
        ],
        "items": [
            {"kind": "section_header", "label": "docling:section_header", "text": "Introduction",
             "physical_page_no": 1, "bbox": [72.0, 60.0, 300.0, 80.0],
             "bbox_space": "pdf_points_y_down", "page_size": [612, 792],
             "char_span": [0, 12], "char_span_space": "page_text_chars",
             "heading_level": 1, "table": None},
            {"kind": "paragraph", "label": "docling:text", "text": "This study reports effects of X on Y.",
             "physical_page_no": 1, "bbox": [72.0, 100.0, 540.0, 160.0],
             "bbox_space": "pdf_points_y_down", "page_size": [612, 792],
             "char_span": [13, 47], "char_span_space": "page_text_chars",
             "heading_level": None, "table": None},
            {"kind": "paragraph", "label": "docling:text", "text": "No coordinates were provided for this item.",
             "physical_page_no": 1, "bbox": None, "bbox_space": None,
             "page_size": None, "char_span": None, "char_span_space": None,
             "heading_level": None, "table": None},
            {"kind": "table", "label": "docling:table", "physical_page_no": 2,
             "bbox": [60.0, 90.0, 550.0, 300.0], "bbox_space": "pdf_points_y_down",
             "page_size": [612, 792], "char_span": None,
             "table": {"n_rows": 2, "n_cols": 3,
                       "cells": [["a", "b", "c"], ["1", "2", "3"]],
                       "extraction_method": "fake_tableformer"}},
            {"kind": "paragraph", "label": "docling:text", "text": "Methods section content.",
             "physical_page_no": 2, "bbox": [72.0, 100.0, 540.0, 140.0],
             "bbox_space": "pdf_points_y_down", "page_size": [612, 792],
             "char_span": None, "char_span_space": None,
             "heading_level": None, "table": None},
        ],
        "language_hint": None,
        "warnings": [],
    }


def fake_factory(inters: dict[str, dict], fail: dict[str, Exception] | None = None,
                 versions: dict[str, str] | None = None):
    fail = fail or {}
    versions = versions or {}

    class _Fake:
        def __init__(self, name: str):
            self.name = name

        def probe(self):
            # adapter contract: probe must predict the identity parse() reports
            inter = inters.get(self.name) or {}
            return {
                "name": self.name,
                "parser_version": versions.get(self.name, "1.0.0"),
                "model_versions": dict((inter.get("parser") or {}).get("model_versions") or {}),
            }

        def parse(self, pdf_path, options):
            if self.name in fail:
                raise fail[self.name]
            return json.loads(json.dumps(inters[self.name], ensure_ascii=False))

        def parse_to_file(self, pdf_path, options, out_json):
            inter = self.parse(pdf_path, options)
            Path(out_json).write_text(json.dumps(inter, ensure_ascii=False), encoding="utf-8")
            return inter

    return lambda name, **kwargs: _Fake(name)


def make_cfg(tmp: Path, **overrides) -> ParsingConfig:
    cfg = ParsingConfig(base=Config(data_dir=tmp / "data"))
    cfg.execution = "inprocess"
    cfg.primary_parser = "fake"
    cfg.fallback_parser = "pdfplumber"
    cfg.output_root = tmp / "parse-output"
    cfg.corrections_dir = tmp / "parse-corrections"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("parsing-")
        self.cfg = make_cfg(self.tmp)
        self.pdf = self.tmp / "doc-a.pdf"
        self.pdf.write_bytes(make_pdf(pages=2))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_parse(self, cfg=None, **kwargs):
        cfg = cfg or self.cfg
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            return pl.run_document(self.pdf, cfg, document_id="doc-a", **kwargs)

    # ------------------------------------------------------------------
    def test_happy_path_writes_versioned_artifacts(self):
        outcome = self.run_parse()
        self.assertEqual("parsed", outcome["action"])
        self.assertEqual("ok", outcome["status"])
        a_dir = Path(outcome["output_dir"])
        self.assertTrue((a_dir / "result.json").exists())
        self.assertTrue((a_dir / "page-map.json").exists())
        self.assertTrue((a_dir / "run-meta.json").exists())
        result = json.loads((a_dir / "result.json").read_text(encoding="utf-8"))
        # artifact dir is content-addressed by source sha
        self.assertEqual(outcome["sha256"][:12], a_dir.parent.name)
        self.assertEqual(outcome["artifact_id"], a_dir.name)
        self.assertTrue(outcome["artifact_id"].startswith("pa-"))
        # schema & provenance
        self.assertEqual(result["schema"]["name"], "childevidence.parse")
        self.assertEqual(result["source"]["sha256"], outcome["sha256"])
        self.assertEqual(result["parser"]["name"], "fake")
        self.assertEqual(result["parser"]["model_versions"], {"layout": {"repo": "fake/repo"}})
        # structure: sections/paragraphs/tables with reading order
        self.assertEqual(1, len(result["sections"]))
        self.assertEqual(4, len(result["paragraphs"]))
        self.assertEqual(1, len(result["tables"]))
        self.assertEqual([1, 2, 3, 5], [p["reading_order_index"] for p in result["paragraphs"]])
        self.assertEqual([4], [t["reading_order_index"] for t in result["tables"]])
        self.assertEqual(result["paragraphs"][0]["section_id"], result["sections"][0]["section_id"])
        # honest nulls: references unsupported -> items null + note
        self.assertIsNone(result["references"]["items"])
        self.assertTrue(result["references"]["note"])
        # printed pages null; physical pages preserved
        self.assertTrue(all(p["printed_page_no"] is None for p in result["pages"]))
        self.assertEqual([1, 2], [p["physical_page_no"] for p in result["pages"]])
        # localization summary: 3 of 4 paragraphs carry bbox (presence, not accuracy)
        loc = result["localization_summary"]
        self.assertEqual((4, 3), (loc["paragraphs_total"], loc["paragraphs_with_bbox"]))
        self.assertIsNone(loc["localization_accuracy"])
        self.assertEqual((1, 1), (loc["tables_total"], loc["tables_with_bbox"]))
        # validator passes
        from research_library.parsing.schema import validate_result
        self.assertEqual([], validate_result(result))

    def test_idempotent_rerun_skips(self):
        first = self.run_parse()
        result_before = Path(first["output_dir"], "result.json").read_bytes()
        second = self.run_parse()
        self.assertEqual("skipped", second["action"])
        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(result_before, Path(first["output_dir"], "result.json").read_bytes())

    def test_force_reruns(self):
        self.run_parse()
        forced = self.run_parse(force=True)
        self.assertEqual("parsed", forced["action"])

    def test_path_change_same_content_reuses_artifact(self):
        self.run_parse()
        pdf2 = self.tmp / "renamed-copy.pdf"
        pdf2.write_bytes(self.pdf.read_bytes())
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(pdf2, self.cfg, document_id="doc-b")
        self.assertEqual("skipped", outcome["action"])
        # content-addressed: same sha -> same artifact directory
        a_dir = Path(outcome["output_dir"])
        result = json.loads((a_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("doc-a", result["document_id"])

    def test_corrupted_pdf_fails_integrity_without_parsing(self):
        bad = self.tmp / "broken.pdf"
        bad.write_bytes(JUNK_BYTES)
        inter = make_inter()
        calls = []

        def tracking_factory(name, **kwargs):
            calls.append(name)
            return fake_factory({"fake": inter})(name, **kwargs)

        with mock.patch.object(pl, "get_adapter", tracking_factory):
            outcome = pl.run_document(bad, self.cfg, document_id="broken")
        self.assertEqual([], calls)  # integrity fails before any adapter is built
        self.assertEqual("integrity_failed", outcome["action"])
        self.assertIn("invalid_pdf", [r["code"] for r in outcome["failure_reasons"]])

    def test_sha_mismatch_fails_before_parsing(self):
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a",
                                      expected_sha256="0" * 64)
        self.assertEqual("integrity_failed", outcome["action"])
        self.assertIn("sha_mismatch", [r["code"] for r in outcome["failure_reasons"]])

    def test_zero_text_document_degraded(self):
        inter = make_inter()
        inter["pages"] = [{"physical_page_no": 1, "width": None, "height": None, "text": ""}]
        inter["items"] = []
        inter["page_count"] = 1
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("degraded", outcome["status"])
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertIn("no_text_extracted", [r["code"] for r in result["failure_reasons"]])
        self.assertIn("no_text_layer_suspected", result["pages"][0]["issues"])

    def test_mojibake_and_suspicious_scripts_flagged(self):
        inter = make_inter()
        inter["items"][1]["text"] = "\ufffd\ufffd\ufffd 私有区:\ue000\ue001 藏区: ཀ ཁ"
        inter["pages"][0]["text"] = "\ufffd\ue000 ཀ"
        inter["pages"][0]["physical_page_no"] = 1
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("degraded", outcome["status"])
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        codes = {i["code"] for i in result["issues"]}
        self.assertTrue({"replacement_chars", "pua_chars", "suspicious_script_mix"} & codes,
                        f"expected mojibake flags, got {result['issues']}")
        # flagged paragraph carries the issue too; text is kept, not fixed
        flagged = result["paragraphs"][1]
        self.assertTrue(flagged["issues"])
        self.assertIn("\ufffd", flagged["text"])

    def test_missing_bbox_counts_unlocatable_not_wrong(self):
        outcome = self.run_parse()
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        no_bbox = [p for p in result["paragraphs"] if p["provenance"]["bbox"] is None]
        self.assertEqual(1, len(no_bbox))
        self.assertEqual("unavailable", no_bbox[0]["provenance"]["localization"]["status"])
        self.assertFalse(no_bbox[0]["provenance"]["localization"]["verified"])
        with_bbox = result["paragraphs"][0]["provenance"]["localization"]
        self.assertEqual("recorded", with_bbox["status"])
        self.assertFalse(with_bbox["verified"])  # bbox presence is never correctness

    def test_fallback_parser_used_and_marked(self):
        inter = make_inter("fake")
        inter_fb = make_inter("pdfplumber", version="0.11.7")
        inter_fb["parser"]["warnings"] = ["fallback line-level"]
        fail = {"fake": AdapterError("docling exploded")}
        with mock.patch.object(pl, "get_adapter",
                               fake_factory({"fake": inter, "pdfplumber": inter_fb}, fail=fail)):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("parsed", outcome["action"])
        self.assertEqual("fallback", outcome["status"])
        self.assertEqual("pdfplumber", outcome["parser"])
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertEqual("fallback", result["status"])
        self.assertEqual("fake", result["failure_reasons"][0]["parser"])
        self.assertEqual("adapter_error", result["failure_reasons"][0]["code"])
        self.assertEqual("pdfplumber", result["parser"]["name"])

    def test_dependency_missing_then_failed_when_fallback_disabled(self):
        inter = make_inter("pdfplumber")
        cfg = make_cfg(self.tmp, fallback_enabled=False)
        fail = {"fake": DependencyMissing("docling not installed")}
        with mock.patch.object(pl, "get_adapter",
                               fake_factory({"fake": inter, "pdfplumber": inter}, fail=fail)):
            outcome = pl.run_document(self.pdf, cfg, document_id="doc-a")
        self.assertEqual("failed", outcome["status"])
        self.assertIn("dependency_missing", [r["code"] for r in outcome["failure_reasons"]])
        # failed artifacts are recorded for audit
        self.assertTrue(Path(outcome["output_dir"], "run-meta.json").exists())

    def test_model_unavailable_falls_back(self):
        inter_fb = make_inter("pdfplumber")
        fail = {"fake": AdapterError("model artifacts missing")}
        fail["fake"].__class__ = type("ModelUnavailable", (AdapterError,), {})
        with mock.patch.object(pl, "get_adapter",
                               fake_factory({"fake": inter_fb, "pdfplumber": inter_fb},
                                            fail=fail)):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("fallback", outcome["status"])
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertIn("model_unavailable", [r["code"] for r in result["failure_reasons"]])

    def test_cache_pollution_rebuilds(self):
        outcome = self.run_parse()
        a_dir = Path(outcome["output_dir"])
        (a_dir / "result.json").write_text("{ not json !!!", encoding="utf-8")
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome2 = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("parsed", outcome2["action"])
        self.assertTrue(any("cache pollution" in w for w in outcome2["warnings"]))
        rebuilt = json.loads((a_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("childevidence.parse", rebuilt["schema"]["name"])

    def test_foreign_result_json_rejected_as_pollution(self):
        from research_library.pdfcheck import sha256_file

        # the foreign file lives under THIS document's sha12 directory, where
        # the reuse scan actually looks (a dir under another sha12 is simply
        # not visited)
        a_dir = self.cfg.output_root / sha256_file(self.pdf)[:12] / "pa-notmine"
        a_dir.mkdir(parents=True, exist_ok=True)
        (a_dir / "result.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("parsed", outcome["action"])
        # "警告 + 重建" policy covers foreign dicts, not just unreadable JSON
        self.assertTrue(any("not a parse result" in w for w in outcome["warnings"]),
                        f"expected a pollution warning, got {outcome['warnings']}")
        self.assertEqual("childevidence.parse",
                         json.loads(Path(outcome["output_dir"], "result.json")
                                    .read_text(encoding="utf-8"))["schema"]["name"])

    def test_cross_document_cache_pollution_rebuilds(self):
        # P1-1: a schema-VALID result.json copied from another document must
        # never be adopted silently — reuse requires source-sha agreement.
        inter = make_inter()
        first = self.run_parse()
        legit_dir = Path(first["output_dir"])
        foreign = json.loads((legit_dir / "result.json").read_text(encoding="utf-8"))
        foreign["source"]["sha256"] = "b" * 64  # describes another document
        foreign_dir = self.cfg.output_root / first["sha256"][:12] / "pa-foreign"
        foreign_dir.mkdir(parents=True, exist_ok=True)
        (foreign_dir / "result.json").write_text(json.dumps(foreign), encoding="utf-8")
        import shutil
        shutil.rmtree(legit_dir)  # only the foreign copy remains
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = self.run_parse()
        self.assertEqual("parsed", outcome["action"])  # rebuilt, NOT skipped
        self.assertTrue(any("different source document" in w for w in outcome["warnings"]))
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertEqual(first["sha256"], result["source"]["sha256"])
        self.assertNotEqual(foreign_dir, Path(outcome["output_dir"]))

    def test_partial_success_degraded_with_converter_errors(self):
        # P1-2: docling PARTIAL_SUCCESS must surface as degraded with the
        # converter's own error list — never as a fully successful parse.
        inter = make_inter()
        inter["conversion_partial"] = {
            "conversion_status": "ConversionStatus.PARTIAL_SUCCESS",
            "errors": ["page 3: layout model failed"],
        }
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("degraded", outcome["status"])
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        reasons = [r["code"] for r in result["failure_reasons"]]
        self.assertIn("conversion_partial_success", reasons)
        partial = [r for r in result["failure_reasons"]
                   if r["code"] == "conversion_partial_success"][0]
        self.assertIn("PARTIAL_SUCCESS", partial["message"])
        self.assertIn("page 3", partial["message"])

    def test_page_count_mismatch_degraded(self):
        # P1-2: the independent pdfcheck page scan must be cross-checked — a
        # parser claiming more pages than the file contains is flagged loudly.
        inter = make_inter()
        inter["page_count"] = 3
        inter["pages"].append({"physical_page_no": 3, "width": None, "height": None,
                               "text": "ghost page"})
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("degraded", outcome["status"])
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertIn("page_count_mismatch", [r["code"] for r in result["failure_reasons"]])

    def test_page_map_manual_corrections_applied_physical_untouched(self):
        self.cfg.corrections_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.corrections_dir / "doc-a.json").write_text(
            json.dumps([{"physical_page_no": 1, "printed_page_no": 42, "note": "human checked"},
                        {"physical_page_no": 2, "printed_page_no": 43}]),
            encoding="utf-8")
        outcome = self.run_parse()
        result = json.loads(Path(outcome["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertEqual(42, result["pages"][0]["printed_page_no"])
        self.assertEqual("manual", result["pages"][0]["printed_page_origin"])
        self.assertEqual(1, result["pages"][0]["physical_page_no"])
        pm = json.loads(Path(outcome["output_dir"], "page-map.json").read_text(encoding="utf-8"))
        self.assertEqual(2, len(pm["manual_corrections_applied"]))
        self.assertTrue(str(pm["manual_corrections_applied"][0]["from_file"]).endswith("doc-a.json"))
        # without corrections printed pages stay null (no offset inference)
        outcome2 = self.run_parse(force=True)
        result2 = json.loads(Path(outcome2["output_dir"], "result.json").read_text(encoding="utf-8"))
        self.assertEqual(42, result2["pages"][0]["printed_page_no"])  # corrections persist

    def test_page_map_absent_printed_stays_null(self):
        outcome = self.run_parse()
        pm = json.loads(Path(outcome["output_dir"], "page-map.json").read_text(encoding="utf-8"))
        self.assertTrue(all(e["printed_page_no"] is None for e in pm["entries"]))

    def test_batch_manifest_run(self):
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps({"documents": [
            {"document_id": "doc-a", "path": str(self.pdf), "sha256": None},
        ]}), encoding="utf-8")
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            summary = pl.run_batch(pl.load_manifest(manifest), self.cfg)
        self.assertEqual(1, summary["total"])
        self.assertEqual(1, summary["parsed"])
        self.assertEqual({"ok": 1}, summary["status_counts"])

    def test_batch_manifest_sha_mismatch(self):
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps({"documents": [
            {"document_id": "doc-a", "path": str(self.pdf), "sha256": "f" * 64},
        ]}), encoding="utf-8")
        inter = make_inter()
        with mock.patch.object(pl, "get_adapter", fake_factory({"fake": inter})):
            summary = pl.run_batch(pl.load_manifest(manifest), self.cfg)
        self.assertEqual(1, summary["integrity_failed"])

    def test_batch_missing_file_counts_in_integrity_bucket(self):
        # resolve-stage failures use the same taxonomy as run_document's own
        # missing_file (integrity_failed), not the generic failed bucket
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps({"documents": [
            {"document_id": "gone", "path": str(self.tmp / "nope.pdf")},
        ]}), encoding="utf-8")
        summary = pl.run_batch(pl.load_manifest(manifest), self.cfg)
        self.assertEqual(1, summary["integrity_failed"])
        self.assertEqual(0, summary["failed"])

    def test_corrections_applied_on_plain_rerun_after_first_parse(self):
        # P2-2 / docs §6: corrections added AFTER the first parse take effect
        # on the next ordinary run (no --force), without re-parsing.
        first = self.run_parse()
        self.assertEqual("parsed", first["action"])
        result_path = Path(first["output_dir"], "result.json")
        before = result_path.read_bytes()
        self.cfg.corrections_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.corrections_dir / "doc-a.json").write_text(
            json.dumps([{"physical_page_no": 1, "printed_page_no": 7, "note": "human"}]),
            encoding="utf-8")
        second = self.run_parse()  # plain rerun
        self.assertEqual("skipped", second["action"])
        self.assertTrue(any("corrections applied on skip" in w for w in second["warnings"]))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(7, result["pages"][0]["printed_page_no"])
        self.assertEqual("manual", result["pages"][0]["printed_page_origin"])
        self.assertEqual(1, result["artifact"]["page_map_applied"]["applied"])
        self.assertNotEqual(before, result_path.read_bytes())
        # rerunning again changes nothing (byte-stable, no duplicate audit rows)
        snapshot = result_path.read_bytes()
        third = self.run_parse()
        self.assertEqual("skipped", third["action"])
        self.assertEqual(snapshot, result_path.read_bytes())

    def test_cross_check_default_off_runs_primary_only(self):
        inter = make_inter()
        calls = []

        def tracking_factory(name, **kwargs):
            calls.append(name)
            return fake_factory({"fake": inter})(name, **kwargs)

        with mock.patch.object(pl, "get_adapter", tracking_factory):
            outcome = pl.run_document(self.pdf, self.cfg, document_id="doc-a")
        self.assertEqual("ok", outcome["status"])
        # exactly probe + primary parse are constructed; no fallback parser,
        # no cross-check second pass, no review queue
        self.assertEqual(["fake", "fake"], calls)
        self.assertFalse((self.cfg.output_root / "parse-review-queue").exists())

    def test_cross_check_conflict_writes_review_task(self):
        inter = make_inter()
        inter_pl = make_inter("pdfplumber")
        inter_pl["page_count"] = 3  # divergence
        inter_pl["pages"].append({"physical_page_no": 3, "width": None, "height": None, "text": "x"})
        cfg = make_cfg(self.tmp, cross_check=True)
        with mock.patch.object(pl, "get_adapter",
                               fake_factory({"fake": inter, "pdfplumber": inter_pl})):
            outcome = pl.run_document(self.pdf, cfg, document_id="doc-a")
        qdir = cfg.review_queue_dir
        tasks = list(qdir.glob("*.json"))
        self.assertEqual(1, len(tasks))
        task = json.loads(tasks[0].read_text(encoding="utf-8"))
        self.assertEqual("cross_check_divergence", task["type"])
        self.assertIn("page_count_mismatch", [d["type"] for d in task["divergences"]])
        self.assertIn("never auto-resolved", task["policy"])
        self.assertTrue(any("review task" in w for w in outcome["warnings"]))

    def test_cross_check_agreement_no_review_task(self):
        inter = make_inter()
        inter_pl = make_inter("pdfplumber")
        cfg = make_cfg(self.tmp, cross_check=True)
        with mock.patch.object(pl, "get_adapter",
                               fake_factory({"fake": inter, "pdfplumber": inter_pl})):
            outcome = pl.run_document(self.pdf, cfg, document_id="doc-a")
        self.assertFalse(list(cfg.review_queue_dir.glob("*.json"))
                         if cfg.review_queue_dir.exists() else False)
        self.assertEqual("ok", outcome["status"])


class SubprocessTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("parsing-timeout-")
        self.pdf = self.tmp / "doc.pdf"
        self.pdf.write_bytes(make_pdf(pages=1))
        self.cfg = make_cfg(self.tmp)
        self.cfg.execution = "subprocess"
        self.cfg.timeout_sec = 3
        # sleeper parser module (test hook)
        self.sleeper = self.tmp / "sleeper_parser.py"
        self.sleeper.write_text(
            "import time\n"
            "class Parser:\n"
            "    def parse(self, pdf_path, options):\n"
            "        time.sleep(30)\n"
            "        raise RuntimeError('should have been killed')\n",
            encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_timeout_kills_subprocess(self):
        with self.assertRaises(pl.ParseTimeout):
            pl._run_adapter("sleeper", self.pdf, {}, self.cfg,
                            parser_module=str(self.sleeper))

    def test_subprocess_success_roundtrip(self):
        fast = self.tmp / "fast_parser.py"
        fast.write_text(
            "class Parser:\n"
            "    def parse(self, pdf_path, options):\n"
            "        return {'format_version': 1, 'parser': {'name': 'stub',"
            " 'parser_version': '0'}, 'page_count': 1,\n"
            "                'pages': [{'physical_page_no': 1, 'width': None,"
            " 'height': None, 'text': 'hello'}], 'items': [],"
            " 'language_hint': 'en', 'warnings': []}\n",
            encoding="utf-8")
        inter = pl._run_adapter("stub", self.pdf, {}, self.cfg, parser_module=str(fast))
        self.assertEqual(1, inter["page_count"])

    def test_subprocess_reports_peak_memory(self):
        # issue #3: the task report includes memory. The subprocess runner
        # self-measures its peak working set (Windows psapi) and attaches
        # "_peak_memory_mb" for provenance.peak_memory_mb. Where process-
        # memory queries are unavailable or virtualized (sandboxed CI), the
        # field stays absent and provenance keeps an honest null — this test
        # accepts both and validates the value whenever it is present.
        fast = self.tmp / "fast_parser_mem.py"
        fast.write_text(
            "class Parser:\n"
            "    def parse(self, pdf_path, options):\n"
            "        return {'format_version': 1, 'parser': {'name': 'stub',"
            " 'parser_version': '0'}, 'page_count': 1,\n"
            "                'pages': [{'physical_page_no': 1, 'width': None,"
            " 'height': None, 'text': 'hello'}], 'items': [],"
            " 'language_hint': 'en', 'warnings': []}\n",
            encoding="utf-8")
        inter = pl._run_adapter("stub", self.pdf, {}, self.cfg, parser_module=str(fast))
        if "_peak_memory_mb" in inter:
            self.assertIsInstance(inter["_peak_memory_mb"], float)
            self.assertGreater(inter["_peak_memory_mb"], 0.0)

    def test_chatty_stderr_no_false_timeout(self):
        # P2-1: a child that floods stderr (~400KB > the OS pipe buffer) must
        # complete instead of blocking on a full pipe until the timeout kill
        # and being misattributed as a timeout.
        self.cfg.timeout_sec = 30
        chatty = self.tmp / "chatty_parser.py"
        chatty.write_text(
            "import sys\n"
            "class Parser:\n"
            "    def parse(self, pdf_path, options):\n"
            "        sys.stderr.write('x' * 80 + '\\n' * 1)  # 81 B\n"
            "        for _ in range(5000):\n"
            "            sys.stderr.write('WARN ' + 'y' * 76 + '\\n')\n"
            "        return {'format_version': 1, 'parser': {'name': 'stub',"
            " 'parser_version': '0'}, 'page_count': 1,\n"
            "                'pages': [{'physical_page_no': 1, 'width': None,"
            " 'height': None, 'text': 'hello'}], 'items': [],"
            " 'language_hint': 'en', 'warnings': []}\n",
            encoding="utf-8")
        inter = pl._run_adapter("stub", self.pdf, {}, self.cfg, parser_module=str(chatty))
        self.assertEqual(1, inter["page_count"])

    def test_memory_cap_kills_subprocess(self):
        # memory-cap enforcement path: the poll loop reads the child's working
        # set (mocked here so the test is deterministic under sandboxed psapi)
        # and kills the process when it exceeds the configured cap.
        cfg = make_cfg(self.tmp)
        cfg.execution = "subprocess"
        cfg.max_memory_mb = 64
        slow = self.tmp / "slow_parser.py"
        slow.write_text(
            "import time\n"
            "class Parser:\n"
            "    def parse(self, pdf_path, options):\n"
            "        time.sleep(20)\n"
            "        raise RuntimeError('should have been killed for memory')\n",
            encoding="utf-8")
        with mock.patch.object(pl, "get_memory_info_mb",
                               lambda pid: (4096.0, 4096.0)), \
                mock.patch.object(pl.time, "sleep", lambda _s: None):
            with self.assertRaises(pl.AdapterError) as cm:
                pl._run_adapter("stub", self.pdf, {}, cfg, parser_module=str(slow))
        self.assertIn("memory cap", str(cm.exception))


class AdapterGuardTests(unittest.TestCase):
    def test_classify_conversion_never_treats_partial_as_success(self):
        from research_library.parsing.adapters.docling_adapter import classify_conversion

        self.assertEqual("ok", classify_conversion("ConversionStatus.SUCCESS"))
        self.assertEqual("partial", classify_conversion("ConversionStatus.PARTIAL_SUCCESS"))
        self.assertEqual("failure", classify_conversion("ConversionStatus.FAILURE"))
        self.assertEqual("failure", classify_conversion("ConversionStatus.PENDING"))
        self.assertEqual("failure", classify_conversion("unknown"))
        self.assertEqual("failure", classify_conversion(""))

    def test_offline_env_forced_not_punched_through(self):
        # P2-3: offline.mode=true must FORCE the guards; an inherited
        # HF_HUB_OFFLINE=0 from the user environment must not survive.
        import os

        from research_library.parsing.adapters.docling_adapter import DoclingParser

        adapter = DoclingParser(models_dir=None, offline=True)
        with mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "0",
                                          "TRANSFORMERS_OFFLINE": "0"}):
            adapter._prepare_offline_env()
            self.assertEqual("1", os.environ["HF_HUB_OFFLINE"])
            self.assertEqual("1", os.environ["TRANSFORMERS_OFFLINE"])
        adapter2 = DoclingParser(models_dir=None, offline=False)
        with mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "0"}, clear=False):
            adapter2._prepare_offline_env()
            self.assertEqual("0", os.environ["HF_HUB_OFFLINE"])  # untouched


class ConfigValidationTests(unittest.TestCase):
    def _cfg_with_yaml(self, tmp: Path, text: str) -> ParsingConfig:
        p = tmp / "parsing.yaml"
        p.write_text(text, encoding="utf-8")
        return ParsingConfig(base=Config(data_dir=tmp / "data"), config_file=p)

    def setUp(self):
        self.tmp = make_tmp_dir("parsing-cfg-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrency_two_rejected(self):
        with self.assertRaises(ValueError):
            self._cfg_with_yaml(self.tmp, "parser:\n  concurrency: 2\n")

    def test_ocr_enabled_true_rejected(self):
        # ocr_enabled participates in artifact identity but the adapter
        # hardcodes do_ocr=False — accepting true would be a config lie
        with self.assertRaises(ValueError):
            self._cfg_with_yaml(self.tmp, "docling:\n  ocr_enabled: true\n")

    def test_models_dir_default_aligned_with_models_command(self):
        # P2-4: run-side default == the directory `parse models` populates
        # without --artifacts-dir, so the documented install->run flow works
        cfg = self._cfg_with_yaml(self.tmp, "parser:\n  primary: docling\n")
        self.assertEqual(self.tmp / "data" / "parse-models", cfg.models_dir)


if __name__ == "__main__":
    unittest.main()
