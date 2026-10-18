"""Offline synthetic tests for the Evidence/Claim model (Issue #14).

Covers the five acceptance criteria of Issue #14:

1. expressiveness: one Work with several RQs / source versions, one study in
   several reports, contradictory evidence and missing fields — with evidence
   counted per distinct study (no double counting);
2. strict rejection: illegal extra fields, numeric boundaries, duplicate keys,
   wrong references and wrong versions — including a direct proof that the
   partial governance validator would silently ignore them;
3. fresh database, upgrade path, unchanged legacy rows/IDs, and contract
   loading from a relocated (installed) package copy;
4. the recorded Issue #10 pilot run mapped with honest unknowns;
5. reproducible commands via the ``research evidence`` CLI.

All fixtures are synthetic; no network, no model calls, no real publication
content, and the production database under data/ is never touched.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from helpers import make_tmp_dir

from research_library import db, evidence as ev
from research_library import governance
from research_library.astra_pilot import ISSUE_URL as PILOT_ISSUE_URL
from research_library.cli import main as cli_main

SV = "ce.evidence/1"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_PILOT = "9c" * 32  # synthetic stand-in for the run's recorded PDF sha256


def source_version_record(**changes):
    record = {
        "schema_version": SV,
        "version_id": "sv-test-1",
        "work_id": "lt-fixture01",
        "study_id": None,
        "source_kind": "journal_article",
        "original_version": "published_version",
        "original_sha256": DIGEST_A,
        "parsed_sha256": None,
        "parsed_format": None,
        "locator_status": "unknown",
        "origin": "manual",
        "origin_ref": None,
        "notes": None,
    }
    record.update(changes)
    return record


def rq_record(**changes):
    record = {"schema_version": SV, "rq_id": "rq-test-1", "statement": "Does X help Y?",
              "version": 1, "status": "active", "notes": None}
    record.update(changes)
    return record


class EvidenceModelTestsBase(unittest.TestCase):
    """Common fixture: temp workspace with a library DB and one legacy Work."""

    def setUp(self):
        self.root = make_tmp_dir("ev-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.db_path = self.root / "research-library" / "library.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.conn.execute(
            "INSERT INTO works (internal_id, title, pdf_version, sha256, record_status)"
            " VALUES (?, ?, ?, ?, 'ingested')",
            ("lt-fixture01", "Fixture Work (synthetic, not a real publication)",
             "published_version", DIGEST_A))
        self.conn.commit()

    def insert(self, kind, record, conn=None):
        return ev.insert_record(conn or self.conn, kind, record)


class FreshDatabaseTests(unittest.TestCase):
    """验收 #3: a fresh database gets the complete additive schema."""

    def test_connect_creates_all_evidence_tables(self):
        root = make_tmp_dir("ev-fresh-")
        self.addCleanup(shutil.rmtree, root, True)
        with closing(db.connect(root / "library.sqlite")) as conn:
            present = ev.evidence_tables_present(conn)
            self.assertEqual(sorted(present), sorted(ev.EVIDENCE_TABLES))
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(works)")}
            self.assertIn("internal_id", columns)

    def test_works_schema_untouched(self):
        root = make_tmp_dir("ev-fresh2-")
        self.addCleanup(shutil.rmtree, root, True)
        with closing(db.connect(root / "library.sqlite")) as conn:
            names = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            self.assertIn("works", names)
            # no evidence column ever leaked into the bibliographic table
            work_cols = {row[1] for row in conn.execute("PRAGMA table_info(works)")}
            self.assertNotIn("locator_status", work_cols)


class UpgradeCompatibilityTests(unittest.TestCase):
    """验收 #3: pre-evidence databases upgrade additively; legacy rows and IDs
    stay byte-identical; the recorded migration leaves a restorable backup."""

    def setUp(self):
        self.root = make_tmp_dir("ev-upg-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.db_path = self.root / "library.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(db.BASE_SCHEMA)  # pre-evidence schema (no evidence tables)
        conn.execute("INSERT INTO works (internal_id, title, record_status) VALUES (?, ?, ?)",
                     ("lt-legacy00001", "Legacy Work (synthetic)", "ingested"))
        conn.execute("INSERT INTO download_log (internal_id, url, attempt, status, at)"
                     " VALUES (?, ?, 1, 'ok', '2026-10-13T00:00:00Z')",
                     ("lt-legacy00001", "https://example.invalid/legacy.pdf"))
        conn.commit()
        self.legacy_works = [dict(r) for r in conn.execute("SELECT * FROM works")]
        self.legacy_logs = [dict(r) for r in conn.execute("SELECT * FROM download_log")]
        conn.close()
        probe = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(ev.evidence_tables_present(probe), [])
        finally:
            probe.close()

    def rows_of(self, path, table):
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
        finally:
            conn.close()

    def test_migrate_with_backup_preserves_legacy_rows(self):
        result = ev.migrate_with_backup(self.db_path)
        self.assertEqual(result["integrity"], "ok")
        self.assertIsNotNone(result["backup"])
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(sorted(result["evidence_tables"]), sorted(ev.EVIDENCE_TABLES))
        self.assertEqual(self.rows_of(self.db_path, "works"), self.legacy_works)
        self.assertEqual(self.rows_of(self.db_path, "download_log"), self.legacy_logs)
        # old internal_id still resolves and the backup restores the same row
        backup_rows = self.rows_of(result["backup"], "works")
        self.assertEqual(backup_rows, self.legacy_works)
        # converges with the normal connect() path afterwards (additive, idempotent)
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(sorted(ev.evidence_tables_present(conn)),
                             sorted(ev.EVIDENCE_TABLES))
            self.assertEqual([dict(r) for r in conn.execute("SELECT * FROM works")],
                             self.legacy_works)

    def test_fresh_database_migration_needs_no_backup(self):
        fresh = self.root / "fresh" / "library.sqlite"
        fresh.parent.mkdir(parents=True, exist_ok=True)
        result = ev.migrate_with_backup(fresh)
        self.assertIsNone(result["backup"])
        self.assertEqual(result["integrity"], "ok")


class StrictRejectionTests(EvidenceModelTestsBase):
    """验收 #2: illegal extra fields, numeric boundaries, duplicate keys, wrong
    references and wrong versions are rejected — never silently passed."""

    def test_extra_field_rejected(self):
        bad = source_version_record(sneaky_extra=1)
        self.assertTrue(ev.validate_record("source_version", bad))

    def test_wrong_envelope_version_rejected(self):
        bad = source_version_record(schema_version="ce.evidence/2")
        errors = ev.validate_record("source_version", bad)
        self.assertTrue(any("const" in e for e in errors))

    def test_numeric_boundaries_rejected(self):
        bad_rq = rq_record(version=0)
        self.assertTrue(any("minimum" in e for e in ev.validate_record("research_question", bad_rq)))
        bad_rq2 = rq_record(version=1000001)
        self.assertTrue(any("maximum" in e for e in ev.validate_record("research_question", bad_rq2)))
        bad_finding = {
            "schema_version": SV, "finding_id": "f-test-1", "study_id": "st-test-1",
            "source_version_id": "sv-test-1", "statement": "s",
            "attributes": {"sample_size": 0},
        }
        self.assertTrue(any("minimum" in e for e in ev.validate_record("finding", bad_finding)))
        bad_finding["attributes"] = {"sample_size": 1000000001}
        self.assertTrue(any("maximum" in e for e in ev.validate_record("finding", bad_finding)))

    def test_statement_length_boundary_rejected(self):
        bad = rq_record(statement="x" * 2001)
        self.assertTrue(any("maxLength" in e for e in ev.validate_record("research_question", bad)))

    def test_governance_validator_would_silently_pass(self):
        """Direct proof that the partial validator is not enough (验收 #2)."""
        schema = ev.load_schema("source_version")
        sneaky = source_version_record(sneaky_extra={"nested": True})
        self.assertEqual(governance.validate(sneaky, schema), [])
        self.assertTrue(ev.validate_record("source_version", sneaky))
        schema_finding = ev.load_schema("finding")
        out_of_bounds = {
            "schema_version": SV, "finding_id": "f-test-1", "study_id": "st-test-1",
            "source_version_id": "sv-test-1", "statement": "s",
            "attributes": {"sample_size": -5},
        }
        self.assertEqual(governance.validate(out_of_bounds, schema_finding), [])
        self.assertTrue(ev.validate_record("finding", out_of_bounds))

    def test_duplicate_relation_pair_rejected(self):
        sv = self.insert("source_version", source_version_record())
        study = self.insert("study", {"schema_version": SV, "study_id": "st-test-1"})
        self.assertIsNotNone(study)
        finding = self.insert("finding", {
            "schema_version": SV, "finding_id": "f-test-1", "study_id": "st-test-1",
            "source_version_id": sv["version_id"], "statement": "observed X"})
        claim = self.insert("claim", {
            "schema_version": SV, "claim_id": "c-test-1", "statement": "X helps Y"})
        self.insert("relation", {"schema_version": SV, "relation_id": "r-test-1",
                                 "claim_id": claim["claim_id"],
                                 "finding_id": finding["finding_id"], "relation": "supports"})
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("relation", {"schema_version": SV, "relation_id": "r-test-2",
                                     "claim_id": claim["claim_id"],
                                     "finding_id": finding["finding_id"],
                                     "relation": "supports"})
        self.assertIn("EV-Dup", str(ctx.exception))

    def test_duplicate_finding_statement_rejected(self):
        self.insert("source_version", source_version_record())
        self.insert("study", {"schema_version": SV, "study_id": "st-test-1"})
        self.insert("finding", {"schema_version": SV, "finding_id": "f-test-1",
                                "study_id": "st-test-1", "source_version_id": "sv-test-1",
                                "statement": "observed X"})
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("finding", {"schema_version": SV, "finding_id": "f-test-2",
                                    "study_id": "st-test-1", "source_version_id": "sv-test-1",
                                    "statement": "observed X"})
        self.assertIn("EV-Dup", str(ctx.exception))

    def test_duplicate_study_report_and_version_id_rejected(self):
        self.insert("study", {"schema_version": SV, "study_id": "st-test-1"})
        self.insert("study_report", {"schema_version": SV, "study_id": "st-test-1",
                                     "work_id": "lt-fixture01"})
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("study_report", {"schema_version": SV, "study_id": "st-test-1",
                                         "work_id": "lt-fixture01"})
        self.assertIn("EV-Dup", str(ctx.exception))
        self.insert("source_version", source_version_record())
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("source_version", source_version_record())
        self.assertIn("EV-Dup", str(ctx.exception))

    def test_wrong_reference_rejected(self):
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("source_version", source_version_record(work_id="lt-missing000"))
        self.assertIn("EV-Ref", str(ctx.exception))
        self.insert("study", {"schema_version": SV, "study_id": "st-test-1"})
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("finding", {"schema_version": SV, "finding_id": "f-test-1",
                                    "study_id": "st-test-1",
                                    "source_version_id": "sv-missing000",
                                    "statement": "s"})
        self.assertIn("EV-Ref", str(ctx.exception))

    def test_wrong_version_conflict_rejected(self):
        # works row holds the original file (sha256=DIGEST_A, pdf_version=
        # 'published_version'); binding that same file under a different
        # version label is a wrong-version binding.
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("source_version", source_version_record(original_version="preprint_v1"))
        self.assertIn("EV-Version", str(ctx.exception))
        # matching version label, unknown label, and a *different* file version
        # (preprint of the same work) are all accepted
        self.insert("source_version", source_version_record())
        self.insert("source_version", source_version_record(version_id="sv-test-2",
                                                            original_version=None,
                                                            original_sha256=None))
        self.insert("source_version", source_version_record(version_id="sv-test-3",
                                                            original_version="preprint_v1",
                                                            original_sha256=DIGEST_B))

    def test_parsed_hash_without_format_rejected(self):
        bad = source_version_record(parsed_sha256=DIGEST_B)
        self.assertTrue(any("EV-Fields" in e for e in ev.validate_record("source_version", bad)))


class ExpressivenessTests(EvidenceModelTestsBase):
    """验收 #1: same Work with several RQs, several source versions, one study
    in several reports, contradictory evidence and missing fields — expressible,
    with evidence counted per distinct study (no double counting)."""

    def setUp(self):
        super().setUp()
        conn = self.conn
        conn.execute("INSERT INTO works (internal_id, title, record_status) VALUES (?, ?, 'ingested')",
                     ("lt-fixture02", "Second report of the same study (synthetic)"))
        conn.execute("INSERT INTO works (internal_id, title, doi, record_status) VALUES (?, ?, ?, 'ingested')",
                     ("lt-fixture03", "Contradicting journal article (synthetic)",
                      "10.1000/fixture.c"))
        conn.commit()
        self.insert("research_question", rq_record())
        self.insert("research_question", rq_record(rq_id="rq-test-2",
                                                   statement="Does X harm Z?"))
        self.insert("study", {"schema_version": SV, "study_id": "st-study-1",
                              "study_key": "synthetic-study-1"})
        self.insert("study", {"schema_version": SV, "study_id": "st-study-2"})
        self.insert("study_report", {"schema_version": SV, "study_id": "st-study-1",
                                     "work_id": "lt-fixture01", "report_role": "primary"})
        self.insert("study_report", {"schema_version": SV, "study_id": "st-study-1",
                                     "work_id": "lt-fixture02", "report_role": "secondary"})
        self.insert("study_report", {"schema_version": SV, "study_id": "st-study-2",
                                     "work_id": "lt-fixture03"})
        # same Work, two source versions (published + preprint of the same report)
        self.insert("source_version", source_version_record())
        self.insert("source_version", source_version_record(
            version_id="sv-test-2", original_version="preprint_v1",
            original_sha256=DIGEST_B))
        self.insert("source_version", source_version_record(
            version_id="sv-test-3", work_id="lt-fixture02",
            original_version=None, original_sha256=None))
        self.insert("source_version", source_version_record(
            version_id="sv-test-4", work_id="lt-fixture03", source_kind="journal_article",
            original_version="published_version", original_sha256=None))
        # findings: two from study 1 (different reports/RQs/versions), one contradicting
        self.insert("finding", {"schema_version": SV, "finding_id": "f-study1-a",
                                "study_id": "st-study-1", "source_version_id": "sv-test-1",
                                "research_question_id": "rq-test-1",
                                "statement": "report A observed X",
                                "attributes": {"sample_size": 120}})
        self.insert("finding", {"schema_version": SV, "finding_id": "f-study1-b",
                                "study_id": "st-study-1", "source_version_id": "sv-test-3",
                                "research_question_id": "rq-test-1",
                                "statement": "report B observed X again"})
        self.insert("finding", {"schema_version": SV, "finding_id": "f-study1-c",
                                "study_id": "st-study-1", "source_version_id": "sv-test-2",
                                "research_question_id": "rq-test-2",
                                "statement": "preprint version notes measurement limits"})
        self.insert("finding", {"schema_version": SV, "finding_id": "f-study2-a",
                                "study_id": "st-study-2", "source_version_id": "sv-test-4",
                                "research_question_id": "rq-test-2",
                                "statement": "other study observed the opposite"})
        self.insert("claim", {"schema_version": SV, "claim_id": "c-claim-1",
                              "research_question_id": "rq-test-1",
                              "statement": "X helps Y in the studied population"})
        self.insert("claim", {"schema_version": SV, "claim_id": "c-claim-2",
                              "research_question_id": "rq-test-2", "statement": "X harms Z"})
        self.insert("relation", {"schema_version": SV, "relation_id": "r-rel-1",
                                 "claim_id": "c-claim-1", "finding_id": "f-study1-a",
                                 "relation": "supports"})
        self.insert("relation", {"schema_version": SV, "relation_id": "r-rel-2",
                                 "claim_id": "c-claim-1", "finding_id": "f-study1-b",
                                 "relation": "supports"})
        self.insert("relation", {"schema_version": SV, "relation_id": "r-rel-3",
                                 "claim_id": "c-claim-1", "finding_id": "f-study2-a",
                                 "relation": "refutes"})
        self.insert("relation", {"schema_version": SV, "relation_id": "r-rel-4",
                                 "claim_id": "c-claim-2", "finding_id": "f-study1-c",
                                 "relation": "insufficient"})

    def test_one_work_multiple_rqs_and_source_versions(self):
        rq1_findings = self.conn.execute(
            "SELECT COUNT(*) FROM evidence_findings f"
            " JOIN evidence_source_versions sv ON sv.version_id = f.source_version_id"
            " WHERE sv.work_id='lt-fixture01' AND f.research_question_id='rq-test-1'"
        ).fetchone()[0]
        rq2_findings = self.conn.execute(
            "SELECT COUNT(*) FROM evidence_findings f"
            " JOIN evidence_source_versions sv ON sv.version_id = f.source_version_id"
            " WHERE sv.work_id='lt-fixture01' AND f.research_question_id='rq-test-2'"
        ).fetchone()[0]
        self.assertEqual((rq1_findings, rq2_findings), (1, 1))
        # the same study's second report (a second Work) carries the other
        # rq-test-1 finding — same study, several reports
        study1_rq1_reports = self.conn.execute(
            "SELECT COUNT(DISTINCT sv.work_id) FROM evidence_findings f"
            " JOIN evidence_source_versions sv ON sv.version_id = f.source_version_id"
            " WHERE f.study_id='st-study-1' AND f.research_question_id='rq-test-1'"
        ).fetchone()[0]
        self.assertEqual(study1_rq1_reports, 2)
        versions = self.conn.execute(
            "SELECT COUNT(*) FROM evidence_source_versions WHERE work_id='lt-fixture01'"
        ).fetchone()[0]
        self.assertEqual(versions, 2)

    def test_contradictory_evidence_and_missing_fields_expressible(self):
        relations = dict(self.conn.execute(
            "SELECT relation, COUNT(*) FROM evidence_relations WHERE claim_id='c-claim-1'"
            " GROUP BY relation"))
        self.assertEqual(relations, {"supports": 2, "refutes": 1})
        # missing fields honestly stored as NULL: no sha256, no sample attributes,
        # no scope, no study_key
        row = self.conn.execute(
            "SELECT original_sha256, study_id FROM evidence_source_versions"
            " WHERE version_id='sv-test-4'").fetchone()
        self.assertEqual(tuple(row), (None, None))
        attributes = self.conn.execute(
            "SELECT attributes FROM evidence_findings WHERE finding_id='f-study2-a'"
        ).fetchone()[0]
        self.assertEqual(json.loads(attributes), {})

    def test_evidence_counted_per_distinct_study_no_double_counting(self):
        summary = ev.evidence_summary(self.conn, "c-claim-1")
        # two supporting findings come from the SAME study (two reports) and
        # count as one distinct study; the refuting finding is a second study.
        self.assertEqual(summary["relations"]["supports"], {"findings": 2, "studies": 1})
        self.assertEqual(summary["relations"]["refutes"], {"findings": 1, "studies": 1})
        self.assertEqual(summary["relations"]["insufficient"], {"findings": 0, "studies": 0})
        self.assertEqual(summary["distinct_studies"], 2)
        # the second claim holds its relation in the insufficient bucket
        summary2 = ev.evidence_summary(self.conn, "c-claim-2")
        self.assertEqual(summary2["relations"]["insufficient"], {"findings": 1, "studies": 1})
        self.assertEqual(summary2["distinct_studies"], 1)

    def test_summary_unknown_claim_rejected(self):
        with self.assertRaises(ev.EvidenceError) as ctx:
            ev.evidence_summary(self.conn, "c-missing00")
        self.assertIn("EV-Ref", str(ctx.exception))


class LocatorVerificationTests(EvidenceModelTestsBase):
    """交付范围 #2: 来源定位验证状态显式记录；bbox 存在不当准确。"""

    def setUp(self):
        super().setUp()
        self.insert("source_version", source_version_record())

    def test_bbox_detection_never_verified(self):
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("locator_check", {"schema_version": SV, "check_id": "lc-test-1",
                                          "version_id": "sv-test-1", "method": "bbox_detection",
                                          "result": "verified", "details": "bbox found"})
        self.assertIn("EV-Locator", str(ctx.exception))

    def test_detection_updates_to_unverified_only(self):
        result = ev.record_locator_check(self.conn, {
            "schema_version": SV, "check_id": "lc-test-1", "version_id": "sv-test-1",
            "method": "bbox_detection", "result": "detected", "details": None})
        self.assertEqual(result["source_locator_status"], "unverified")

    def test_explicit_verified_check_required(self):
        with self.assertRaises(ev.EvidenceError) as ctx:
            ev.record_locator_check(self.conn, {
                "schema_version": SV, "check_id": "lc-test-2", "version_id": "sv-test-1",
                "method": "page_anchor_match", "result": "verified", "details": None})
        self.assertIn("EV-Locator", str(ctx.exception))
        result = ev.record_locator_check(self.conn, {
            "schema_version": SV, "check_id": "lc-test-3", "version_id": "sv-test-1",
            "method": "page_anchor_match", "result": "verified",
            "details": "page 3 anchor matched against the parsed version"})
        self.assertEqual(result["source_locator_status"], "verified")

    def test_failed_check_and_append_only_history(self):
        ev.record_locator_check(self.conn, {
            "schema_version": SV, "check_id": "lc-test-1", "version_id": "sv-test-1",
            "method": "page_anchor_match", "result": "failed", "details": "no anchor"})
        ev.record_locator_check(self.conn, {
            "schema_version": SV, "check_id": "lc-test-2", "version_id": "sv-test-1",
            "method": "page_anchor_match", "result": "verified", "details": "matched"})
        checks = self.conn.execute(
            "SELECT check_id, result FROM evidence_locator_checks"
            " WHERE version_id='sv-test-1' ORDER BY check_id").fetchall()
        self.assertEqual([(c[0], c[1]) for c in checks],
                         [("lc-test-1", "failed"), ("lc-test-2", "verified")])
        status = self.conn.execute(
            "SELECT locator_status FROM evidence_source_versions WHERE version_id='sv-test-1'"
        ).fetchone()[0]
        self.assertEqual(status, "verified")


class ReleaseSeparationTests(EvidenceModelTestsBase):
    """交付范围 #3: 支持/反证/证据不足、科学质量、人工审核、发布资格正交分离。"""

    def test_ai_origin_cannot_self_qualify(self):
        bad = {"schema_version": SV, "appraisal_id": "ap-test-1", "target_kind": "claim",
               "target_id": "c-test-1", "quality": "medium",
               "review_origin": "ai_draft", "review_status": "ai_reviewed",
               "release_eligibility": "eligible"}
        self.assertTrue(any("EV-Release" in e for e in ev.validate_record("appraisal", bad)))
        bad["review_origin"] = "multi_model_consistent"
        self.assertTrue(any("EV-Release" in e for e in ev.validate_record("appraisal", bad)))

    def test_human_origin_can_hold_eligible_flag(self):
        good = {"schema_version": SV, "appraisal_id": "ap-test-1", "target_kind": "claim",
                "target_id": "c-test-1", "quality": None,
                "review_origin": "single_human", "review_status": "human_reviewed",
                "release_eligibility": "eligible"}
        self.assertEqual(ev.validate_record("appraisal", good), [])

    def test_default_is_not_eligible_and_target_must_exist(self):
        self.insert("claim", {"schema_version": SV, "claim_id": "c-test-1",
                              "statement": "X helps Y"})
        stored = self.insert("appraisal", {"schema_version": SV, "appraisal_id": "ap-test-1",
                                           "target_kind": "claim", "target_id": "c-test-1",
                                           "quality": "low"})
        self.assertEqual(stored["release_eligibility"], "not_eligible")
        with self.assertRaises(ev.EvidenceError) as ctx:
            self.insert("appraisal", {"schema_version": SV, "appraisal_id": "ap-test-2",
                                      "target_kind": "finding", "target_id": "f-missing000"})
        self.assertIn("EV-Ref", str(ctx.exception))


def _write_pilot_fixture(run_dir: Path, *, issue_url=PILOT_ISSUE_URL,
                         work_id="lt-fixture01", run_id="ce06-synthetic-0001",
                         verdict="blocked", pdf_version="published_version",
                         with_review=True):
    run_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "schema": "astra-pilot-audit/1",
        "run_id": run_id,
        "issue_url": issue_url,
        "created_at": "2026-10-18T15:13:52Z",
        "work_id": work_id,
        "mode": "appraise",
        "verdict": verdict,
        "actual_model_id": None,
        "actual_identity_status": "unknown",
        "model_review_performed": False,
        "blocked_reasons": ["permission_registered", "policy_active"] if verdict == "blocked" else [],
        "conditions": [
            {"id": "original_available", "status": "pass", "detail": "sha256=" + DIGEST_PILOT},
            {"id": "permission_registered", "status": "missing", "detail": "no registration"},
        ],
        "library_metadata": {
            "internal_id": work_id, "doi": "10.1000/fixture.x",
            "title": "Fixture Work (synthetic, not a real publication)",
            "language": "en", "publication_year": 2018,
            "metadata_status": "crossref_verified", "license": "cc-by",
            "pdf_version": pdf_version,
        },
    }
    (run_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if with_review:
        review = {
            "schema_version": 1, "run_id": run_id, "mode": "appraise",
            "reviewer_type": "ai_model", "model_id": None,
            "model_identity_status": "not_called", "model_review_performed": False,
            "execution_kind": "deterministic_demo", "findings": [],
            "uncertainties": ["evidence_insufficient", "original_unavailable"],
            "review_status": "unresolved", "label_tier": "silver",
            "maturity_level": "L0", "human_review_status": "not_reviewed",
            "allowed_for_agent_release": False,
            "summary": "确定性演示。未调用模型，无科研结论。",
        }
        (run_dir / "review.json").write_text(
            json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


class PilotMappingTests(EvidenceModelTestsBase):
    """验收 #4: the recorded Issue #10 pilot outcome maps honestly; missing
    evidence stays undetermined; nothing is fabricated."""

    def setUp(self):
        super().setUp()
        self.run_dir = _write_pilot_fixture(self.root / "astra-pilot" / "ce06-synthetic-0001")

    def test_dry_run_preserves_unknowns_and_writes_nothing(self):
        result = ev.map_pilot_run(self.run_dir, self.conn, apply=False)
        self.assertEqual(result["verdict"], "blocked")
        self.assertEqual(result["original_sha256"], DIGEST_PILOT)
        self.assertEqual(result["original_version"], "published_version")
        self.assertEqual(result["preserved_unknowns"],
                         ["parsed_sha256", "parsed_format", "study_id", "locator_status",
                          "research_content"])
        self.assertEqual(result["uncertainties"],
                         ["evidence_insufficient", "original_unavailable"])
        self.assertFalse(result["model_review_performed"])
        self.assertFalse(result["applied"])
        for table in ev.EVIDENCE_TABLES:
            count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_apply_maps_source_version_with_honest_nulls(self):
        result = ev.map_pilot_run(self.run_dir, self.conn, apply=True)
        self.assertTrue(result["applied"])
        row = self.conn.execute(
            "SELECT version_id, work_id, study_id, source_kind, original_version,"
            " original_sha256, parsed_sha256, parsed_format, locator_status, origin, origin_ref"
            " FROM evidence_source_versions").fetchone()
        self.assertEqual(tuple(row), (
            "sv-pilot-ce06-synthetic-0001", "lt-fixture01", None, "unspecified",
            "published_version", DIGEST_PILOT, None, None, "unknown",
            "pilot_mapping", "ce06-synthetic-0001"))
        notes = self.conn.execute(
            "SELECT notes FROM evidence_source_versions").fetchone()[0]
        self.assertIn("blocked", notes)
        self.assertIn("evidence_insufficient", notes)
        # no research content was fabricated
        for table, expected in (("evidence_findings", 0), ("evidence_claims", 0),
                                ("evidence_relations", 0), ("evidence_appraisals", 0)):
            count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertEqual(count, expected, table)

    def test_remap_is_idempotent(self):
        ev.map_pilot_run(self.run_dir, self.conn, apply=True)
        again = ev.map_pilot_run(self.run_dir, self.conn, apply=True)
        self.assertTrue(again["already_mapped"])
        self.assertFalse(again["applied"])
        count = self.conn.execute(
            "SELECT COUNT(*) FROM evidence_source_versions").fetchone()[0]
        self.assertEqual(count, 1)

    def test_foreign_run_audit_rejected(self):
        other = _write_pilot_fixture(self.root / "other-run", issue_url="https://example.invalid/x")
        with self.assertRaises(ev.EvidenceError):
            ev.map_pilot_run(other, self.conn, apply=True)
        other2 = _write_pilot_fixture(self.root / "other-run2",
                                      run_id="ce06-synthetic-0002", with_review=False)
        result = ev.map_pilot_run(other2, self.conn, apply=True)
        self.assertEqual(result["uncertainties"], [])
        self.assertIn("none declared", self.conn.execute(
            "SELECT notes FROM evidence_source_versions WHERE version_id=?",
            ("sv-pilot-ce06-synthetic-0002",)).fetchone()[0])

    def test_completed_run_without_model_review_still_maps_only_provenance(self):
        run_dir = _write_pilot_fixture(self.root / "ready-run",
                                       run_id="ce06-synthetic-0003", verdict="completed")
        result = ev.map_pilot_run(run_dir, self.conn, apply=True)
        self.assertEqual(result["verdict"], "completed")
        self.assertIn("requires the human-approved extraction flow", result["research_content"])
        count = self.conn.execute("SELECT COUNT(*) FROM evidence_findings").fetchone()[0]
        self.assertEqual(count, 0)


class IndependentInstallTests(unittest.TestCase):
    """验收 #3: contract loading works from a relocated (installed) package copy,
    detached from the repository checkout."""

    def test_contract_load_and_validate_outside_source_tree(self):
        root = make_tmp_dir("ev-inst-")
        self.addCleanup(shutil.rmtree, root, True)
        instroot = root / "site"
        instroot.mkdir()
        shutil.copytree(Path(db.__file__).resolve().parent, instroot / "research_library",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        script = r"""
import sys
from pathlib import Path
import research_library
install_root = Path(sys.argv[1]).resolve()
pkg = Path(research_library.__file__).resolve()
assert install_root in pkg.parents, "package must load from the install root, not the repo: %s" % pkg
from research_library import evidence as ev
for kind in ev.KINDS:
    schema = ev.load_schema(kind)
    assert schema["type"] == "object", kind
    path = Path(ev.schema_path(kind))
    assert install_root in path.parents, path
good = {"schema_version": "ce.evidence/1", "version_id": "sv-inst-1",
        "work_id": "lt-inst00001", "source_kind": "report",
        "locator_status": "unknown", "origin": "manual"}
assert ev.validate_record("source_version", good) == []
bad = dict(good, unexpected_extra=1)
assert ev.validate_record("source_version", bad), "extra field must be rejected"
finding = {"schema_version": "ce.evidence/1", "finding_id": "f-inst-1",
           "study_id": "st-inst-1", "source_version_id": "sv-inst-1",
           "statement": "s", "attributes": {"sample_size": -1}}
assert ev.validate_record("finding", finding), "numeric bound must be rejected"
finding["attributes"] = {"sample_size": 42}
assert not ev.validate_record("finding", finding)
print("INSTALL_CONTRACT_OK")
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(instroot)
        env.pop("CHILDEVIDENCE_DATA_DIR", None)
        proc = subprocess.run([sys.executable, "-c", script, str(instroot)],
                              capture_output=True, text=True, cwd=str(root), env=env,
                              timeout=180)
        self.assertEqual(proc.returncode, 0,
                         "stdout:\n%s\nstderr:\n%s" % (proc.stdout, proc.stderr))
        self.assertIn("INSTALL_CONTRACT_OK", proc.stdout)


class EvidenceCliTests(EvidenceModelTestsBase):
    """验收 #5: reproducible commands via `research evidence ...`."""

    def test_migrate_creates_backup_and_verifies(self):
        rc = cli_main(["evidence", "migrate", "--db", str(self.db_path)])
        self.assertEqual(rc, 0)
        backups = list((self.db_path.parent / "backups").glob("pre-evidence-migration-*.sqlite"))
        self.assertGreaterEqual(len(backups), 1)
        # second run stays idempotent and still backs up first
        rc = cli_main(["evidence", "migrate", "--db", str(self.db_path)])
        self.assertEqual(rc, 0)

    def test_validate_file(self):
        payload = {"kind": "source_version", "record": source_version_record()}
        path = self.root / "record.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(cli_main(["evidence", "validate", "--file", str(path)]), 0)
        payload["record"] = source_version_record(sneaky=1)
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(cli_main(["evidence", "validate", "--file", str(path)]), 2)

    def test_map_pilot_and_summary(self):
        run_dir = _write_pilot_fixture(self.root / "run-ce06",
                                       run_id="ce06-synthetic-cli1")
        rc = cli_main(["evidence", "map-pilot", "--run-dir", str(run_dir),
                       "--db", str(self.db_path)])
        self.assertEqual(rc, 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM evidence_source_versions").fetchone()[0], 0)
        rc = cli_main(["evidence", "map-pilot", "--run-dir", str(run_dir), "--apply",
                       "--db", str(self.db_path)])
        self.assertEqual(rc, 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM evidence_source_versions").fetchone()[0], 1)

    def test_summary_requires_claim(self):
        self.insert("claim", {"schema_version": SV, "claim_id": "c-test-1",
                              "statement": "X helps Y"})
        rc = cli_main(["evidence", "summary", "--claim-id", "c-test-1",
                       "--db", str(self.db_path)])
        self.assertEqual(rc, 0)
        rc = cli_main(["evidence", "summary", "--claim-id", "c-missing00",
                       "--db", str(self.db_path)])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
