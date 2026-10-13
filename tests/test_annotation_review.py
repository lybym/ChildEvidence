"""CE-02 blind human review regression tests (Issue #2).

Covers the regression surface demanded by Issue #2:
- blind-leak detection at import (historical_label / stratum / pre-filled judgements);
- append-only audit trail (UPDATE/DELETE refused at the DB level);
- duplicate-submission protection and amend-with-history;
- human permission gates: no code path promotes provisional -> gold without a
  human sign-off backed by an evidence file + independent review or adjudication;
- pending/undecided queue; pause/resume;
- pre-lock unblinding refusal (audit requires all labels locked);
- lossless round-trip with the real A2 blinded CSV (80 items) and export with
  no blinded-out columns;
- independent store isolation: the main library.sqlite is never created/touched.

All tests are offline; the real blinded CSV is only read, never modified, and
its keyed sibling (historical labels) is only touched by the post-lock audit
test through a synthetic fixture (never the real keyed file).
"""

import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from helpers import make_tmp_dir  # noqa: E402

from research_library import annotation  # noqa: E402

BLINDED_CSV = (
    ROOT / "docs" / "assessment" / "2026-10-13-poc-tech-evaluation" / "datasets"
    / "asreview-human-review-queue-blinded.csv"
)

HEADER = "queue_id,sample_id,doi,title,abstract,language,publication_year,review_task,gold_label,reviewer,review_status,notes"
ROW_OK = ("a2-t001,lt-x1,10.1000/fixture.1,Fixture Title One,Some abstract,en,2020,"
          "judge relevance to: test scope,,,pending,")
ROW_OK2 = ("a2-t002,lt-x2,10.1000/fixture.2,Fixture Title Two,Some other abstract,zh,1998,"
           "judge relevance to: test scope,,,pending,")


def write_csv(tmp: Path, rows: list[str], header: str = HEADER, name: str = "queue.csv") -> Path:
    p = tmp / name
    lines = [header] + rows
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def judge_first(tmp: Path, reviewer: str = "reviewer-1",
                decision: str = "relevant", code: str = "A01") -> str:
    store = tmp / "annotations.sqlite"
    item = annotation.next_item(store)
    annotation.judge(store, item["queue_id"], reviewer_id=reviewer,
                     decision=decision, reason_code=code,
                     reason_text="符合测试范围的实证研究")
    return item["queue_id"]


class BlindImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("ann-imp-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_import_basic_and_idempotent(self):
        csv = write_csv(self.tmp, [ROW_OK, ROW_OK2])
        store = self.tmp / "annotations.sqlite"
        res = annotation.import_blinded_csv(store, csv)
        self.assertEqual(res["imported"], 2)
        # identical re-import is an idempotent no-op
        res2 = annotation.import_blinded_csv(store, csv)
        self.assertTrue(res2["idempotent"])
        self.assertEqual(res2["total"], 2)
        # a different queue is refused
        other = write_csv(self.tmp, [ROW_OK.replace("a2-t001", "a2-t009")], name="queue2.csv")
        with self.assertRaises(annotation.ReviewError):
            annotation.import_blinded_csv(store, other)

    def test_blind_leak_historical_label_rejected(self):
        header = HEADER.replace(",review_task,", ",review_task,historical_label,")
        row = ROW_OK.replace(",,,pending,", ",1,,pending,")
        csv = write_csv(self.tmp, [row], header=header)
        with self.assertRaises(annotation.BlindLeakError) as ctx:
            annotation.import_blinded_csv(self.tmp / "s.sqlite", csv)
        self.assertIn("historical_label", str(ctx.exception))

    def test_blind_leak_stratum_rejected(self):
        header = HEADER.replace(",review_task,", ",review_task,stratum,")
        row = ROW_OK.replace(",,,pending,", ",ingested_en,,pending,")
        csv = write_csv(self.tmp, [row], header=header)
        with self.assertRaises(annotation.BlindLeakError):
            annotation.import_blinded_csv(self.tmp / "s.sqlite", csv)

    def test_blind_leak_prefilled_gold_label_rejected(self):
        row = ROW_OK.replace(",,pending,", "1,rev,pending,")
        csv = write_csv(self.tmp, [row])
        with self.assertRaises(annotation.BlindLeakError):
            annotation.import_blinded_csv(self.tmp / "s.sqlite", csv)

    def test_store_has_no_leak_columns(self):
        csv = write_csv(self.tmp, [ROW_OK])
        store = self.tmp / "annotations.sqlite"
        annotation.import_blinded_csv(store, csv)
        conn = sqlite3.connect(str(store))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(queue_items)")}
        conn.close()
        self.assertFalse(cols & {"historical_label", "stratum", "model_score",
                                 "rank", "gold_label", "reviewer"})

    def test_main_library_isolation(self):
        csv = write_csv(self.tmp, [ROW_OK])
        store = self.tmp / "annotations.sqlite"
        annotation.import_blinded_csv(store, csv)
        # the independent store exists; the main library.sqlite was never created
        self.assertTrue(store.exists())
        self.assertFalse((self.tmp / "library.sqlite").exists())

    def test_real_a2_blinded_csv_imports_80(self):
        self.assertTrue(BLINDED_CSV.exists(), "real blinded CSV must ship in repo")
        store = self.tmp / "annotations.sqlite"
        res = annotation.import_blinded_csv(store, BLINDED_CSV)
        self.assertEqual(res["imported"], 80)
        conn = sqlite3.connect(str(store))
        n = conn.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0]
        conn.close()
        self.assertEqual(n, 80)


class JudgementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("ann-jdg-")
        self.store = self.tmp / "annotations.sqlite"
        self.csv = write_csv(self.tmp, [ROW_OK, ROW_OK2])
        annotation.import_blinded_csv(self.store, self.csv)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_judge_creates_provisional_single_human(self):
        res = annotation.judge(self.store, "a2-t001", reviewer_id="reviewer-1",
                               decision="relevant", reason_code="A01",
                               reason_text="儿童执行功能实证研究，符合范围",
                               confidence="high")
        self.assertEqual(res["label_tier"], "provisional")
        conn = sqlite3.connect(str(self.store))
        conn.row_factory = sqlite3.Row
        ev = conn.execute("SELECT * FROM annotation_events").fetchone()
        st = conn.execute("SELECT * FROM review_state WHERE queue_id='a2-t001'").fetchone()
        conn.close()
        self.assertEqual(ev["produced_by_kind"], "single_human")
        self.assertEqual(ev["ai_assisted"], 0)
        self.assertEqual(st["status"], "submitted")
        self.assertEqual(st["label_tier"], "provisional")

    def test_invalid_decision_and_reason_code(self):
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="maybe", reason_code="A01", reason_text="x")
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="not_relevant", reason_code="A01",
                             reason_text="理由")
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="not_relevant", reason_code="R03",
                             reason_text=" ")
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="relevant", reason_code="B01", reason_text="理由")
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="relevant", reason_code="A01",
                             reason_text="ok", confidence="very-high")

    def test_missing_reviewer_id_rejected(self):
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="",
                             decision="relevant", reason_code="A01", reason_text="理由")

    def test_duplicate_submission_blocked_amend_keeps_history(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="初判")
        with self.assertRaises(annotation.DuplicateSubmissionError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="not_relevant", reason_code="R01",
                             reason_text="改判")
        res = annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                               decision="not_relevant", reason_code="R01",
                               reason_text="改判", amend=True)
        self.assertEqual(res["event_kind"], "amendment")
        conn = sqlite3.connect(str(self.store))
        events = conn.execute(
            "SELECT event_kind, decision FROM annotation_events ORDER BY event_id"
        ).fetchall()
        conn.close()
        self.assertEqual(events[0], ("judgement", "relevant"))  # original kept
        self.assertEqual(events[1], ("amendment", "not_relevant"))

    def test_undecided_is_legal_and_pends(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="undecided", reason_code="U01",
                         reason_text="缺少关键信息")
        pending = annotation.pending_queue(self.store)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["queue_id"], "a2-t001")
        self.assertEqual(pending[0]["reason_code"], "U01")

    def test_append_only_triggers_block_update_delete(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="初判")
        raw = sqlite3.connect(str(self.store))
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute("UPDATE annotation_events SET decision='not_relevant'")
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute("DELETE FROM annotation_events")
        raw.close()

    def test_next_skips_submitted_and_paused_flow(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="ok理由")
        nxt = annotation.next_item(self.store)
        self.assertEqual(nxt["queue_id"], "a2-t002")
        # blind exposure: next() must not carry historical/stratum fields
        self.assertFalse({"historical_label", "stratum", "rank", "score"} & set(nxt))
        paused = annotation.pause(self.store, note="休息")
        self.assertTrue(paused["paused"])
        self.assertEqual(paused["resume_point"], "a2-t002")
        resumed = annotation.resume(self.store)
        self.assertTrue(resumed["was_paused"])
        self.assertEqual(resumed["next_queue_id"], "a2-t002")
        self.assertFalse(annotation.progress(self.store)["paused"])


class LockAndAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("ann-aud-")
        self.store = self.tmp / "annotations.sqlite"
        rows = [ROW_OK, ROW_OK2]
        self.csv = write_csv(self.tmp, rows)
        annotation.import_blinded_csv(self.store, self.csv)
        # keyed view used only by the post-lock audit (synthetic fixture)
        keyed_header = ("queue_id,sample_id,stratum,doi,title,abstract,language,"
                        "publication_year,historical_label,review_task")
        self.keyed = write_csv(
            self.tmp,
            ["a2-t001,lt-x1,ingested_en,10.1000/fixture.1,Fixture Title One,ab,en,2020,1,judge",
             "a2-t002,lt-x2,rejected_zh,10.1000/fixture.2,Fixture Title Two,ab,zh,1998,0,judge"],
            header=keyed_header, name="keyed.csv",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _submit_all(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01",
                         reason_text="符合范围")
        annotation.judge(self.store, "a2-t002", reviewer_id="r1",
                         decision="not_relevant", reason_code="R01",
                         reason_text="离题")

    def test_lock_requires_full_submission(self):
        with self.assertRaises(annotation.NotLockedError):
            annotation.lock_queue(self.store, confirmed_by="owner")
        self._submit_all()
        res = annotation.lock_queue(self.store, confirmed_by="owner")
        self.assertEqual(res["locked"], 2)
        self.assertEqual(annotation.progress(self.store)["locked"], 2)
        with self.assertRaises(annotation.ReviewError):
            annotation.lock_queue(self.store, confirmed_by="")

    def test_audit_refused_before_lock(self):
        # partially submitted: refused
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01",
                         reason_text="符合范围")
        with self.assertRaises(annotation.NotLockedError):
            annotation.run_audit(self.store, self.keyed, self.tmp / "audit")
        # fully submitted but not locked: still refused (blind must be fixed first)
        annotation.judge(self.store, "a2-t002", reviewer_id="r1",
                         decision="not_relevant", reason_code="R01",
                         reason_text="离题")
        with self.assertRaises(annotation.NotLockedError):
            annotation.run_audit(self.store, self.keyed, self.tmp / "audit")

    def test_locked_items_reject_further_judgement_and_adjudication(self):
        # r1 and r2 both judge a2-t001 (different reviewers are independent);
        # r2's state lands in review_state, so the queue can be locked.
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="一审")
        annotation.judge(self.store, "a2-t001", reviewer_id="r2",
                         decision="not_relevant", reason_code="R01", reason_text="二审")
        annotation.judge(self.store, "a2-t002", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="ok理由")
        annotation.lock_queue(self.store, confirmed_by="owner")
        # judge/amend on locked labels must be refused (labels are fixed)
        with self.assertRaises(annotation.NotLockedError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                             decision="not_relevant", reason_code="R01",
                             reason_text="锁定后改判", amend=True)
        with self.assertRaises(annotation.NotLockedError):
            annotation.judge(self.store, "a2-t002", reviewer_id="r2",
                             decision="relevant", reason_code="A01",
                             reason_text="锁定后补判")
        # a locked item cannot re-enter adjudication either
        with self.assertRaises(annotation.NotLockedError):
            annotation.record_adjudication(self.store, "a2-t001",
                                           adjudicator_id="judge-3",
                                           decision="boundary", reason_code="B01",
                                           reason_text="锁定后裁决")
        self.assertEqual(annotation.progress(self.store)["locked"], 2)
        conn = sqlite3.connect(str(self.store))
        st = conn.execute("SELECT status, decision FROM review_state "
                          "WHERE queue_id='a2-t001'").fetchone()
        conn.close()
        self.assertEqual(st[0], "locked")
        self.assertEqual(st[1], "not_relevant")

    def test_amend_without_prior_judgement_refused(self):
        with self.assertRaises(annotation.ReviewError):
            annotation.judge(self.store, "a2-t001", reviewer_id="r9",
                             decision="relevant", reason_code="A01",
                             reason_text="没有初判却要求修正", amend=True)

    def test_audit_after_lock_is_readonly_and_layered(self):
        self._submit_all()
        annotation.lock_queue(self.store, confirmed_by="owner")
        outdir = self.tmp / "audit"
        res = annotation.run_audit(self.store, self.keyed, outdir)
        self.assertEqual(res["total"], 2)
        # a2-t001: human relevant vs historical ingested -> consistent
        # a2-t002: human not_relevant vs historical rejected -> consistent
        self.assertEqual(res["counts"]["consistent"], 2)
        report = (outdir / "audit-report.md").read_text(encoding="utf-8")
        self.assertIn("不得", report)  # no-extrapolation boundary present
        self.assertIn("回训", report)  # ASReview re-training ban present
        self.assertIn("未提供", report)  # no extrapolation note by default
        results = (outdir / "audit-results.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(results), 2)
        # original decisions preserved (audit never writes back)
        conn = sqlite3.connect(str(self.store))
        st = conn.execute("SELECT decision FROM review_state WHERE queue_id='a2-t001'").fetchone()
        conn.close()
        self.assertEqual(st[0], "relevant")
        # protective layer proxies: zh item under classic/zh layer logic
        layers = {r.split('"protective_layer_proxy": "')[1].split('"')[0] for r in results}
        self.assertTrue(layers <= {"chinese", "classic_pre2000", "negative_result", "general"})
        # explicit extrapolation note is rendered when provided
        res2 = annotation.run_audit(self.store, self.keyed, self.tmp / "audit2",
                                    extrapolation_note="按 stratum 加权（人工提供）")
        report2 = (self.tmp / "audit2" / "audit-report.md").read_text(encoding="utf-8")
        self.assertIn("按 stratum 加权", report2)
        self.assertEqual(res2["total"], 2)

    def test_audit_missing_keyed_row_refused(self):
        self._submit_all()
        annotation.lock_queue(self.store, confirmed_by="owner")
        keyed_header = "queue_id,historical_label"
        bad = write_csv(self.tmp, ["a2-t001,1"], header=keyed_header, name="bad-keyed.csv")
        with self.assertRaises(annotation.ReviewError):
            annotation.run_audit(self.store, bad, self.tmp / "audit3")


class GoldGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("ann-gold-")
        self.store = self.tmp / "annotations.sqlite"
        self.csv = write_csv(self.tmp, [ROW_OK, ROW_OK2])
        annotation.import_blinded_csv(self.store, self.csv)
        self.evidence = self.tmp / "SIGNOFF.md"
        self.evidence.write_text("人工签署：知识负责人 owner，2026-10-13", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_script_path_from_provisional_to_gold(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="理由")
        # single-human label cannot be signed off (LT-02/LT-03 flow missing)
        with self.assertRaises(annotation.GateViolationError):
            annotation.record_signoff(self.store, "a2-t001", sign_off_by="owner",
                                      sign_off_date="2026-10-13",
                                      evidence_file=self.evidence)
        conn = sqlite3.connect(str(self.store))
        tier = conn.execute(
            "SELECT label_tier FROM review_state WHERE queue_id='a2-t001'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(tier, "provisional")

    def test_export_never_contains_gold_without_signoff(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="理由")
        out = annotation.export_annotations(self.store, self.tmp / "exp")
        self.assertEqual(out["gold"], 0)
        self.assertTrue(out["human_review_pending"])

    def test_signoff_requires_existing_evidence_file(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="理由")
        with self.assertRaises(annotation.GateViolationError):
            annotation.record_signoff(self.store, "a2-t001", sign_off_by="owner",
                                      sign_off_date="2026-10-13",
                                      evidence_file=self.tmp / "missing.md")

    def test_independent_double_agreement_allows_signoff_to_gold(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="reviewer-1",
                         decision="relevant", reason_code="A01", reason_text="独立一审")
        annotation.judge(self.store, "a2-t001", reviewer_id="reviewer-2",
                         decision="relevant", reason_code="A02", reason_text="独立二审")
        res = annotation.compare_reviewers(self.store)
        self.assertEqual(res["agreements"], 1)
        self.assertEqual(res["total_disagreements"], 0)
        signed = annotation.record_signoff(self.store, "a2-t001", sign_off_by="owner",
                                           sign_off_date="2026-10-13",
                                           evidence_file=self.evidence)
        self.assertEqual(signed["label_tier"], "gold")
        conn = sqlite3.connect(str(self.store))
        st = conn.execute("SELECT label_tier, produced_by_kind FROM review_state "
                          "WHERE queue_id='a2-t001'").fetchone()
        ev = conn.execute("SELECT event_kind, sign_off_by, evidence_file "
                          "FROM annotation_events WHERE event_kind='signoff'").fetchone()
        conn.close()
        self.assertEqual(st[0], "gold")
        self.assertEqual(st[1], "independent_double_human")
        self.assertEqual(ev[1], "owner")

    def test_disagreement_registered_then_adjudicated_then_signed(self):
        annotation.judge(self.store, "a2-t001", reviewer_id="reviewer-1",
                         decision="relevant", reason_code="A01", reason_text="一审")
        annotation.judge(self.store, "a2-t001", reviewer_id="reviewer-2",
                         decision="not_relevant", reason_code="R01", reason_text="二审")
        res = annotation.compare_reviewers(self.store)
        self.assertEqual(res["new_disagreements"], ["a2-t001"])
        dis = annotation.list_disagreements(self.store)
        self.assertEqual(len(dis), 1)
        self.assertEqual(dis[0]["decision_a"], "relevant")   # both originals kept
        self.assertEqual(dis[0]["decision_b"], "not_relevant")
        # sign-off must refuse while the disagreement is unresolved
        with self.assertRaises(annotation.GateViolationError):
            annotation.record_signoff(self.store, "a2-t001", sign_off_by="owner",
                                      sign_off_date="2026-10-13",
                                      evidence_file=self.evidence)
        # adjudication requires a registered disagreement; wrong item refused
        with self.assertRaises(annotation.ReviewError):
            annotation.record_adjudication(self.store, "a2-t002",
                                           adjudicator_id="judge-3",
                                           decision="relevant", reason_code="A01",
                                           reason_text="无分歧条目")
        adj = annotation.record_adjudication(self.store, "a2-t001",
                                             adjudicator_id="judge-3",
                                             decision="boundary", reason_code="B01",
                                             reason_text="裁决：人群边界")
        self.assertEqual(adj["label_tier"], "provisional")
        # after adjudication, sign-off produces gold
        signed = annotation.record_signoff(self.store, "a2-t001", sign_off_by="owner",
                                           sign_off_date="2026-10-13",
                                           evidence_file=self.evidence)
        self.assertEqual(signed["label_tier"], "gold")


class ExportAndMappingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("ann-exp-")
        self.store = self.tmp / "annotations.sqlite"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_roundtrip_real_a2_no_leak_columns(self):
        annotation.import_blinded_csv(self.store, BLINDED_CSV)
        qid = judge_first(self.tmp)
        out = annotation.export_annotations(self.store, self.tmp / "exp")
        self.assertEqual(out["total"], 80)
        self.assertEqual(out["submitted"], 1)
        self.assertTrue(out["human_review_pending"])
        csv_text = Path(out["csv"]).read_text(encoding="utf-8")
        header = csv_text.splitlines()[0]
        for banned in ("historical_label", "stratum", "rank", "score", "gold_label"):
            self.assertNotIn(banned, header.lower())
        self.assertIn(qid, csv_text)
        events = Path(out["events"]).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(events), 1)
        readme = Path(out["readme"]).read_text(encoding="utf-8")
        self.assertIn("HUMAN_REVIEW_PENDING", readme)
        self.assertIn("provisional", readme)

    def test_catalog_mapping_is_conservative(self):
        self.assertEqual(annotation.CATALOG_MAPPING["relevant"], "ingested")
        self.assertEqual(annotation.CATALOG_MAPPING["not_relevant"], "rejected")
        # boundary/undecided must stay pending (no automated conclusion)
        self.assertEqual(annotation.CATALOG_MAPPING["boundary"], "pending")
        self.assertEqual(annotation.CATALOG_MAPPING["undecided"], "pending")
        self.assertEqual(set(annotation.CATALOG_MAPPING), set(annotation.DECISIONS))

    def test_reason_code_table_matches_guide(self):
        self.assertEqual(annotation.REASON_CODES["relevant"], ("A01", "A02", "A03"))
        self.assertEqual(annotation.REASON_CODES["boundary"], ("B01", "B02", "B03"))
        self.assertEqual(annotation.REASON_CODES["not_relevant"],
                         ("R01", "R02", "R03", "R04", "R05", "R06"))
        self.assertEqual(annotation.REASON_CODES["undecided"], ("P01", "U01"))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_dir("ann-mig-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_migrate_store_idempotent(self):
        store = self.tmp / "annotations.sqlite"
        self.assertEqual(annotation.migrate_store(store), 1)
        self.assertEqual(annotation.migrate_store(store), 1)
        # migrating a store that already holds events must not reset the stamp
        write_csv(self.tmp, [ROW_OK])
        annotation.import_blinded_csv(store, self.tmp / "queue.csv")
        annotation.judge(store, "a2-t001", reviewer_id="r1",
                         decision="relevant", reason_code="A01", reason_text="理由")
        self.assertEqual(annotation.migrate_store(store), 1)
        conn = sqlite3.connect(str(store))
        n = conn.execute("SELECT COUNT(*) FROM annotation_events").fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)

    def test_future_store_version_refused(self):
        store = self.tmp / "future.sqlite"
        conn = annotation.connect_store(store)
        conn.execute("UPDATE schema_meta SET value='999' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        with self.assertRaises(annotation.ReviewError):
            annotation.migrate_store(store)


if __name__ == "__main__":
    unittest.main()
