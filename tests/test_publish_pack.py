"""Offline synthetic tests for the minimal private capability pack publisher
and retraction mechanism (Issue #16).

Covers the four acceptance criteria of Issue #16:

1. whitelist negative tests: abstracts, full text, ``raw_sources``, local
   paths, credentials, child records and unqualified assets are rejected
   (PUB-Whitelist / PUB-LocalPath / PUB-Secret / PUB-Eligibility);
2. missing citations, tampering, duplicate ids, incompatible versions and
   mixed versions all fail; hashes and the manifest are recomputable
   (PUB-Closure / PUB-Covers / PUB-Hash / PUB-Dup / PUB-MixedRevision /
   PUB-Runner / PUB-Manifest);
3. a clean environment reads the minimal pack, failed activation leaves no
   half version, and rolling back to an older pack cannot revive a withdrawn
   asset (independent retraction ledger precedence);
4. docs and reproducible commands ship with the offline tests (see
   ``docs/publish/PACK-MODEL.md``; this file is the executable half).

All fixtures are synthetic (``lt-fixture*`` / ``test-*`` ids); no network, no
model calls, no real publication content, and the production database under
data/ is never touched.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import unittest

from helpers import make_tmp_dir

from research_library import assets as am
from research_library import db, evidence as ev, publish as pub
from research_library.cli import main as cli_main

BUILT_AT = "2026-10-19T00:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures (synthetic library + eligible asset chain)
# ---------------------------------------------------------------------------

def _prepared(kind, record):
    prepared = am.prepared_record(kind, record)
    prepared.setdefault("content_hash", am.compute_content_hash(prepared))
    return prepared


def eval_case_record(asset_id, revision, case_id="test-eval-a", case_revision=1,
                     **changes):
    record = {
        "schema_version": am.SCHEMA_VERSION,
        "asset_id": case_id,
        "revision": case_revision,
        "title": "Test evaluation case (synthetic)",
        "created_by": "test-fixture",
        "created_at": BUILT_AT,
        "basis_kind": "design_choice",
        "basis_sufficiency": "insufficient",
        "basis_refs": [{"ref_kind": "design_note", "ref": "docs/notes.md",
                        "note": "synthetic design note"}],
        "demo_only": False,
        "review_origin": "single_human",
        "review_status": "human_reviewed",
        "technical_validation": "passed",
        "scientific_appraisal": "done",
        "release_eligibility": "eligible",
        "lifecycle_status": "released",
        "fixture_kind": "synthetic",
        "input_fixture": {"intent": "help_with_current_task",
                          "content": "synthetic task fixture"},
        "expected_behaviors": ["asks a clarification question first"],
        "forbidden_behaviors": ["labels the child"],
        "scoring_basis": "synthetic checklist; no clinical meaning",
        "covers": [{"asset_id": asset_id, "revision": revision}],
    }
    record.update(changes)
    return record


def strategy_record(asset_id="test-strategy-a", revision=1, supersedes=None,
                    eval_ids=(("test-eval-a", 1),), extra_basis_refs=(), **changes):
    record = {
        "schema_version": am.SCHEMA_VERSION,
        "asset_id": asset_id,
        "revision": revision,
        "title": "Test strategy (synthetic, eligible)",
        "created_by": "test-fixture",
        "created_at": BUILT_AT,
        "basis_kind": "application_inference",
        "basis_sufficiency": "insufficient",
        "basis_refs": [
            {"ref_kind": "work", "ref": "lt-fixture01",
             "note": "synthetic citation to the fixture work"},
            *extra_basis_refs,
        ],
        "evaluation_refs": [{"case_id": case_id, "revision": case_revision}
                            for case_id, case_revision in eval_ids],
        "demo_only": False,
        "review_origin": "single_human",
        "review_status": "human_reviewed",
        "technical_validation": "passed",
        "scientific_appraisal": "done",
        "release_eligibility": "eligible",
        "lifecycle_status": "released",
        "goal": "support the current task (synthetic)",
        "applies_when": [{"information": "task_content", "expect": "available",
                          "on_unknown": "needs_information"}],
        "excludes_when": [{"information": "exhaustion_signal", "expect": "available",
                           "on_unknown": "block"}],
        "steps": [{"order": 1, "action": "ask_clarification", "content": "clarify"}],
        "observed_outcomes": ["task restated"],
        "adjust_when": ["no progress"],
        "stop_when": ["exhaustion"],
        "evidence_summary": "synthetic fixture marked honestly insufficient",
    }
    if supersedes is not None:
        record["supersedes_revision"] = supersedes
    record.update(changes)
    return record


class PublisherFixtureBase(unittest.TestCase):
    """A synthetic library: two works, one publishable claim + one draft claim,
    one source version/finding/relation, and an eligible strategy + eval case."""

    def setUp(self):
        self.root = make_tmp_dir("pub-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.db_path = self.root / "library.sqlite"
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        # works: one with metadata-only fields filled, one with license unknown
        self.conn.execute(
            "INSERT INTO works (internal_id, title, abstract, local_pdf_path,"
            " record_status, license) VALUES (?, ?, ?, ?, 'ingested', 'cc-by-40')",
            ("lt-fixture01", "Fixture Work One (synthetic, not a real publication)",
             "Library abstract that must never leave the library (synthetic)",
             "C:\\library\\pdf\\fixture01.pdf"))
        self.conn.execute(
            "INSERT INTO works (internal_id, title, record_status) VALUES (?, ?, 'ingested')",
            ("lt-fixture02", "Fixture Work Two (synthetic, license unknown)"))
        self.conn.commit()
        # evidence: publishable claim (eligible appraisal) + unappraised claim
        ev.insert_record(self.conn, "claim", {
            "schema_version": ev.SCHEMA_VERSION, "claim_id": "c-fixture01",
            "statement": "Synthetic claim fixture (no research meaning)"})
        ev.insert_record(self.conn, "claim", {
            "schema_version": ev.SCHEMA_VERSION, "claim_id": "c-fixture02",
            "statement": "Unappraised synthetic claim (stays out of packs)"})
        ev.insert_record(self.conn, "appraisal", {
            "schema_version": ev.SCHEMA_VERSION, "appraisal_id": "ap-fixture01",
            "target_kind": "claim", "target_id": "c-fixture01",
            "quality": "medium", "biases": "synthetic bias note",
            "limitations": "synthetic limitation note",
            "applicability": "synthetic applicability note",
            "review_origin": "single_human", "review_status": "human_reviewed",
            "release_eligibility": "eligible", "created_at": BUILT_AT})
        self.conn.commit()

    def insert_asset(self, kind, record, conn=None):
        return am.insert_record(conn or self.conn, kind, _prepared(kind, record))

    def seed_eligible_chain(self, asset_id="test-strategy-a", eval_id="test-eval-a",
                            claim_ref=None):
        extra = ()
        if claim_ref:
            extra = ({"ref_kind": "claim", "ref": claim_ref,
                      "note": "synthetic citation to the fixture claim"},)
        self.insert_asset("evaluation_case",
                          eval_case_record(asset_id, 1, case_id=eval_id))
        stored = self.insert_asset(
            "strategy", strategy_record(asset_id=asset_id,
                                        eval_ids=((eval_id, 1),),
                                        extra_basis_refs=extra))
        return stored

    def seed_revision_two(self, asset_id="test-strategy-a", eval_id="test-eval-a"):
        """Append asset revision 2 with its own covering evaluation case."""
        self.insert_asset("evaluation_case", eval_case_record(
            asset_id, 2, case_id=eval_id, case_revision=2, supersedes_revision=1,
            covers=[{"asset_id": asset_id, "revision": 2}]))
        self.insert_asset("strategy", strategy_record(
            asset_id=asset_id, revision=2, supersedes=1,
            eval_ids=((eval_id, 2),)))

    # -- pack helpers -------------------------------------------------------

    def build(self, version, mode="release", conn=None):
        return pub.build_pack(conn or self.conn, version, mode=mode,
                              packs_dir=self.root / "packs", built_at=BUILT_AT)

    def restamp(self, pack_dir):
        """Recompute file hashes/counts/pack_hash after editing pack files.

        This simulates an attacker who re-stamps the manifest after tampering:
        content-level detection must still fire.
        """
        pack_dir = Path(pack_dir)
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        records_by_file = {}
        for name in pub.JSONL_FILES:
            path = pack_dir / name
            if not path.exists():
                continue
            records_by_file[name] = [json.loads(line) for line in
                                     path.read_text(encoding="utf-8").splitlines()
                                     if line.strip()]
        projection = pub._expected_projection(records_by_file)
        manifest["files"] = projection["files"]
        manifest["counts"] = projection["counts"]
        manifest["rights"] = projection["rights"]
        body = {k: v for k, v in manifest.items() if k != "pack_hash"}
        manifest["pack_hash"] = pub._pack_hash(body)
        (pack_dir / "manifest.json").write_bytes(
            (json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
             + "\n").encode("utf-8"))
        return manifest


# ---------------------------------------------------------------------------
# AC #1 — whitelist negative tests
# ---------------------------------------------------------------------------

class WhitelistTests(PublisherFixtureBase):

    def test_current_catalog_whitelist_is_valid(self):
        pub.validate_catalog_whitelist(pub.CATALOG_FIELDS)  # must not raise

    def test_fraudulent_whitelist_additions_are_rejected(self):
        for field in ("abstract", "raw_sources", "local_pdf_path", "api_key",
                      "subject_ref", "review_status", "token"):
            with self.assertRaises(pub.PublishError) as ctx:
                pub.validate_catalog_whitelist(list(pub.CATALOG_FIELDS) + [field])
            self.assertIn("PUB-Whitelist", str(ctx.exception))

    def test_scan_rejects_forbidden_field_names(self):
        for field in ("abstract", "raw_sources", "local_pdf_path", "api_key",
                      "subject_ref", "child_profile", "growth_record"):
            errors = []
            pub.scan_record({field: "x"}, "probe", errors)
            self.assertTrue(any("PUB-Whitelist" in e for e in errors), field)

    def test_scan_allows_asset_review_envelope_fields(self):
        # review_status/limitations are legitimate asset/appraisal fields;
        # only catalog records must reject them (regression guard).
        errors = []
        pub.scan_record({"review_status": "human_reviewed",
                         "limitations": "synthetic"}, "asset", errors)
        self.assertEqual(errors, [])
        errors = []
        pub.scan_record({"review_status": "unreviewed"}, "catalog", errors,
                        catalog_record=True)
        self.assertTrue(any("PUB-Whitelist" in e for e in errors))

    def test_scan_rejects_local_paths(self):
        for value in (r"C:\Users\lybym\secret.txt", "C:/library/pdf/x.pdf",
                      "\\\\server\\share\\x.pdf", "/home/agent/notes.pdf",
                      "see file at /Users/lybym/x.pdf"):
            errors = []
            pub.scan_record({"note": value}, "probe", errors)
            self.assertTrue(any("PUB-LocalPath" in e for e in errors), value)

    def test_scan_rejects_credentials(self):
        for value in ("gho_" + "a" * 30, "sk-" + "b" * 30,
                      "AKIA" + "IOS7" + "X" * 12,
                      "-----BEGIN RSA PRIVATE KEY-----"):
            errors = []
            pub.scan_record({"note": value}, "probe", errors)
            self.assertTrue(any("PUB-Secret" in e for e in errors), value)

    def test_unqualified_assets_are_excluded_from_release_pack(self):
        # draft strategy stays in the library; only the eligible chain ships
        self.seed_eligible_chain()
        self.insert_asset("evaluation_case",
                          eval_case_record("test-strategy-draft", 1,
                                           case_id="test-eval-draft",
                                           lifecycle_status="draft",
                                           release_eligibility="not_eligible",
                                           review_origin=None,
                                           review_status="not_reviewed",
                                           technical_validation="not_run",
                                           scientific_appraisal="not_done"))
        self.insert_asset("strategy", strategy_record(
            asset_id="test-strategy-draft", eval_ids=(("test-eval-draft", 1),),
            release_eligibility="not_eligible", lifecycle_status="draft"))
        report = self.build("2026.10.19-r1")
        self.assertEqual(report["counts"]["strategy"], 1)
        self.assertEqual(report["excluded"]["strategy"], 1)
        pack_dir = Path(report["pack_dir"])
        ids = [json.loads(line)["asset_id"] for line in
               (pack_dir / "strategies.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
        self.assertEqual(ids, ["test-strategy-a"])

    def test_demo_asset_is_excluded_from_release_pack(self):
        self.seed_eligible_chain()
        self.insert_asset("evaluation_case",
                          eval_case_record("demo-strategy-x", 1,
                                           case_id="demo-eval-x", demo_only=True,
                                           lifecycle_status="draft",
                                           release_eligibility="not_eligible",
                                           review_origin=None,
                                           review_status="not_reviewed",
                                           technical_validation="not_run",
                                           scientific_appraisal="not_done"))
        self.insert_asset("strategy", strategy_record(
            asset_id="demo-strategy-x", eval_ids=(("demo-eval-x", 1),),
            demo_only=True, lifecycle_status="draft",
            release_eligibility="not_eligible", review_origin=None,
            review_status="not_reviewed", technical_validation="not_run",
            scientific_appraisal="not_done"))
        report = self.build("2026.10.19-r1")
        self.assertEqual(report["counts"]["strategy"], 1)
        pack_dir = Path(report["pack_dir"])
        ids = [json.loads(line)["asset_id"] for line in
               (pack_dir / "strategies.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
        self.assertNotIn("demo-strategy-x", ids)

    def test_verify_rejects_wrong_content_class_records(self):
        # craft a pack that claims research_assets but carries demo fixtures:
        # the pack-level qualification scan must refuse it (AC #1)
        conn = db.connect(self.root / "demo.sqlite")
        self.addCleanup(conn.close)
        am.seed_demo(conn)
        report = self.build("2026.10.19-d1", mode="synthetic_demo", conn=conn)
        pack_dir = Path(report["pack_dir"])
        manifest_path = pack_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["content_class"] = "research_assets"
        body = {k: v for k, v in manifest.items() if k != "pack_hash"}
        manifest["pack_hash"] = pub._pack_hash(body)
        manifest_path.write_bytes(
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        result = pub.verify_pack(pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Eligibility" in e for e in result["errors"]),
                        result["errors"])

    def test_demo_pack_excludes_non_demo_assets(self):
        # selection filter: a synthetic-demo pack never carries non-demo assets
        self.seed_eligible_chain()
        report = self.build("2026.10.19-d1", mode="synthetic_demo")
        self.assertEqual(report["content_class"], "synthetic_demo")
        self.assertEqual(report["counts"]["strategy"], 0)
        self.assertEqual(report["counts"]["evaluation_case"], 0)
        self.assertEqual(report["excluded"]["strategy"], 1)

    def test_demo_pack_carries_demo_fixtures_only(self):
        conn = db.connect(self.root / "demo.sqlite")
        self.addCleanup(conn.close)
        am.seed_demo(conn)
        report = self.build("2026.10.19-d1", mode="synthetic_demo", conn=conn)
        self.assertEqual(report["content_class"], "synthetic_demo")
        self.assertEqual(report["counts"]["catalog"], 0)
        self.assertEqual(report["counts"]["evidence_cards"], 0)
        self.assertEqual(report["counts"]["strategy"], 2)

    def test_manifest_with_injected_api_key_fails_verification(self):
        self.seed_eligible_chain()
        report = self.build("2026.10.19-r1")
        pack_dir = Path(report["pack_dir"])
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["api_key"] = "leaked"
        (pack_dir / "manifest.json").write_bytes(
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        result = pub.verify_pack(pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Manifest" in e for e in result["errors"]))

    def test_manifest_with_local_path_value_fails_verification(self):
        self.seed_eligible_chain()
        report = self.build("2026.10.19-r1")
        pack_dir = Path(report["pack_dir"])
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["publisher"]["publisher_ref"] = r"C:\Users\lybym\publisher"
        body = {k: v for k, v in manifest.items() if k != "pack_hash"}
        manifest["pack_hash"] = pub._pack_hash(body)
        (pack_dir / "manifest.json").write_bytes(
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        result = pub.verify_pack(pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-LocalPath" in e for e in result["errors"]))

    def test_packaged_catalog_is_projected_whitelist(self):
        self.seed_eligible_chain()
        report = self.build("2026.10.19-r1")
        pack_dir = Path(report["pack_dir"])
        records = [json.loads(line) for line in
                   (pack_dir / "catalog.jsonl").read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        self.assertEqual([r["internal_id"] for r in records], ["lt-fixture01"])
        entry = records[0]
        self.assertNotIn("abstract", entry)
        self.assertNotIn("raw_sources", entry)
        self.assertNotIn("local_pdf_path", entry)
        self.assertEqual(set(entry), set(pub.CATALOG_FIELDS))
        self.assertEqual(entry["license"], "cc-by-40")


# ---------------------------------------------------------------------------
# AC #2 — integrity: closure, tampering, duplicates, mixed versions, compat
# ---------------------------------------------------------------------------

class ReleasePackTests(PublisherFixtureBase):

    def test_release_pack_includes_closure_and_cards(self):
        self.seed_eligible_chain(claim_ref="c-fixture01")
        report = self.build("2026.10.19-r1")
        self.assertEqual(report["content_class"], "research_assets")
        self.assertEqual(report["counts"],
                         {"catalog": 1, "evidence_cards": 1, "strategy": 1,
                          "support_method": 0, "interaction_profile": 0,
                          "evaluation_case": 1})
        pack_dir = Path(report["pack_dir"])
        cards = [json.loads(line) for line in
                 (pack_dir / "evidence-cards.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        card = cards[0]
        self.assertEqual(card["claim"]["claim_id"], "c-fixture01")
        self.assertEqual(card["appraisals"][0]["release_eligibility"], "eligible")
        self.assertEqual(card["source_versions"], [])  # no finding chain in this fixture
        self.assertEqual(report["rights"]["license_unknown_count"], 0)

    def test_cited_work_missing_from_library_fails_build(self):
        # layered defense: the asset layer already refuses fabricated research
        # citations at insert time (AS-BasisRef); the publisher additionally
        # refuses closure targets that exist but are not ingested (see
        # test_cited_work_not_ingested_fails_build).
        self.insert_asset("evaluation_case", eval_case_record("test-strategy-a", 1))
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert_asset("strategy", strategy_record(extra_basis_refs=(
                {"ref_kind": "work", "ref": "lt-missing",
                 "note": "synthetic citation to a non-existent work"},)))
        self.assertIn("AS-BasisRef", str(ctx.exception))

    def test_cited_work_not_ingested_fails_build(self):
        self.conn.execute(
            "INSERT INTO works (internal_id, title, record_status)"
            " VALUES (?, ?, 'candidate')",
            ("lt-candidate01", "Candidate Work (synthetic)"))
        self.conn.commit()
        self.insert_asset("evaluation_case", eval_case_record("test-strategy-a", 1))
        self.insert_asset("strategy", strategy_record(extra_basis_refs=(
            {"ref_kind": "work", "ref": "lt-candidate01",
             "note": "synthetic citation to a non-ingested work"},)))
        with self.assertRaises(pub.PublishError) as ctx:
            self.build("2026.10.19-r1")
        self.assertIn("PUB-Closure", str(ctx.exception))

    def test_cited_claim_without_card_fails_build(self):
        self.seed_eligible_chain(claim_ref="c-fixture02")  # unappraised claim
        with self.assertRaises(pub.PublishError) as ctx:
            self.build("2026.10.19-r1")
        self.assertIn("PUB-Closure", str(ctx.exception))
        self.assertIn("c-fixture02", str(ctx.exception))

    def test_evaluation_ref_to_missing_case_fails_build(self):
        # layered defense: AS-EvalRef refuses the dangling evaluation citation
        # at insert time; the publisher re-checks closure inside every pack.
        with self.assertRaises(am.AssetsError) as ctx:
            self.insert_asset("strategy", strategy_record(
                eval_ids=(("test-eval-missing", 1),)))
        self.assertIn("AS-EvalRef", str(ctx.exception))

    def test_covers_to_missing_asset_fails_build(self):
        # eval case covers a strategy that is not eligible for packaging
        self.insert_asset("evaluation_case", eval_case_record("test-strategy-a", 1))
        self.insert_asset("strategy", strategy_record(
            release_eligibility="not_eligible", lifecycle_status="draft"))
        # make the strategy selection exclude the asset while the case ships:
        # package only the evaluation case by retracting the draft strategy
        am.retract_asset(self.conn, "strategy", "test-strategy-a", 1,
                         reason="synthetic withdrawal", ref="test-decision-001")
        with self.assertRaises(pub.PublishError) as ctx:
            self.build("2026.10.19-r1")
        self.assertIn("PUB-Closure", str(ctx.exception))
        self.assertIn("covers", str(ctx.exception))

    def test_unappraised_claim_never_enters_release_pack(self):
        self.seed_eligible_chain(claim_ref="c-fixture01")
        report = self.build("2026.10.19-r1")
        pack_dir = Path(report["pack_dir"])
        cards = [json.loads(line) for line in
                 (pack_dir / "evidence-cards.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        self.assertEqual([c["claim"]["claim_id"] for c in cards], ["c-fixture01"])

    def test_retracted_asset_is_never_packaged(self):
        self.seed_eligible_chain()
        am.retract_asset(self.conn, "strategy", "test-strategy-a", 1,
                         reason="synthetic withdrawal", ref="test-decision-001")
        # the covering evaluation case is withdrawn too (a release pack can
        # never contain one without the other), then the rebuild excludes both
        am.retract_asset(self.conn, "evaluation_case", "test-eval-a", 1,
                         reason="covers withdrawn strategy", ref="test-decision-001b")
        report = self.build("2026.10.19-r1")
        self.assertEqual(report["counts"]["strategy"], 0)
        self.assertEqual(report["counts"]["evaluation_case"], 0)
        self.assertEqual(report["excluded"]["strategy"], 1)
        self.assertEqual(report["excluded"]["evaluation_case"], 1)

    def test_immutability_refuses_rebuild_of_same_version(self):
        self.seed_eligible_chain()
        self.build("2026.10.19-r1")
        with self.assertRaises(pub.PublishError) as ctx:
            self.build("2026.10.19-r1")
        self.assertIn("PUB-Immutable", str(ctx.exception))


class IntegrityTests(PublisherFixtureBase):

    def setUp(self):
        super().setUp()
        self.seed_eligible_chain(claim_ref="c-fixture01")
        self.report = self.build("2026.10.19-r1")
        self.pack_dir = Path(self.report["pack_dir"])

    def test_fresh_pack_verifies_green(self):
        result = pub.verify_pack(self.pack_dir)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["pack_hash"], self.report["pack_hash"])

    def test_manifest_projection_is_deterministic(self):
        again = self.build("2026.10.19-r1-copy")  # same records, pinned built_at
        first = json.loads((self.pack_dir / "manifest.json").read_text(encoding="utf-8"))
        second = json.loads((Path(again["pack_dir"]) / "manifest.json").read_text(encoding="utf-8"))
        # identical record sets must rebuild identical file hashes/counts/rights
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(first["rights"], second["rights"])

    def test_tampered_file_byte_is_detected(self):
        strategies = self.pack_dir / "strategies.jsonl"
        data = strategies.read_bytes()
        strategies.write_bytes(data.replace(b"clarify", b"CLARIFY", 1))
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Hash" in e for e in result["errors"]))

    def test_tampered_record_with_restamped_manifest_is_detected(self):
        # Replace the strategy title AND re-stamp file hash + pack_hash:
        # the record-level content hash must still catch the tampering.
        strategies = self.pack_dir / "strategies.jsonl"
        record = json.loads(strategies.read_text(encoding="utf-8").splitlines()[0])
        record["title"] = "Tampered title"
        strategies.write_bytes((json.dumps(record, ensure_ascii=False,
                                           sort_keys=True) + "\n").encode("utf-8"))
        self.restamp(self.pack_dir)
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Record" in e and "AS-Hash" in e
                            for e in result["errors"]),
                        result["errors"])

    def test_duplicate_catalog_id_is_detected(self):
        catalog = self.pack_dir / "catalog.jsonl"
        line = catalog.read_text(encoding="utf-8").splitlines()[0]
        catalog.write_bytes((line + "\n" + line + "\n").encode("utf-8"))
        self.restamp(self.pack_dir)
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Dup" in e for e in result["errors"]))

    def test_same_asset_id_in_two_kinds_is_detected(self):
        # the same asset id may not travel under two asset kinds
        strategies = (self.pack_dir / "strategies.jsonl").read_text(encoding="utf-8")
        (self.pack_dir / "methods.jsonl").write_bytes(strategies.encode("utf-8"))
        self.restamp(self.pack_dir)
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Dup" in e for e in result["errors"]),
                        result["errors"])

    def test_mixed_revisions_are_detected(self):
        # craft a second revision of the same asset inside the pack file
        strategies = self.pack_dir / "strategies.jsonl"
        first = json.loads(strategies.read_text(encoding="utf-8").splitlines()[0])
        second = dict(first)
        second["revision"] = 2
        second["supersedes_revision"] = 1
        second["content_hash"] = am.compute_content_hash(second)
        payload = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                          for r in (first, second))
        strategies.write_bytes(payload.encode("utf-8"))
        self.restamp(self.pack_dir)
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-MixedRevision" in e for e in result["errors"]))

    def test_missing_citation_detected_by_verify(self):
        # remove the cited work from the catalog + restamp: closure must fail
        catalog = self.pack_dir / "catalog.jsonl"
        catalog.write_bytes(b"")
        self.restamp(self.pack_dir)
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Closure" in e for e in result["errors"]))

    def test_incompatible_pack_schema_version_fails(self):
        manifest_path = self.pack_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        body = {k: v for k, v in manifest.items() if k != "pack_hash"}
        body["schema_version"] = "ce.pack/2"
        manifest = {**body, "pack_hash": pub._pack_hash(body)}
        manifest_path.write_bytes(
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Manifest" in e or "PUB-Schema" in e
                            for e in result["errors"]))

    def test_runner_below_pack_minimum_fails(self):
        result = pub.verify_pack(self.pack_dir, runner_version="0.0.9")
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Runner" in e for e in result["errors"]))
        ok = pub.verify_pack(self.pack_dir, runner_version="0.1.0")
        self.assertTrue(ok["ok"])

    def test_foreign_file_is_detected(self):
        (self.pack_dir / "stowaway.json").write_text("{}", encoding="utf-8")
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-ForeignFile" in e for e in result["errors"]))

    def test_missing_file_is_detected(self):
        (self.pack_dir / "methods.jsonl").unlink()
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Hash" in e for e in result["errors"]))

    def test_non_object_record_is_reported_not_crash(self):
        # a malformed (non-object) jsonl line is a reported error, never an
        # unhandled crash of the verifier
        (self.pack_dir / "catalog.jsonl").write_bytes(b'["not","an","object"]\n')
        self.restamp(self.pack_dir)
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Manifest" in e for e in result["errors"]))

    def test_counts_mismatch_is_detected(self):
        manifest_path = self.pack_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["counts"]["strategy"] = 99
        manifest_path.write_bytes(
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
        result = pub.verify_pack(self.pack_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PUB-Manifest" in e for e in result["errors"]))

    def test_diff_reports_changes_between_snapshots(self):
        self.seed_revision_two()
        report2 = self.build("2026.10.19-r2")
        diff = pub.diff_packs(self.pack_dir, Path(report2["pack_dir"]))
        changed_ids = {entry["asset_id"] for entry in diff["assets_changed"]}
        self.assertIn("test-strategy-a", changed_ids)
        strategy_change = next(entry for entry in diff["assets_changed"]
                               if entry["asset_id"] == "test-strategy-a")
        self.assertEqual(strategy_change["from"]["revision"], 1)
        self.assertEqual(strategy_change["to"]["revision"], 2)
        self.assertEqual(diff["assets_added"], [])
        self.assertEqual(diff["assets_removed"], [])


# ---------------------------------------------------------------------------
# AC #3 — clean-environment read, atomic activation, retraction precedence
# ---------------------------------------------------------------------------

class ActivationTests(PublisherFixtureBase):
    """Reads and activations without any database connection."""

    def _consumer(self, name="consumer"):
        return self.root / name

    def test_activate_and_read_active_pack(self):
        self.seed_eligible_chain(claim_ref="c-fixture01")
        report = self.build("2026.10.19-r1")
        pub.activate_pack(Path(report["pack_dir"]), self._consumer())
        status = pub.pack_status(self._consumer())
        self.assertEqual(status["pack_id"], "ce-pack-2026.10.19-r1")
        self.assertEqual(status["content_class"], "research_assets")
        self.assertFalse(status["eligible_for_real_user_delivery"])
        self.assertEqual(status["publisher"]["credentials_embedded"], False)
        self.assertEqual(status["retraction_count"], 0)

    def test_clean_environment_reads_copied_pack(self):
        # copy the pack far away from the build tree; read it with no database
        self.seed_eligible_chain()
        report = self.build("2026.10.19-r1")
        clean = self.root / "clean-room" / "pack-copy"
        shutil.copytree(Path(report["pack_dir"]), clean)
        result = pub.verify_pack(clean)
        self.assertTrue(result["ok"], result["errors"])
        consumer = self.root / "clean-room" / "consumer"
        pub.activate_pack(clean, consumer)
        status = pub.pack_status(consumer)
        self.assertEqual(status["counts"]["strategy"], 1)

    def test_failed_activation_leaves_previous_version_active(self):
        self.seed_eligible_chain()
        v1 = self.build("2026.10.19-r1")
        consumer = self._consumer()
        pub.activate_pack(Path(v1["pack_dir"]), consumer)
        active_before = (consumer / "ACTIVE.json").read_bytes()
        # a tampered v2 must be refused before anything is committed
        v2 = self.build("2026.10.19-r2")
        v2_dir = Path(v2["pack_dir"])
        strategies = v2_dir / "strategies.jsonl"
        record = json.loads(strategies.read_text(encoding="utf-8").splitlines()[0])
        record["title"] = "Tampered"
        strategies.write_bytes((json.dumps(record, ensure_ascii=False,
                                           sort_keys=True) + "\n").encode("utf-8"))
        with self.assertRaises(pub.PublishError) as ctx:
            pub.activate_pack(v2_dir, consumer)
        self.assertIn("PUB-Hash", str(ctx.exception))
        self.assertEqual((consumer / "ACTIVE.json").read_bytes(), active_before)
        self.assertFalse((consumer / "packs" / "ce-pack-2026.10.19-r2").exists())
        status = pub.pack_status(consumer)
        self.assertEqual(status["pack_id"], "ce-pack-2026.10.19-r1")

    def test_swapped_pack_directory_is_refused_on_read(self):
        # activate two identical-content packs, then swap the active directory's
        # content back to the older pack: the active pointer must refuse it.
        self.seed_eligible_chain()
        v1 = self.build("2026.10.19-r1")
        v2 = self.build("2026.10.19-r2")
        consumer = self._consumer()
        pub.activate_pack(Path(v1["pack_dir"]), consumer)
        pub.activate_pack(Path(v2["pack_dir"]), consumer)
        active = json.loads((consumer / "ACTIVE.json").read_text(encoding="utf-8"))
        self.assertEqual(active["pack_id"], "ce-pack-2026.10.19-r2")
        v2_dir = consumer / "packs" / "ce-pack-2026.10.19-r2"
        shutil.rmtree(v2_dir)
        shutil.copytree(Path(v1["pack_dir"]), v2_dir)
        with self.assertRaises(pub.PublishError) as ctx:
            pub.pack_status(consumer)
        self.assertIn("PUB-Active", str(ctx.exception))

    def test_no_active_pack_is_reported(self):
        with self.assertRaises(pub.PublishError) as ctx:
            pub.pack_status(self._consumer("empty-consumer"))
        self.assertIn("PUB-Active", str(ctx.exception))


class RetractionTests(PublisherFixtureBase):

    def _activate_version(self, version):
        report = self.build(version)
        pub.activate_pack(Path(report["pack_dir"]), self.root / "consumer")
        return report

    def test_retraction_blocks_asset_in_active_pack(self):
        self.seed_eligible_chain()
        self._activate_version("2026.10.19-r1")
        consumer = self.root / "consumer"
        resolved = pub.resolve_assets(consumer)
        self.assertEqual(resolved["usable_count"], 2)  # strategy + eval case
        pub.append_retraction(consumer, asset_id="test-strategy-a",
                              reason="synthetic withdrawal drill",
                              decision_ref="test-decision-001")
        resolved = pub.resolve_assets(consumer)
        target = next(a for a in resolved["assets"] if a["asset_id"] == "test-strategy-a")
        self.assertFalse(target["usable"])
        self.assertTrue(any(b["code"] == "PUB-Retracted" for b in target["blockers"]))
        self.assertEqual(resolved["retraction_count"], 1)
        # ledger update is independent of the active version
        status = pub.pack_status(consumer)
        self.assertEqual(status["pack_id"], "ce-pack-2026.10.19-r1")
        self.assertEqual(status["retraction_count"], 1)

    def test_revision_scoped_retraction_leaves_other_revisions_usable(self):
        self.seed_eligible_chain()
        self.seed_revision_two()
        self._activate_version("2026.10.19-r2")  # contains strategy@2
        consumer = self.root / "consumer"
        pub.append_retraction(consumer, asset_id="test-strategy-a", revision=2,
                              reason="synthetic revision-scoped withdrawal",
                              decision_ref="test-decision-002")
        resolved = pub.resolve_assets(consumer)
        target = next(a for a in resolved["assets"] if a["asset_id"] == "test-strategy-a")
        self.assertFalse(target["usable"])

    def test_rollback_cannot_revive_withdrawn_asset(self):
        # v1 carries strategy@1; v2 carries strategy@2 (v1's copy becomes
        # superseded in the library but v1's pack file is immutable).
        self.seed_eligible_chain()
        self._activate_version("2026.10.19-r1")
        self.seed_revision_two()
        self._activate_version("2026.10.19-r2")
        consumer = self.root / "consumer"
        pub.append_retraction(consumer, asset_id="test-strategy-a",
                              reason="synthetic asset-wide withdrawal",
                              decision_ref="test-decision-003")
        resolved = pub.resolve_assets(consumer)
        target = next(a for a in resolved["assets"] if a["asset_id"] == "test-strategy-a")
        self.assertFalse(target["usable"])
        # roll back to v1 (pack file still contains strategy@1):
        v1_dir = self.root / "packs" / "ce-pack-2026.10.19-r1"
        pub.activate_pack(v1_dir, consumer)
        status = pub.pack_status(consumer)
        self.assertEqual(status["pack_id"], "ce-pack-2026.10.19-r1")
        resolved = pub.resolve_assets(consumer)
        target = next(a for a in resolved["assets"] if a["asset_id"] == "test-strategy-a")
        self.assertFalse(target["usable"])
        self.assertTrue(any(b["code"] == "PUB-Retracted" for b in target["blockers"]))

    def test_duplicate_withdrawal_is_rejected(self):
        self.seed_eligible_chain()
        self._activate_version("2026.10.19-r1")
        consumer = self.root / "consumer"
        pub.append_retraction(consumer, asset_id="test-strategy-a",
                              reason="first", decision_ref="test-decision-004")
        with self.assertRaises(pub.PublishError) as ctx:
            pub.append_retraction(consumer, asset_id="test-strategy-a",
                                  reason="second", decision_ref="test-decision-005")
        self.assertIn("PUB-Retract", str(ctx.exception))
        self.assertIn("append-only", str(ctx.exception))

    def test_withdrawal_requires_reason_and_decision_ref(self):
        consumer = self.root / "consumer"
        with self.assertRaises(pub.PublishError) as ctx:
            pub.append_retraction(consumer, asset_id="test-strategy-a",
                                  reason="   ", decision_ref="ref")
        self.assertIn("PUB-Retract", str(ctx.exception))
        with self.assertRaises(pub.PublishError) as ctx:
            pub.append_retraction(consumer, asset_id="test-strategy-a",
                                  reason="a reason", decision_ref="")
        self.assertIn("PUB-Retract", str(ctx.exception))

    def test_ledger_entries_are_validated(self):
        consumer = self.root / "consumer"
        with self.assertRaises(pub.PublishError) as ctx:
            pub.append_retraction(consumer, asset_id="test-strategy-a", revision=0,
                                  reason="bad revision", decision_ref="ref")
        self.assertIn("PUB-Retract", str(ctx.exception))
        with self.assertRaises(pub.PublishError) as ctx:
            pub.append_retraction(consumer, asset_id="test-strategy-a",
                                  content_hash="not-a-hash",
                                  reason="bad hash", decision_ref="ref")
        self.assertIn("PUB-Retract", str(ctx.exception))
        pub.append_retraction(consumer, asset_id="test-strategy-a",
                              reason="ok", decision_ref="ref",
                              content_hash="sha256=" + "a" * 64)
        self.assertEqual(pub.load_retractions(consumer)[0]["content_hash"],
                         "sha256=" + "a" * 64)

    def test_corrupt_ledger_line_is_rejected(self):
        self.seed_eligible_chain()
        self._activate_version("2026.10.19-r1")
        consumer = self.root / "consumer"
        ledger = consumer / "retractions.jsonl"
        ledger.write_bytes(b'{"asset_id": "x"}\n')
        with self.assertRaises(pub.PublishError) as ctx:
            pub.load_retractions(consumer)
        self.assertIn("PUB-Retract", str(ctx.exception))


# ---------------------------------------------------------------------------
# AC #4 — reproducible CLI surface (offline)
# ---------------------------------------------------------------------------

class CliTests(PublisherFixtureBase):

    def test_cli_end_to_end(self):
        self.seed_eligible_chain(claim_ref="c-fixture01")
        packs = self.root / "packs"
        consumer = self.root / "consumer"
        rc = cli_main(["publish", "build", "--db", str(self.db_path),
                       "--out", str(packs), "--pack-version", "2026.10.19-r1"])
        self.assertEqual(rc, 0)
        pack_dir = packs / "ce-pack-2026.10.19-r1"
        rc = cli_main(["publish", "verify", "--pack", str(pack_dir)])
        self.assertEqual(rc, 0)
        rc = cli_main(["publish", "activate", "--pack", str(pack_dir),
                       "--consumer-dir", str(consumer)])
        self.assertEqual(rc, 0)
        rc = cli_main(["publish", "status", "--consumer-dir", str(consumer)])
        self.assertEqual(rc, 0)
        rc = cli_main(["publish", "retract", "--consumer-dir", str(consumer),
                       "--asset-id", "test-strategy-a",
                       "--reason", "synthetic cli withdrawal",
                       "--decision-ref", "test-decision-006"])
        self.assertEqual(rc, 0)
        rc = cli_main(["publish", "read", "--consumer-dir", str(consumer),
                       "--kind", "strategy", "--asset-id", "test-strategy-a",
                       "--revision", "1"])
        self.assertEqual(rc, 0)
        rc = cli_main(["publish", "diff", "--from", str(pack_dir),
                       "--to", str(pack_dir)])
        self.assertEqual(rc, 0)

    def test_cli_verify_fails_on_tampered_pack(self):
        self.seed_eligible_chain()
        packs = self.root / "packs"
        rc = cli_main(["publish", "build", "--db", str(self.db_path),
                       "--out", str(packs), "--pack-version", "2026.10.19-r1"])
        self.assertEqual(rc, 0)
        pack_dir = packs / "ce-pack-2026.10.19-r1"
        strategies = pack_dir / "strategies.jsonl"
        record = json.loads(strategies.read_text(encoding="utf-8").splitlines()[0])
        record["title"] = "Tampered"
        strategies.write_bytes((json.dumps(record, ensure_ascii=False,
                                           sort_keys=True) + "\n").encode("utf-8"))
        rc = cli_main(["publish", "verify", "--pack", str(pack_dir)])
        self.assertEqual(rc, 2)

    def test_cli_build_excludes_unqualified_assets(self):
        self.seed_eligible_chain()
        self.insert_asset("evaluation_case",
                          eval_case_record("test-strategy-draft", 1,
                                           case_id="test-eval-draft",
                                           lifecycle_status="draft",
                                           release_eligibility="not_eligible",
                                           review_origin=None,
                                           review_status="not_reviewed",
                                           technical_validation="not_run",
                                           scientific_appraisal="not_done"))
        self.insert_asset("strategy", strategy_record(
            asset_id="test-strategy-draft", eval_ids=(("test-eval-draft", 1),),
            release_eligibility="not_eligible", lifecycle_status="draft"))
        packs = self.root / "packs"
        rc = cli_main(["publish", "build", "--db", str(self.db_path),
                       "--out", str(packs), "--pack-version", "2026.10.19-r1"])
        self.assertEqual(rc, 0)
        ids = [json.loads(line)["asset_id"] for line in
               (packs / "ce-pack-2026.10.19-r1" / "strategies.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(ids, ["test-strategy-a"])


if __name__ == "__main__":
    unittest.main()
