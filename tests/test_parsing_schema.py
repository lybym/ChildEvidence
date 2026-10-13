"""Unit tests for the ce03-parse schema validator, CID heuristics and page maps."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from research_library.parsing import cidcheck
from research_library.parsing.adapters.normalize import normalize_intermediate, options_hash
from research_library.parsing.page_map import (
    apply_corrections,
    empty_page_map,
    load_corrections,
)
from research_library.parsing.schema import compute_localization_summary, validate_result


def minimal_doc(**over) -> dict:
    """A minimal VALID normalized result."""
    doc = {
        "schema": {"name": "childevidence.parse", "version": 1},
        "document_id": "d1",
        "source": {"path": "p.pdf", "file_name": "p.pdf", "size_bytes": 1,
                   "sha256": "a" * 64,
                   "integrity": {"header_ok": True, "eof_ok": True, "validated": True}},
        "parser": {"name": "fake", "parser_version": "1.0", "model_versions": {},
                   "dependency_versions": {}, "options": {}, "options_hash": "x"},
        "status": "ok",
        "failure_reasons": [],
        "warnings": [],
        "issues": [],
        "language": "en",
        "page_count": 1,
        "pages": [{"physical_page_no": 1, "printed_page_no": None,
                   "printed_page_origin": None, "width": None, "height": None,
                   "text_present": True, "char_count": 5, "issues": []}],
        "sections": [],
        "paragraphs": [{
            "paragraph_id": "par-0001", "kind": "paragraph", "text": "hello",
            "reading_order_index": 1, "section_id": None, "physical_page_no": 1,
            "printed_page_no": None, "char_span": None, "issues": [],
            "provenance": {"origin": "x", "bbox": [0, 0, 1, 1],
                           "bbox_space": "pdf_points_y_down", "page_size": None,
                           "char_span_space": None,
                           "localization": {"status": "recorded", "verified": False}},
        }],
        "tables": [],
        "references": {"supported_by_parser": False, "items": None, "note": "unsupported"},
        "localization_summary": compute_localization_summary({"paragraphs": [], "tables": []}),
        "provenance": {"produced_at_utc": "t", "duration_sec": 1.0, "peak_memory_mb": None,
                       "transform_chain": [], "normalize_version": "childevidence.parse/1"},
        "artifact": {"artifact_id": None, "output_dir": None, "page_map_applied": None},
    }
    doc["localization_summary"] = compute_localization_summary(doc)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(doc.get(k), dict):
            doc[k].update(v)
        else:
            doc[k] = v
    return doc


class ValidatorTests(unittest.TestCase):
    def test_minimal_valid(self):
        self.assertEqual([], validate_result(minimal_doc()))

    def test_not_a_dict(self):
        self.assertTrue(validate_result(["nope"]))

    def test_bad_status(self):
        doc = minimal_doc(status="amazing")
        self.assertTrue(any("status" in e for e in validate_result(doc)))

    def test_bad_sha(self):
        doc = minimal_doc()
        doc["source"]["sha256"] = "xyz"
        self.assertTrue(any("sha256" in e for e in validate_result(doc)))

    def test_pages_length_mismatch(self):
        doc = minimal_doc(page_count=3)
        self.assertTrue(any("pages" in e for e in validate_result(doc)))

    def test_non_sequential_physical_pages_rejected(self):
        doc = minimal_doc()
        doc["pages"][0]["physical_page_no"] = 7
        self.assertTrue(any("physical_page_no" in e for e in validate_result(doc)))

    def test_printed_page_requires_manual_origin(self):
        doc = minimal_doc()
        doc["pages"][0]["printed_page_no"] = 5
        self.assertTrue(any("printed_page_origin" in e for e in validate_result(doc)))
        doc["pages"][0]["printed_page_origin"] = "manual"
        self.assertEqual([], validate_result(doc))

    def test_bbox_without_recorded_status_rejected(self):
        doc = minimal_doc()
        doc["paragraphs"][0]["provenance"]["localization"]["status"] = "unavailable"
        self.assertTrue(validate_result(doc))

    def test_bbox_claiming_verified_rejected(self):
        doc = minimal_doc()
        doc["paragraphs"][0]["provenance"]["localization"]["verified"] = True
        self.assertTrue(any("verified" in e for e in validate_result(doc)))

    def test_missing_bbox_requires_unavailable(self):
        doc = minimal_doc()
        doc["paragraphs"][0]["provenance"]["bbox"] = None
        self.assertTrue(validate_result(doc))
        doc["paragraphs"][0]["provenance"]["localization"]["status"] = "unavailable"
        self.assertEqual([], validate_result(doc))

    def test_paragraph_page_reference(self):
        doc = minimal_doc()
        doc["paragraphs"][0]["physical_page_no"] = 9
        self.assertTrue(any("physical_page_no" in e for e in validate_result(doc)))

    def test_failed_status_requires_reasons(self):
        doc = minimal_doc(status="failed")
        self.assertTrue(validate_result(doc))
        doc["failure_reasons"] = [{"stage": "s", "code": "c", "message": "m"}]
        self.assertEqual([], validate_result(doc))

    def test_accuracy_must_be_null_in_parse_layer(self):
        doc = minimal_doc()
        doc["localization_summary"]["localization_accuracy"] = 0.95
        self.assertTrue(any("localization_accuracy" in e for e in validate_result(doc)))

    def test_presence_rate_consistency(self):
        doc = minimal_doc()
        doc["localization_summary"]["bbox_presence_rate"] = 0.99
        self.assertTrue(any("bbox_presence_rate" in e for e in validate_result(doc)))

    def test_references_null_requires_note(self):
        doc = minimal_doc()
        doc["references"] = {"supported_by_parser": False, "items": None, "note": None}
        self.assertTrue(any("references" in e for e in validate_result(doc)))

    def test_ragged_table_needs_flag(self):
        doc = minimal_doc()
        doc["tables"] = [{
            "table_id": "t1", "reading_order_index": 2, "physical_page_no": 1,
            "printed_page_no": None, "n_rows": 2, "n_cols": 2,
            "cells": [["a", "b"], ["c"]], "extraction_method": "m", "issues": [],
            "provenance": {"origin": "x", "bbox": None, "bbox_space": None,
                           "page_size": None, "char_span_space": None,
                           "localization": {"status": "unavailable", "verified": False}},
        }]
        self.assertTrue(any("ragged" in e for e in validate_result(doc)))
        doc["tables"][0]["issues"] = ["table_ragged_grid"]
        self.assertEqual([], validate_result(doc))


def _valid_table(**prov_over) -> dict:
    return {
        "table_id": "t1", "reading_order_index": 2, "physical_page_no": 1,
        "printed_page_no": None, "n_rows": 1, "n_cols": 2,
        "cells": [["a", "b"]], "extraction_method": "m", "issues": [],
        "provenance": {"origin": "x", "bbox": [0, 0, 10, 10],
                       "bbox_space": "pdf_points_y_down", "page_size": None,
                       "char_span_space": None,
                       "localization": {"status": "recorded", "verified": False},
                       **prov_over},
    }


class TableValidatorParityTests(unittest.TestCase):
    """Tables get the same page-reference and localization discipline as
    paragraphs (validator-as-contract parity, review round 1 §5)."""

    def test_valid_table_passes(self):
        doc = minimal_doc()
        doc["tables"] = [_valid_table()]
        self.assertEqual([], validate_result(doc))

    def test_table_page_reference_enforced(self):
        doc = minimal_doc()
        tbl = _valid_table()
        tbl["physical_page_no"] = 9  # document has only page 1
        doc["tables"] = [tbl]
        self.assertTrue(any("physical_page_no" in e for e in validate_result(doc)))

    def test_table_bbox_claiming_verified_rejected(self):
        doc = minimal_doc()
        doc["tables"] = [_valid_table(
            localization={"status": "recorded", "verified": True})]
        self.assertTrue(any("verified" in e for e in validate_result(doc)))

    def test_table_bbox_without_recorded_status_rejected(self):
        doc = minimal_doc()
        doc["tables"] = [_valid_table(
            localization={"status": "unavailable", "verified": False})]
        self.assertTrue(any("recorded" in e for e in validate_result(doc)))

    def test_table_malformed_bbox_rejected(self):
        doc = minimal_doc()
        doc["tables"] = [_valid_table(bbox=[1, 2, 3])]
        self.assertTrue(any("bbox" in e for e in validate_result(doc)))

    def test_table_missing_bbox_requires_unavailable(self):
        doc = minimal_doc()
        doc["tables"] = [_valid_table(bbox=None,
                                      localization={"status": "recorded", "verified": False})]
        self.assertTrue(any("unavailable" in e for e in validate_result(doc)))


class CidcheckTests(unittest.TestCase):
    def test_replacement_chars(self):
        # below the ratio-noise threshold (len<200) any replacement char flags
        self.assertIn("replacement_chars", cidcheck.page_text_issues("ok" * 50 + "\ufffd"))
        self.assertIn("replacement_chars",
                      cidcheck.page_text_issues("ok" * 1000 + "\ufffd" * 20))

    def test_pua_chars(self):
        self.assertIn("pua_chars", cidcheck.page_text_issues("ok" * 50 + "\ue000\ue001"))
        self.assertIn("pua_chars", cidcheck.page_text_issues("ok" * 1000 + "\ue000" * 30))

    def test_low_ratio_noise_not_flagged(self):
        # a single stray replacement char in a long clean page stays below the
        # conservative flag threshold (heuristic, not a verdict)
        self.assertEqual([], cidcheck.page_text_issues("ok" * 1000 + "\ufffd"))

    def test_tibetan_range_flagged(self):
        self.assertIn("suspicious_script_mix", cidcheck.page_text_issues("ok" * 100 + "ཀ"))

    def test_clean_text(self):
        self.assertEqual([], cidcheck.page_text_issues("A clean English sentence. " * 10))

    def test_empty_page(self):
        self.assertEqual(["page_no_text"], cidcheck.page_text_issues(""))

    def test_document_language(self):
        self.assertEqual("zh", cidcheck.document_language(["这是一段中文文本内容，涉及儿童发展研究。"]))
        self.assertEqual("en", cidcheck.document_language(["This is an English abstract about children."]))
        self.assertEqual("unknown", cidcheck.document_language(["12345"]))

    def test_document_issues_aggregates(self):
        out = cidcheck.document_issues([["replacement_chars"], ["replacement_chars"]], 5000)
        self.assertEqual(1, len(out))
        self.assertEqual(2, out[0]["pages_affected"])
        # page_no_text is carried by pages[].text_present, not document issues
        self.assertEqual(0, len(cidcheck.document_issues([["page_no_text"]], 5000)))
        self.assertTrue(any(i["code"] == "no_text_extracted"
                            for i in cidcheck.document_issues([[]], 10)))


class PageMapTests(unittest.TestCase):
    def test_empty_map_all_null(self):
        pm = empty_page_map(3)
        self.assertEqual(3, len(pm["entries"]))
        self.assertTrue(all(e["printed_page_no"] is None for e in pm["entries"]))

    def test_corrections_file_validation(self):
        tmp = Path(__file__).parent.parent / ".tmp-test" / f"pm-{self.id()}.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps([{"physical_page_no": 1, "printed_page_no": 3}]), encoding="utf-8")
        self.assertEqual(1, len(load_corrections(tmp)))
        tmp.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_corrections(tmp)
        tmp.write_text(json.dumps([{"physical_page_no": "x"}]), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_corrections(tmp)
        tmp.unlink()

    def test_apply_corrections_auditable(self):
        pm = empty_page_map(2)
        pm2 = apply_corrections(pm, [{"physical_page_no": 2, "printed_page_no": None}],
                                source_file="c.json")
        self.assertEqual(None, pm2["entries"][1]["printed_page_no"])
        self.assertEqual("manual", pm2["entries"][1]["printed_page_origin"])
        self.assertEqual(1, len(pm2["manual_corrections_applied"]))
        self.assertEqual("c.json", pm2["manual_corrections_applied"][0]["from_file"])
        with self.assertRaises(ValueError):
            apply_corrections(pm, [{"physical_page_no": 99, "printed_page_no": 1}])

    def test_no_offset_inference_anywhere(self):
        # printed stays null unless a human file says otherwise; policy string present
        pm = empty_page_map(5)
        self.assertTrue(all(e["printed_page_no"] is None and e["printed_page_origin"] is None
                            for e in pm["entries"]))
        self.assertIn("no fixed-offset inference", pm["policy"])


class NormalizeOptionsTests(unittest.TestCase):
    def test_options_hash_stable_and_sensitive(self):
        a = options_hash({"x": 1, "y": "z"})
        b = options_hash({"y": "z", "x": 1})
        c = options_hash({"x": 2, "y": "z"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(16, len(a))

    def test_normalize_rejects_wrong_format_version(self):
        with self.assertRaises(ValueError):
            normalize_intermediate({"format_version": 999}, source={}, document_id=None,
                                   options={}, status="ok")


if __name__ == "__main__":
    unittest.main()
