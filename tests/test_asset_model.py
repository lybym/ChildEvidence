"""Offline synthetic tests for the professional assets model (Issue #15).

Covers the four acceptance criteria of Issue #15:

1. traceability: every method/profile version carries basis nature, version
   and evaluation citations; unapproved drafts cannot pose as released assets
   (AS-Release/AS-Lifecycle; GS-01/02/05);
2. explicit branches: competing explanations, user decline, ineffective
   method and per-audience adaptation are required structure;
3. unknown conditions never execute as true; missing evidence and
   retraction block; assets are declarative data only;
4. docs, reproducible commands (``research assets`` CLI) and offline tests,
   with the minimal synthetic demo asset chain seeded idempotently.

All fixtures are synthetic (``demo-*`` / ``test-*`` ids); no network, no
model calls, no real publication content, and the production database under
data/ is never touched.
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

from research_library import assets as am
from research_library import db, evidence as ev
from research_library.cli import main as cli_main

SV = "ce.assets/1"
DEMO_KIND_COUNT = 8  # the packaged minimal demo chain


# ---------------------------------------------------------------------------
# Record builders (valid by default; tests override individual fields)
# ---------------------------------------------------------------------------

def case_record(**changes):
    record = {
        "schema_version": SV,
        "asset_id": "test-eval-generic",
        "revision": 1,
        "title": "Test evaluation case (synthetic)",
        "created_by": "test-fixture",
        "created_at": "2026-10-19T00:00:00Z",
        "basis_kind": "design_choice",
        "basis_sufficiency": "insufficient",
        "basis_refs": [{"ref_kind": "design_note", "ref": "docs/notes.md",
                        "note": "synthetic design note"}],
        "demo_only": False,
        "fixture_kind": "synthetic",
        "input_fixture": {"request_id": "demo-request-test"},
        "expected_behaviors": ["asks for clarification first"],
        "forbidden_behaviors": ["labels the child"],
        "scoring_basis": "programmatically checkable actions only",
        "covers": [{"asset_id": "test-method-generic", "revision": 1}],
    }
    record.update(changes)
    return record


def method_record(**changes):
    record = {
        "schema_version": SV,
        "asset_id": "test-method-generic",
        "revision": 1,
        "title": "Test support method (synthetic)",
        "created_by": "test-fixture",
        "created_at": "2026-10-19T00:00:00Z",
        "basis_kind": "design_choice",
        "basis_sufficiency": "insufficient",
        "basis_refs": [{"ref_kind": "design_note", "ref": "docs/notes.md",
                        "note": "synthetic design note"}],
        "evaluation_refs": [{"case_id": "test-eval-generic", "revision": 1}],
        "demo_only": False,
        "goal": "clarify then support",
        "required_information": ["task_content"],
        "explanation_dimensions": ["misread the task", "knows it but stuck on step one"],
        "states": ["clarify", "support", "paused"],
        "initial_state": "clarify",
        "allowed_actions": ["ask_clarification", "explain_with_support", "pause"],
        "transitions": [{"from_state": "clarify", "on_outcome": "task clear",
                         "to_state": "support"}],
        "on_user_decline": {"action": "pause", "note": "stop, keep willingness"},
        "on_method_ineffective": {"action": "offer_choice", "note": "switch approach"},
        "audience_adaptation": {"child": "short sentences", "parent": "observe vs explain",
                                "teacher": "classroom equivalents"},
        "conflict_priority": ["stop signals over task completion"],
        "review_criteria": {"observe": ["restatement"], "adjust_when": ["no progress"],
                            "stop_when": ["exhaustion"]},
        "unknown_policy": "block",
    }
    record.update(changes)
    return record


def profile_record(**changes):
    record = {
        "schema_version": SV,
        "asset_id": "test-profile-generic",
        "revision": 1,
        "title": "Test interaction profile (synthetic)",
        "created_by": "test-fixture",
        "created_at": "2026-10-19T00:00:00Z",
        "basis_kind": "design_choice",
        "basis_sufficiency": "insufficient",
        "basis_refs": [{"ref_kind": "design_note", "ref": "docs/notes.md",
                        "note": "synthetic design note"}],
        "evaluation_refs": [{"case_id": "test-eval-generic", "revision": 1}],
        "demo_only": False,
        "expression_norms": {"listening": "reflect back", "questioning": "one at a time",
                             "feedback": "behavior-specific", "style": "warm and direct"},
        "audience_adaptation": {"child": "shorter", "parent": "observe vs explain",
                                "teacher": "classroom equivalents"},
        "conflict_priority": ["safety > willingness > goals > style"],
        "runtime_effect": "new_version_release",
    }
    record.update(changes)
    return record


def strategy_record(**changes):
    record = {
        "schema_version": SV,
        "asset_id": "test-strategy-generic",
        "revision": 1,
        "title": "Test strategy (synthetic)",
        "created_by": "test-fixture",
        "created_at": "2026-10-19T00:00:00Z",
        "basis_kind": "design_choice",
        "basis_sufficiency": "insufficient",
        "basis_refs": [{"ref_kind": "design_note", "ref": "docs/notes.md",
                        "note": "synthetic design note"}],
        "evaluation_refs": [{"case_id": "test-eval-generic", "revision": 1}],
        "demo_only": False,
        "goal": "support the current task",
        "applies_when": [{"information": "task_content", "expect": "available",
                          "on_unknown": "needs_information"}],
        "excludes_when": [{"information": "exhaustion_signal", "expect": "available",
                           "on_unknown": "block"}],
        "steps": [{"order": 1, "action": "ask_clarification", "content": "clarify"}],
        "observed_outcomes": ["task restated"],
        "adjust_when": ["no progress"],
        "stop_when": ["exhaustion"],
        "evidence_summary": "synthetic; no research basis, marked insufficient",
    }
    record.update(changes)
    return record


class AssetModelTestsBase(unittest.TestCase):
    """Common fixture: temp library DB with one Work and one evidence Claim."""

    def setUp(self):
        self.root = make_tmp_dir("am-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.db_path = self.root / "research-library" / "library.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.conn.execute(
            "INSERT INTO works (internal_id, title, record_status) VALUES (?, ?, 'ingested')",
            ("lt-fixture01", "Fixture Work (synthetic, not a real publication)"))
        ev.insert_record(self.conn, "claim", {
            "schema_version": ev.SCHEMA_VERSION, "claim_id": "c-fixture01",
            "statement": "Synthetic claim fixture (no research meaning)"})
        self.conn.commit()

    def prepared(self, kind, record):
        """Record with defaults applied and content_hash computed (insert shape)."""
        prepared = am.prepared_record(kind, record)
        prepared.setdefault("content_hash", am.compute_content_hash(prepared))
        return prepared

    def insert(self, kind, record, conn=None):
        return am.insert_record(conn or self.conn, kind, self.prepared(kind, record))


class DemoChainTestsBase(unittest.TestCase):
    """Fixture for demo-chain seeding: a clean synthetic DB without works rows
    (seed_demo refuses databases that contain bibliographic records)."""

    def setUp(self):
        self.root = make_tmp_dir("am-seed-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.conn = db.connect(self.root / "demo.sqlite")
        self.addCleanup(self.conn.close)

    def prepared(self, kind, record):
        prepared = am.prepared_record(kind, record)
        prepared.setdefault("content_hash", am.compute_content_hash(prepared))
        return prepared

    def insert(self, kind, record, conn=None):
        return am.insert_record(conn or self.conn, kind, self.prepared(kind, record))


class FreshDatabaseTests(unittest.TestCase):
    """A fresh database gets the complete additive asset schema."""

    def test_connect_creates_all_asset_tables(self):
        root = make_tmp_dir("am-fresh-")
        self.addCleanup(shutil.rmtree, root, True)
        with closing(db.connect(root / "library.sqlite")) as conn:
            self.assertEqual(sorted(am.asset_tables_present(conn)), sorted(am.ASSET_TABLES))
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            # evidence layer coexists untouched
            self.assertEqual(sorted(ev.evidence_tables_present(conn)),
                             sorted(ev.EVIDENCE_TABLES))

    def test_works_schema_untouched(self):
        root = make_tmp_dir("am-fresh2-")
        self.addCleanup(shutil.rmtree, root, True)
        with closing(db.connect(root / "library.sqlite")) as conn:
            work_cols = {row[1] for row in conn.execute("PRAGMA table_info(works)")}
            self.assertNotIn("runtime_effect", work_cols)
            self.assertNotIn("lifecycle_status", work_cols)

    def test_schema_action_vocabulary_matches_code(self):
        """The finite action vocabulary is identical in code and every schema."""
        for kind in ("strategy", "support_method"):
            schema_actions = set()
            properties = am.load_schema(kind)["properties"]
            containers = [properties.get("steps", {}).get("items", {}),
                          properties.get("allowed_actions", {}).get("items", {}),
                          properties.get("on_user_decline", {}),
                          properties.get("on_method_ineffective", {})]
            for container in containers:
                enum = container.get("properties", {}).get("action", {}).get("enum")
                if enum:
                    schema_actions.update(enum)
            self.assertEqual(schema_actions, set(am.ACTIONS))


class UpgradeCompatibilityTests(unittest.TestCase):
    """Pre-assets databases upgrade additively; legacy rows stay byte-identical;
    the recorded migration leaves a restorable backup."""

    def setUp(self):
        self.root = make_tmp_dir("am-upg-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.db_path = self.root / "library.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(db.BASE_SCHEMA + ev.EVIDENCE_DDL)  # pre-assets schema
        conn.execute("INSERT INTO works (internal_id, title, record_status)"
                     " VALUES (?, ?, 'ingested')",
                     ("lt-legacy00001", "Legacy Work (synthetic)"))
        conn.execute("INSERT INTO download_log (internal_id, url, attempt, status, at)"
                     " VALUES (?, ?, 1, 'ok', '2026-10-13T00:00:00Z')",
                     ("lt-legacy00001", "https://example.invalid/legacy.pdf"))
        conn.execute("INSERT INTO evidence_claims (claim_id, statement, created_at)"
                     " VALUES ('cl-legacy01', 'Legacy claim', '2026-10-18T00:00:00Z')")
        conn.commit()
        self.legacy = {table: [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
                       for table in ("works", "download_log", "evidence_claims")}
        conn.close()
        probe = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(am.asset_tables_present(probe), [])
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
        result = am.migrate_with_backup(self.db_path)
        self.assertEqual(result["integrity"], "ok")
        self.assertIsNotNone(result["backup"])
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(sorted(result["asset_tables"]), sorted(am.ASSET_TABLES))
        for table, rows in self.legacy.items():
            self.assertEqual(self.rows_of(self.db_path, table), rows, table)
            self.assertEqual(self.rows_of(result["backup"], table), rows, "backup " + table)
        # converges with the normal connect() path afterwards (additive, idempotent)
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(sorted(am.asset_tables_present(conn)), sorted(am.ASSET_TABLES))
            for table, rows in self.legacy.items():
                self.assertEqual([dict(r) for r in conn.execute(f"SELECT * FROM {table}")],
                                 rows, table)

    def test_fresh_database_migration_needs_no_backup(self):
        fresh = self.root / "fresh" / "library.sqlite"
        fresh.parent.mkdir(parents=True, exist_ok=True)
        result = am.migrate_with_backup(fresh)
        self.assertIsNone(result["backup"])
        self.assertEqual(result["integrity"], "ok")


class StrictRejectionTests(AssetModelTestsBase):
    """Illegal extra fields, bad bounds, wrong references, wrong versions and
    governance bypasses are rejected with explicit AS-* rules."""

    def setUp(self):
        super().setUp()
        # most strict-path tests insert a valid method citing this case
        self.insert("evaluation_case", case_record())

    def test_extra_field_rejected(self):
        record = method_record()
        errors = am.validate_record("support_method", {**record, "sneaky": True})
        self.assertTrue(any("unexpected field 'sneaky'" in e for e in errors))

    def test_code_like_field_rejected(self):
        """Assets stay declarative data: no executable field can be smuggled in."""
        for sneaky in ("script", "code", "exec", "command"):
            record = method_record()
            errors = am.validate_record("support_method", {**record, sneaky: "1+1"})
            self.assertTrue(any(f"unexpected field '{sneaky}'" in e for e in errors), sneaky)

    def test_wrong_envelope_version_rejected(self):
        errors = am.validate_record("strategy", strategy_record(schema_version="ce.assets/2"))
        self.assertTrue(any("expected const 'ce.assets/1'" in e for e in errors))

    def test_unknown_action_rejected(self):
        record = strategy_record(
            steps=[{"order": 1, "action": "run_arbitrary_script", "content": "x"}])
        errors = am.validate_record("strategy", record)
        self.assertTrue(any("not in enum" in e for e in errors))

    def test_proceed_on_unknown_is_inexpressible(self):
        """The schema enum offers no 'proceed' option for unknown conditions."""
        record = strategy_record(applies_when=[
            {"information": "task_content", "expect": "available", "on_unknown": "proceed"}])
        errors = am.validate_record("strategy", record)
        self.assertTrue(any("on_unknown" in e and "not in enum" in e for e in errors))

    def test_supersedes_on_revision_one_rejected(self):
        record = method_record(supersedes_revision=1)
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("AS-Revision" in e for e in errors))

    def test_revision_two_without_supersedes_rejected(self):
        record = method_record(revision=2)
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("AS-Revision" in e for e in errors))

    def test_immediate_runtime_effect_rejected(self):
        record = profile_record(runtime_effect="immediate")
        errors = am.validate_record("interaction_profile", record)
        self.assertTrue(any("AS-GS04" in e for e in errors))

    def test_eligible_without_human_review_rejected(self):
        for override in ({"review_origin": "ai_draft", "review_status": "ai_reviewed",
                          "technical_validation": "passed", "scientific_appraisal": "done"},
                         {"review_origin": "single_human", "review_status": "human_reviewed",
                          "technical_validation": "not_run", "scientific_appraisal": "done"}):
            record = strategy_record(release_eligibility="eligible", **override)
            errors = am.validate_record("strategy", record)
            self.assertTrue(any("AS-Release" in e for e in errors), override)

    def test_released_without_eligible_rejected(self):
        errors = am.validate_record("strategy", strategy_record(lifecycle_status="released"))
        self.assertTrue(any("AS-Lifecycle" in e for e in errors))

    def test_retracted_without_reason_rejected(self):
        record = strategy_record(lifecycle_status="retracted")
        errors = am.validate_record("strategy", record)
        self.assertEqual(sum(1 for e in errors if "AS-Retract" in e), 3)

    def test_demo_asset_released_rejected(self):
        record = strategy_record(asset_id="demo-x", demo_only=True,
                                 release_eligibility="eligible")
        errors = am.validate_record("strategy", record)
        self.assertTrue(any("AS-Demo" in e for e in errors))
        record = strategy_record(asset_id="demo-x", demo_only=True,
                                 lifecycle_status="released",
                                 release_eligibility="eligible")
        errors = am.validate_record("strategy", record)
        self.assertTrue(any("AS-Demo" in e for e in errors))

    def test_demo_prefix_without_demo_only_rejected(self):
        errors = am.validate_record("strategy", strategy_record(asset_id="demo-x"))
        self.assertTrue(any("AS-Demo" in e for e in errors))

    def test_missing_content_hash_rejected_at_insert(self):
        record = self.prepared("support_method", method_record())
        record.pop("content_hash")
        with self.assertRaises(am.AssetsError) as ctx:
            am.insert_record(self.conn, "support_method", record)
        self.assertIn("AS-Hash", str(ctx.exception))

    def test_wrong_content_hash_rejected(self):
        record = self.prepared("support_method", method_record())
        record["content_hash"] = "sha256=" + "0" * 64
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("AS-Hash" in e for e in errors))
        with self.assertRaises(am.AssetsError) as ctx:
            am.insert_record(self.conn, "support_method", record)
        self.assertIn("AS-Hash", str(ctx.exception))

    def test_content_hash_survives_lifecycle_annotations(self):
        """Status annotations do not change the content identity."""
        record = self.prepared("support_method", method_record())
        for field, value in (("lifecycle_status", "superseded"),
                             ("release_eligibility", "not_eligible"),
                             ("review_status", "human_reviewed")):
            record[field] = value
        errors = am.validate_record("support_method", record)
        self.assertFalse([e for e in errors if "AS-Hash" in e])

    def test_duplicate_asset_revision_rejected(self):
        self.insert("support_method", method_record())
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", method_record(title="different title"))
        self.assertIn("AS-Dup", str(ctx.exception))

    def test_revision_gap_rejected(self):
        self.insert("support_method", method_record())
        record = method_record(revision=3, supersedes_revision=2)
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-Chain", str(ctx.exception))

    def test_direct_superseded_insert_rejected(self):
        record = method_record(lifecycle_status="superseded")
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-Lifecycle", str(ctx.exception))

    def test_evaluation_case_cannot_carry_evaluation_refs(self):
        record = case_record(evaluation_refs=[{"case_id": "x", "revision": 1}])
        errors = am.validate_record("evaluation_case", record)
        self.assertTrue(any("unexpected field 'evaluation_refs'" in e for e in errors))

    def test_unknown_claim_basis_ref_rejected(self):
        record = method_record(
            basis_kind="application_inference",
            basis_refs=[{"ref_kind": "claim", "ref": "cl-missing", "note": "n"}])
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-BasisRef", str(ctx.exception))

    def test_claim_basis_ref_must_exist(self):
        record = method_record(
            basis_kind="application_inference",
            basis_refs=[{"ref_kind": "claim", "ref": "c-fixture01",
                         "note": "existing synthetic claim"}])
        stored = self.insert("support_method", record)
        self.assertEqual(stored["asset_id"], "test-method-generic")

    def test_work_basis_ref_must_exist(self):
        record = method_record(
            basis_refs=[{"ref_kind": "work", "ref": "lt-fixture01", "note": "n"}])
        stored = self.insert("support_method", record)
        self.assertEqual(stored["basis_refs"][0]["ref_kind"], "work")

    def test_research_supported_without_research_ref_rejected(self):
        record = method_record(basis_sufficiency="research_supported")
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-Basis", str(ctx.exception))

    def test_design_choice_must_be_insufficient(self):
        record = method_record(basis_kind="design_choice",
                               basis_sufficiency="research_supported")
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-Basis", str(ctx.exception))

    def test_application_inference_insufficient_allowed(self):
        record = method_record(basis_kind="application_inference")
        stored = self.insert("support_method", record)
        self.assertEqual(stored["basis_sufficiency"], "insufficient")

    def test_evaluation_ref_to_missing_case_rejected(self):
        record = method_record(
            evaluation_refs=[{"case_id": "test-eval-nothing", "revision": 1}])
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-EvalRef", str(ctx.exception))

    def test_evaluation_ref_without_coverage_rejected(self):
        # setUp already stored the case covering test-method-generic@1;
        # citing it from a different asset must fail the coverage closure
        record = method_record(
            asset_id="test-method-other",
            evaluation_refs=[{"case_id": "test-eval-generic", "revision": 1}])
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("does not declare coverage", str(ctx.exception))

    def test_state_references_validated(self):
        record = method_record(initial_state="not-a-state")
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("AS-State" in e for e in errors))
        record = method_record(transitions=[{"from_state": "nowhere",
                                             "on_outcome": "x", "to_state": "support"}])
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("AS-State" in e for e in errors))

    def test_wrong_asset_id_pattern_rejected(self):
        errors = am.validate_record("strategy", strategy_record(asset_id="Bad_Id"))
        self.assertTrue(any("pattern" in e for e in errors))


class BranchStructureTests(AssetModelTestsBase):
    """验收 #2: competing explanations, user decline, ineffective method and
    per-audience adaptation are required structure, not conventions."""

    def test_method_requires_branch_structure(self):
        base = method_record()
        for removal in ("explanation_dimensions", "on_user_decline",
                        "on_method_ineffective", "audience_adaptation",
                        "conflict_priority", "review_criteria", "unknown_policy",
                        "required_information", "states", "initial_state",
                        "allowed_actions"):
            record = {k: v for k, v in base.items() if k != removal}
            errors = am.validate_record("support_method", record)
            self.assertTrue(any(f"missing required property '{removal}'" in e
                                for e in errors), removal)

    def test_audience_adaptation_covers_all_three_requesters(self):
        record = method_record(
            audience_adaptation={"child": "x", "parent": "y"})
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("missing required property 'teacher'" in e for e in errors))

    def test_unknown_policy_is_const_block(self):
        record = method_record(unknown_policy="proceed")
        errors = am.validate_record("support_method", record)
        self.assertTrue(any("expected const 'block'" in e for e in errors))

    def test_stored_method_round_trips_branches(self):
        self.insert("evaluation_case", case_record())
        stored = self.insert("support_method", method_record())
        loaded = am.get_record(self.conn, "support_method", stored["asset_id"], 1)
        self.assertEqual(len(loaded["explanation_dimensions"]), 2)
        self.assertEqual(loaded["on_user_decline"]["action"], "pause")
        self.assertEqual(loaded["on_method_ineffective"]["action"], "offer_choice")
        self.assertEqual(sorted(loaded["audience_adaptation"]),
                         ["child", "parent", "teacher"])
        self.assertEqual(loaded["unknown_policy"], "block")

    def test_strategy_requires_adjust_and_stop_conditions(self):
        for field in ("adjust_when", "stop_when", "steps", "goal", "evidence_summary"):
            record = {k: v for k, v in strategy_record().items() if k != field}
            errors = am.validate_record("strategy", record)
            self.assertTrue(any(f"missing required property '{field}'" in e
                                for e in errors), field)


class GS04ProfileTests(AssetModelTestsBase):
    """GS-04: any profile version (including the first) carries basis and
    evaluation refs; runtime effect is new-version-release only."""

    def test_first_version_with_refs_passes(self):
        self.insert("evaluation_case",
                    case_record(covers=[{"asset_id": "test-profile-generic",
                                         "revision": 1}]))
        stored = self.insert("interaction_profile", profile_record())
        self.assertEqual(stored["runtime_effect"], "new_version_release")
        self.assertTrue(stored["basis_refs"])
        self.assertTrue(stored["evaluation_refs"])

    def test_missing_evaluation_refs_rejected(self):
        record = profile_record()
        record.pop("evaluation_refs")
        errors = am.validate_record("interaction_profile", record)
        self.assertTrue(any("missing required property 'evaluation_refs'" in e
                            for e in errors))
        record = profile_record(evaluation_refs=[])
        errors = am.validate_record("interaction_profile", record)
        self.assertTrue(any("fewer than minItems=1" in e for e in errors))

    def test_missing_basis_refs_rejected(self):
        record = profile_record()
        record.pop("basis_refs")
        errors = am.validate_record("interaction_profile", record)
        self.assertTrue(any("missing required property 'basis_refs'" in e
                            for e in errors))


class RevisionChainTests(AssetModelTestsBase):
    """Immutable revision chain: append-only, no gaps; the previous version is
    marked superseded when a new one lands; content stays intact."""

    def setUp(self):
        super().setUp()
        self.insert("evaluation_case", case_record())
        self.insert("evaluation_case",
                    case_record(asset_id="test-eval-rev2",
                                covers=[{"asset_id": "test-method-generic",
                                         "revision": 2}]))
        self.first = self.insert("support_method", method_record())

    def revision_two(self, **changes):
        record = method_record(revision=2, supersedes_revision=1,
                               title="Test support method (revised)",
                               evaluation_refs=[{"case_id": "test-eval-rev2",
                                                 "revision": 1}],
                               **changes)
        return self.insert("support_method", record)

    def test_new_revision_marks_previous_superseded(self):
        stored = self.revision_two()
        self.assertTrue(stored["superseded_previous"])
        previous = am.get_record(self.conn, "support_method",
                                 "test-method-generic", 1)
        self.assertEqual(previous["lifecycle_status"], "superseded")
        self.assertEqual(previous["content_hash"], self.first["content_hash"])
        self.assertEqual(am.latest_revision(self.conn, "support_method",
                                            "test-method-generic"), 2)

    def test_new_revision_requires_fresh_evaluation_coverage(self):
        record = method_record(revision=2, supersedes_revision=1)
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert("support_method", record)
        self.assertIn("AS-EvalRef", str(ctx.exception))

    def test_retracted_previous_stays_retracted(self):
        am.retract_asset(self.conn, "support_method", "test-method-generic", 1,
                         reason="synthetic defect", ref="demo-decision-01")
        self.revision_two()
        previous = am.get_record(self.conn, "support_method",
                                 "test-method-generic", 1)
        self.assertEqual(previous["lifecycle_status"], "retracted")

    def test_superseded_assets_report_blockers(self):
        self.revision_two()
        verdict = am.asset_blockers(self.conn, "support_method",
                                    "test-method-generic", 1)
        codes = {b["code"] for b in verdict["blockers"]}
        self.assertIn("ASB-Superseded", codes)
        self.assertFalse(verdict["usable"])


class RetractionTests(AssetModelTestsBase):
    """GS-03: append-style retraction with reason/date/ref; blocks usability."""

    def setUp(self):
        super().setUp()
        self.insert("evaluation_case", case_record())
        self.insert("support_method", method_record())

    def test_retract_sets_annotation_and_keeps_content(self):
        before = am.get_record(self.conn, "support_method", "test-method-generic", 1)
        stored = am.retract_asset(self.conn, "support_method",
                                  "test-method-generic", 1,
                                  reason="synthetic defect found", ref="demo-decision-01",
                                  at="2026-10-19T01:00:00Z")
        self.assertEqual(stored["lifecycle_status"], "retracted")
        self.assertEqual(stored["retraction_reason"], "synthetic defect found")
        self.assertEqual(stored["retracted_at"], "2026-10-19T01:00:00Z")
        self.assertEqual(stored["content_hash"], before["content_hash"])

    def test_re_retract_rejected(self):
        am.retract_asset(self.conn, "support_method", "test-method-generic", 1,
                         reason="x", ref="r1")
        with self.assertRaises(am.AssetsError) as ctx:
            am.retract_asset(self.conn, "support_method", "test-method-generic", 1,
                             reason="y", ref="r2")
        self.assertIn("already retracted", str(ctx.exception))

    def test_retraction_requires_reason_and_ref(self):
        with self.assertRaises(am.AssetsError):
            am.retract_asset(self.conn, "support_method", "test-method-generic", 1,
                             reason="  ", ref="r1")
        with self.assertRaises(am.AssetsError):
            am.retract_asset(self.conn, "support_method", "test-method-generic", 1,
                             reason="x", ref="")

    def test_retracted_asset_blocks(self):
        am.retract_asset(self.conn, "support_method", "test-method-generic", 1,
                         reason="synthetic defect", ref="demo-decision-01")
        verdict = am.asset_blockers(self.conn, "support_method",
                                    "test-method-generic", 1)
        codes = {b["code"] for b in verdict["blockers"]}
        self.assertIn("ASB-Retracted", codes)
        self.assertTrue(verdict["blocked"])
        self.assertFalse(verdict["usable"])


class BlockerTests(DemoChainTestsBase):
    """缺证和撤回可阻断：draft/missing-eval/demo assets report concrete blockers."""

    def test_missing_asset_blocked(self):
        verdict = am.asset_blockers(self.conn, "strategy", "nope", 1)
        self.assertFalse(verdict["found"])
        self.assertTrue(verdict["blocked"])

    def test_draft_demo_chain_blocked(self):
        result = am.seed_demo(self.conn)
        self.assertEqual(len(result["inserted"]), DEMO_KIND_COUNT)
        verdict = am.asset_blockers(self.conn, "interaction_profile",
                                    "demo-profile-support", 1)
        codes = {b["code"] for b in verdict["blockers"]}
        self.assertTrue(codes <= {"ASB-Draft", "ASB-EvidenceInsufficient",
                                  "ASB-ReviewMissing", "ASB-NotEligible",
                                  "ASB-DemoAsset"})
        self.assertIn("ASB-Draft", codes)
        self.assertFalse(verdict["usable"])

    def test_missing_evaluation_refs_block(self):
        # strategies may omit evaluation_refs (methods/profiles cannot);
        # the missing citation must surface as a concrete runtime blocker
        self.insert("strategy", strategy_record(evaluation_refs=[]))
        verdict = am.asset_blockers(self.conn, "strategy",
                                    "test-strategy-generic", 1)
        self.assertIn("ASB-EvalMissing", {b["code"] for b in verdict["blockers"]})

    def test_evaluation_case_itself_needs_no_evaluation_refs(self):
        am.seed_demo(self.conn)
        verdict = am.asset_blockers(self.conn, "evaluation_case",
                                    "demo-eval-e01-clarify", 1)
        self.assertNotIn("ASB-EvalMissing", {b["code"] for b in verdict["blockers"]})


class ConditionPrecheckTests(AssetModelTestsBase):
    """未知条件不按 true 执行；信息前提、拒绝与排除分支可判定。"""

    def setUp(self):
        super().setUp()
        self.insert("evaluation_case", case_record())
        self.method = method_record(
            applies_when=[{"information": "task_content", "expect": "available",
                           "on_unknown": "needs_information"}],
            excludes_when=[{"information": "exhaustion_signal", "expect": "available",
                            "on_unknown": "block"}])

    def test_missing_required_information_blocks(self):
        verdict = am.condition_precheck(self.method, set())
        self.assertFalse(verdict["can_proceed"])
        self.assertIn("task_content", verdict["needs_information"])

    def test_resolved_conditions_proceed(self):
        verdict = am.condition_precheck(self.method,
                                        {"task_content", "!exhaustion_signal"})
        self.assertTrue(verdict["can_proceed"])
        self.assertEqual(verdict["blocked"], [])
        self.assertEqual(verdict["needs_information"], [])

    def test_unknown_condition_never_proceeds_as_true(self):
        verdict = am.condition_precheck(self.method, {"task_content"})
        # exhaustion_signal is unconfirmed → unknown → on_unknown=block
        self.assertFalse(verdict["can_proceed"])
        self.assertTrue(any("never treated as true" in b["detail"]
                            for b in verdict["blocked"]))

    def test_confirmed_exclusion_condition_blocks(self):
        verdict = am.condition_precheck(self.method,
                                        {"task_content", "exhaustion_signal"})
        self.assertFalse(verdict["can_proceed"])
        self.assertTrue(any("excludes_when" in b["detail"] for b in verdict["blocked"]))

    def test_violated_expectation_blocks(self):
        method = method_record(
            applies_when=[{"information": "guardian_consent", "expect": "absent",
                           "on_unknown": "block"}])
        verdict = am.condition_precheck(method, {"guardian_consent"})
        self.assertFalse(verdict["can_proceed"])
        self.assertEqual(len(verdict["violated"]), 1)

    def test_needs_information_on_unknown(self):
        verdict = am.condition_precheck(self.method, set())
        unknown_conditions = {u["condition"] for u in verdict["unknown"]}
        self.assertIn("exhaustion_signal", unknown_conditions)
        self.assertIn("task_content", verdict["needs_information"])


class SeedDemoTests(DemoChainTestsBase):
    """交付范围 #5: the minimal synthetic demo chain seeds idempotently and
    stays draft / insufficient / demo-only."""

    def test_seed_inserts_full_chain(self):
        result = am.seed_demo(self.conn)
        self.assertEqual(len(result["inserted"]), DEMO_KIND_COUNT)
        kinds = {entry["kind"] for entry in result["inserted"]}
        self.assertEqual(kinds, set(am.KINDS))
        ids = {entry["asset_ref"].split("@")[0] for entry in result["inserted"]}
        self.assertIn("demo-strategy-learning-support", ids)
        self.assertIn("demo-strategy-interest-exploration", ids)
        self.assertIn("demo-method-clarify", ids)
        self.assertIn("demo-profile-support", ids)

    def test_reseed_is_idempotent(self):
        am.seed_demo(self.conn)
        again = am.seed_demo(self.conn)
        self.assertEqual(again["inserted"], [])
        self.assertEqual(len(again["already_present"]), DEMO_KIND_COUNT)

    def test_seed_refuses_library_with_works(self):
        self.conn.execute(
            "INSERT INTO works (internal_id, title, record_status)"
            " VALUES ('lt-x', 'synthetic work', 'ingested')")
        self.conn.commit()
        with self.assertRaises(am.AssetsError) as ctx:
            am.seed_demo(self.conn)
        self.assertIn("synthetic-only", str(ctx.exception))

    def test_demo_chain_honesty_markers(self):
        am.seed_demo(self.conn)
        for kind in am.KINDS:
            rows = self.conn.execute(
                f"SELECT lifecycle_status, release_eligibility, basis_sufficiency,"
                f" demo_only FROM {am.TABLES[kind]}").fetchall()
            self.assertTrue(rows)
            for lifecycle, eligible, sufficiency, demo_only in rows:
                self.assertEqual(lifecycle, "draft")
                self.assertEqual(eligible, "not_eligible")
                self.assertEqual(sufficiency, "insufficient")
                self.assertEqual(demo_only, 1)
        profile = am.get_record(self.conn, "interaction_profile",
                                "demo-profile-support", 1)
        self.assertEqual(profile["runtime_effect"], "new_version_release")
        self.assertEqual(profile["basis_kind"], "design_choice")

    def test_demo_profile_evaluation_closure(self):
        am.seed_demo(self.conn)
        profile = am.get_record(self.conn, "interaction_profile",
                                "demo-profile-support", 1)
        for ref in profile["evaluation_refs"]:
            case = am.get_record(self.conn, "evaluation_case",
                                 ref["case_id"], ref["revision"])
            self.assertIsNotNone(case)
            self.assertTrue(any(entry["asset_id"] == profile["asset_id"]
                                and entry["revision"] == profile["revision"]
                                for entry in case["covers"]))

    def test_demo_content_hashes_verify(self):
        """Every stored demo record's content hash recomputes exactly."""
        am.seed_demo(self.conn)
        for kind in am.KINDS:
            for row in self.conn.execute(
                    f"SELECT asset_id, revision FROM {am.TABLES[kind]}").fetchall():
                record = am.get_record(self.conn, kind, row[0], row[1])
                self.assertEqual(record["content_hash"],
                                 am.compute_content_hash(record), (kind, row))


class IndependentInstallTests(unittest.TestCase):
    """The packaged schemas load and validate outside the source tree."""

    def test_contract_load_and_validate_outside_source_tree(self):
        root = make_tmp_dir("am-inst-")
        self.addCleanup(shutil.rmtree, root, True)
        src = Path(__file__).resolve().parents[1] / "src" / "research_library"
        install_root = root / "site"
        install_root.mkdir()
        shutil.copytree(src, install_root / "research_library",
                        ignore=shutil.ignore_patterns("__pycache__"))
        script = (
            "import sys, json;"
            "sys.path.insert(0, r'{root}');"
            "from research_library import assets as am;"
            "record = am.load_schema('interaction_profile') and "
            "json.loads(open(r'{fixture}', encoding='utf-8').read());"
            "errors = am.validate_record('interaction_profile', record['record'] "
            "if 'record' in record else record);"
            "print(json.dumps(errors));"
        ).format(root=str(install_root), fixture=str(
            Path(__file__).resolve().parents[1] / "src" / "research_library" /
            "contracts" / "assets" / "fixtures" / "profile-demo-support.json"))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(install_root)
        output = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env,
            cwd=str(root), check=True)
        self.assertEqual(json.loads(output.stdout.strip()), [])


class AssetCliTests(AssetModelTestsBase):
    """Reproducible commands: research assets migrate/validate/seed-demo/show/blockers."""

    def setUp(self):
        super().setUp()
        self.demo_db = self.root / "demo" / "demo.sqlite"
        self.demo_db.parent.mkdir(parents=True, exist_ok=True)

    def run_cli(self, *argv):
        return cli_main(list(argv))

    def test_migrate_creates_backup_and_verifies(self):
        target = self.root / "migrate-me.sqlite"
        sqlite3.connect(str(target)).close()
        code = self.run_cli("assets", "migrate", "--db", str(target))
        self.assertEqual(code, 0)
        backups = list((target.parent / "backups").glob("pre-assets-migration-*.sqlite"))
        self.assertTrue(backups)

    def test_validate_file(self):
        path = self.root / "record.json"
        path.write_text(json.dumps(
            {"kind": "strategy", "record": strategy_record()}, ensure_ascii=False),
            encoding="utf-8")
        code = self.run_cli("assets", "validate", "--file", str(path))
        self.assertEqual(code, 0)
        path.write_text(json.dumps(
            {"kind": "strategy", "record": strategy_record(asset_id="Bad!")}),
            encoding="utf-8")
        self.assertEqual(self.run_cli("assets", "validate", "--file", str(path)), 2)

    def test_seed_demo_show_blockers(self):
        self.assertEqual(self.run_cli(
            "assets", "seed-demo", "--db", str(self.demo_db)), 0)
        self.assertEqual(self.run_cli(
            "assets", "show", "--kind", "interaction_profile",
            "--asset-id", "demo-profile-support", "--revision", "1",
            "--db", str(self.demo_db)), 0)
        self.assertEqual(self.run_cli(
            "assets", "blockers", "--kind", "interaction_profile",
            "--asset-id", "demo-profile-support", "--revision", "1",
            "--db", str(self.demo_db)), 0)

    def test_seed_demo_requires_explicit_db(self):
        self.assertEqual(self.run_cli("assets", "seed-demo"), 2)

    def test_seed_demo_refuses_production_like_library(self):
        self.assertEqual(self.run_cli(
            "assets", "seed-demo", "--db", str(self.db_path)), 2)

    def test_blockers_missing_asset(self):
        self.assertEqual(self.run_cli(
            "assets", "blockers", "--kind", "strategy",
            "--asset-id", "ghost", "--revision", "1",
            "--db", str(self.demo_db)), 0)


if __name__ == "__main__":
    unittest.main()
