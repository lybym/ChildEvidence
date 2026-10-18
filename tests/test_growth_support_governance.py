"""Growth-support governance decision contract tests (Issue #11).

Covers the machine-checkable deliverables of Issue #11:
- GS contract envelope (pending human *decision* status, ``gsgov`` family);
- two-route comparison recorded without preselecting the AI review trial route;
- six separation dimensions and disjoint review-origin families;
- release decision rules GS-01…GS-06: positive examples pass, negative
  examples fail with exactly the declared rule ids;
- AI consistency cannot produce approval or human gold (GS-02);
- persona version updates (GS-04), revocation audit trail (GS-03),
  unreviewed-content rejection (GS-05) and the two data boundaries (GS-06);
- qualification decision document consistency (pending markers, no forged
  approvals, full issue URLs for #2/#10, history preservation, verification
  scope statement).

All checks are offline and read-only against repository files.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from research_library.governance import (  # noqa: E402
    GS_CONTRACT_FILES,
    GS_DECISION_DOC,
    GS_SEPARATION_DIMENSION_IDS,
    HUMAN_REVIEW_ORIGINS,
    NON_HUMAN_REVIEW_ORIGINS,
    check_governance_docs,
    check_growth_support_governance_docs,
    load_gs_contract,
    validate_release_decision_record,
)

GS_DOC = ROOT / GS_DECISION_DOC


def _base_record(**overrides):
    """A legal minimal pending record used as the base for rule probes."""
    record = {
        "record_id": "gs-rel-test-001",
        "asset_kind": "evidence_pack",
        "asset_ref": "pack-demo-test@1",
        "revision": 1,
        "data_boundary": "research_library",
        "basis_kind": "design_choice",
        "basis_refs": ["design-choice-demo-001"],
        "review_origin": "adjudicated_human",
        "technical_validation": "passed",
        "scientific_appraisal": "done",
        "decision_status": "pending",
        "approved_by": None,
        "approved_date": None,
        "decision_record_ref": None,
        "revoked_reason": None,
        "revoked_date": None,
        "runtime_effect": "new_version_release",
        "evaluation_refs": [],
        "subject_ref": None,
        "host_managed": None,
        "correction_supported": None,
        "governance_doc_version": "test",
    }
    record.update(overrides)
    return record


def _rule_ids(errors):
    return sorted({e.split(":", 1)[0] for e in errors if e.startswith("GS-")})


class GsContractEnvelopeTest(unittest.TestCase):
    def test_contract_envelope_declares_pending_decision(self):
        data, errors = load_gs_contract("gs-qualification")
        self.assertEqual(errors, [], f"gs contract envelope: {errors}")
        self.assertTrue(data["$schema_name"].startswith("childevidence-gsgov-"))
        self.assertEqual(data["$schema_version"], 1)
        self.assertIn("pending human decision", data["status"])

    def test_route_decision_is_not_preselected(self):
        contract, _ = load_gs_contract("gs-qualification")
        route = contract["route_decision"]
        self.assertEqual(route["decision_id"], "GS-D1")
        self.assertEqual(route["status"], "pending_human_decision")
        self.assertIs(route["preselected"], False)

    def test_pending_decision_register_is_complete_and_unsigned(self):
        contract, _ = load_gs_contract("gs-qualification")
        pending = contract["pending_decisions"]
        self.assertEqual([d["decision_id"] for d in pending], ["GS-D1", "GS-D2", "GS-D3", "GS-D4"])
        for d in pending:
            self.assertEqual(d["status"], "pending_human_decision")
        by_id = {d["decision_id"]: d for d in pending}
        self.assertEqual(by_id["GS-D2"]["issue_ref"], "https://github.com/lybym/ChildEvidence/issues/2")
        self.assertEqual(by_id["GS-D3"]["issue_ref"], "https://github.com/lybym/ChildEvidence/issues/10")
        self.assertIn("AI 结果不得代替人工完成", by_id["GS-D2"]["constraint"])
        self.assertIn("Astra", by_id["GS-D3"]["topic"])

    def test_both_routes_recorded_with_comparison_fields(self):
        contract, _ = load_gs_contract("gs-qualification")
        routes = contract["routes"]
        self.assertEqual(set(routes), {"manual_publication", "ai_review_trial"})
        for route in routes.values():
            for field in ("uses", "review_method", "approval_conditions", "unverified"):
                self.assertTrue(route[field], f"route field {field} must be recorded")
        self.assertIn("继续有效", routes["manual_publication"]["label"])
        self.assertIn("未被预先选择", routes["ai_review_trial"]["label"])

    def test_six_separation_dimensions_present_and_distinct(self):
        contract, _ = load_gs_contract("gs-qualification")
        dims = contract["separation_dimensions"]
        self.assertEqual([d["id"] for d in dims], list(GS_SEPARATION_DIMENSION_IDS))
        for dim in dims:
            self.assertTrue(dim["definition"])
            self.assertTrue(dim["distinct_from"])
        self.assertTrue(contract["non_redundancy_rule"])

    def test_review_origin_families_are_disjoint_and_complete(self):
        contract, _ = load_gs_contract("gs-qualification")
        families = contract["review_origin_families"]
        self.assertEqual(set(families["human"]), set(HUMAN_REVIEW_ORIGINS))
        self.assertEqual(set(families["non_human"]), set(NON_HUMAN_REVIEW_ORIGINS))
        self.assertFalse(set(families["human"]) & set(families["non_human"]))
        self.assertIn("multi_model_consistent", families["ai_consistency_rule"])


class ReleaseDecisionRulesTest(unittest.TestCase):
    def test_minimal_pending_record_passes(self):
        self.assertEqual(validate_release_decision_record(_base_record()), [])

    def test_contract_positive_examples_pass(self):
        contract, _ = load_gs_contract("gs-qualification")
        self.assertTrue(contract["positive_examples"])
        for ex in contract["positive_examples"]:
            self.assertEqual(
                validate_release_decision_record(ex), [], f"{ex['record_id']}: must pass"
            )

    def test_contract_negative_examples_fail_with_declared_rules(self):
        contract, _ = load_gs_contract("gs-qualification")
        self.assertTrue(contract["negative_examples"])
        for ex in contract["negative_examples"]:
            errors = validate_release_decision_record(ex["record"])
            self.assertEqual(
                _rule_ids(errors),
                sorted(ex["expected_rule_ids"]),
                f"{ex['record']['record_id']}: unexpected rule ids (full: {errors})",
            )

    def test_approved_requires_human_signoff_and_decision_ref(self):
        record = _base_record(
            decision_status="approved",
            approved_by="knowledge-owner",
            approved_date="2026-10-18",
            decision_record_ref="GS-D1-approval-test-001",
        )
        self.assertEqual(validate_release_decision_record(record), [])
        for missing in ({"approved_by": None}, {"approved_date": None}, {"decision_record_ref": None}):
            bad = _base_record(decision_status="approved", **missing)
            errors = validate_release_decision_record(bad)
            self.assertIn("GS-01", _rule_ids(errors), f"{missing}: {errors}")

    def test_unreviewed_content_cannot_be_approved(self):
        record = _base_record(
            decision_status="approved",
            approved_by="knowledge-owner",
            approved_date="2026-10-18",
            decision_record_ref="GS-test",
            technical_validation="not_run",
            scientific_appraisal="none",
        )
        self.assertEqual(_rule_ids(validate_release_decision_record(record)), ["GS-05"])

    def test_revocation_requires_reason_date_and_keeps_audit_trail(self):
        base = _base_record(
            decision_status="revoked",
            approved_by="knowledge-owner",
            approved_date="2026-10-10",
        )
        errors = validate_release_decision_record(base)
        self.assertEqual(_rule_ids(errors), ["GS-03"])
        good = _base_record(
            decision_status="revoked",
            approved_by="knowledge-owner",
            approved_date="2026-10-10",
            decision_record_ref="GS-REV-test-001",
            revoked_reason="复审发现适用边界收窄",
            revoked_date="2026-10-18",
        )
        # Revocation is an appended state: asset_ref and revision are retained.
        self.assertEqual(good["asset_ref"], "pack-demo-test@1")
        self.assertEqual(good["revision"], 1)
        self.assertEqual(validate_release_decision_record(good), [])

    def test_persona_update_requires_evaluation_and_version_release(self):
        good = _base_record(
            asset_kind="interaction_profile",
            asset_ref="profile-demo-test@2",
            revision=2,
            basis_refs=["synthesis-demo-001"],
            evaluation_refs=["evalcase-demo-001"],
            runtime_effect="new_version_release",
            decision_status="pending",
        )
        self.assertEqual(validate_release_decision_record(good), [])
        no_eval = _base_record(
            asset_kind="interaction_profile",
            revision=2,
            basis_refs=["synthesis-demo-001"],
            evaluation_refs=[],
            decision_status="pending",
        )
        self.assertEqual(_rule_ids(validate_release_decision_record(no_eval)), ["GS-04"])
        immediate = _base_record(
            asset_kind="interaction_profile",
            revision=2,
            basis_refs=["synthesis-demo-001"],
            evaluation_refs=["evalcase-demo-001"],
            runtime_effect="immediate",
            decision_status="pending",
        )
        self.assertEqual(_rule_ids(validate_release_decision_record(immediate)), ["GS-04"])
        first_revision = _base_record(
            asset_kind="interaction_profile",
            revision=1,
            basis_refs=["synthesis-demo-001"],
            evaluation_refs=[],
            decision_status="pending",
        )
        # Review P1-1 regression: revision 1 must NOT bypass GS-04 — persona
        # assets are evaluable and version-released at every revision.
        self.assertEqual(_rule_ids(validate_release_decision_record(first_revision)), ["GS-04"])
        first_revision_good = _base_record(
            asset_kind="interaction_profile",
            asset_ref="profile-demo-test@1",
            revision=1,
            basis_refs=["synthesis-demo-001"],
            evaluation_refs=["evalcase-demo-001"],
            decision_status="pending",
        )
        self.assertEqual(validate_release_decision_record(first_revision_good), [])

    def test_persona_v1_immediate_without_evaluation_is_rejected(self):
        # Exact probe from review P1-1: revision=1 + runtime_effect=immediate +
        # empty evaluation_refs used to pass with zero errors.
        record = _base_record(
            asset_kind="interaction_profile",
            asset_ref="profile-demo-v1@1",
            revision=1,
            basis_refs=[],
            evaluation_refs=[],
            runtime_effect="immediate",
            decision_status="approved",
            approved_by="product-owner",
            approved_date="2026-10-18",
            decision_record_ref="GS-test-approval",
        )
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), ["GS-04"])

    def test_schema_rejects_malformed_dates(self):
        record = _base_record(decision_status="pending", approved_date="2026/10/18")
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), [])  # not a GS rule: schema-level failure
        self.assertTrue(any("approved_date" in e for e in errors), f"{errors}")

    def test_schema_requires_core_fields(self):
        record = _base_record()
        del record["decision_status"]
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), [])
        self.assertTrue(any("decision_status" in e for e in errors), f"{errors}")


class AiConsistencyTest(unittest.TestCase):
    def test_multi_model_consensus_cannot_be_approved_even_with_signoff_fields(self):
        record = _base_record(
            review_origin="multi_model_consistent",
            decision_status="approved",
            approved_by="model-ensemble-demo",
            approved_date="2026-10-18",
            decision_record_ref="GS-bad-consensus",
        )
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), ["GS-02"])

    def test_ai_draft_cannot_reach_revoked_state(self):
        record = _base_record(
            review_origin="ai_draft",
            decision_status="revoked",
            decision_record_ref="GS-test",
            revoked_reason="试运行发现问题",
            revoked_date="2026-10-18",
        )
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), ["GS-02"])

    def test_non_human_origins_stay_pending(self):
        for origin in NON_HUMAN_REVIEW_ORIGINS:
            record = _base_record(review_origin=origin, decision_status="pending")
            self.assertEqual(validate_release_decision_record(record), [])

    def test_approved_with_unmarked_origin_is_rejected(self):
        # Review P2-1 regression: an approved record with review_origin=null
        # (unknown review source) used to pass all rules.
        record = _base_record(
            review_origin=None,
            decision_status="approved",
            approved_by="knowledge-owner",
            approved_date="2026-10-18",
            decision_record_ref="GS-test",
        )
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), ["GS-02"])

    def test_revoked_with_unmarked_origin_is_rejected(self):
        record = _base_record(
            review_origin=None,
            decision_status="revoked",
            decision_record_ref="GS-test",
            revoked_reason="复审撤回",
            revoked_date="2026-10-18",
        )
        self.assertEqual(_rule_ids(validate_release_decision_record(record)), ["GS-02"])

    def test_approved_requires_each_human_origin_to_be_marked(self):
        for origin in HUMAN_REVIEW_ORIGINS:
            record = _base_record(
                review_origin=origin,
                decision_status="approved",
                approved_by="knowledge-owner",
                approved_date="2026-10-18",
                decision_record_ref="GS-test",
            )
            self.assertEqual(validate_release_decision_record(record), [])


class DataBoundaryTest(unittest.TestCase):
    def test_research_library_rejects_personal_subject_refs(self):
        record = _base_record(data_boundary="research_library", subject_ref="demo-learner-A")
        errors = validate_release_decision_record(record)
        self.assertEqual(_rule_ids(errors), ["GS-06"])

    def test_personal_records_require_host_management_and_correction(self):
        record = _base_record(
            data_boundary="personal_growth_record",
            subject_ref="demo-learner-A",
            host_managed=False,
            correction_supported=None,
        )
        self.assertEqual(_rule_ids(validate_release_decision_record(record)), ["GS-06"])
        good = _base_record(
            data_boundary="personal_growth_record",
            subject_ref="demo-learner-A",
            host_managed=True,
            correction_supported=True,
        )
        self.assertEqual(validate_release_decision_record(good), [])


class QualificationDocConsistencyTest(unittest.TestCase):
    def test_gs_document_checks_pass(self):
        errors, warnings = check_growth_support_governance_docs()
        self.assertEqual(errors, [], f"GS doc errors: {errors}")
        self.assertEqual(warnings, [])

    def test_document_keeps_pending_and_no_proxy_signature_markers(self):
        text = GS_DOC.read_text(encoding="utf-8")
        self.assertIn("pending_human_decision", text)
        self.assertIn("不代签", text)
        self.assertIn("待真实决定", text)
        self.assertNotIn("已生效", text)
        self.assertNotIn("| APPROVE |", text)

    def test_document_records_route_comparison_without_preselection(self):
        text = GS_DOC.read_text(encoding="utf-8")
        for marker in ("人工发布资格", "AI 审查试用", "未预先选择"):
            self.assertIn(marker, text)

    def test_document_lists_six_separation_dimensions(self):
        text = GS_DOC.read_text(encoding="utf-8")
        for dim in ("资料处理权限", "技术校验", "科学评价", "审核来源", "发布资格", "个体适用性"):
            self.assertIn(dim, text)

    def test_document_preserves_issue_2_and_10_references_with_full_urls(self):
        text = GS_DOC.read_text(encoding="utf-8")
        self.assertIn("https://github.com/lybym/ChildEvidence/issues/2", text)
        self.assertIn("https://github.com/lybym/ChildEvidence/issues/10", text)
        self.assertIn("继续、缩小或延期", text)
        self.assertIn("Astra", text)

    def test_document_points_to_contract_and_states_verification_scope(self):
        text = GS_DOC.read_text(encoding="utf-8")
        self.assertIn(GS_CONTRACT_FILES["gs-qualification"], text)
        self.assertIn("保留旧版本", text)
        self.assertIn("不改写", text)
        self.assertIn("验证范围", text)

    def test_full_governance_doc_set_stays_consistent(self):
        errors, warnings = check_governance_docs()
        self.assertEqual(errors, [], f"governance docs errors: {errors}")
        self.assertEqual(warnings, [])

    def test_protocols_stay_untouched_draft_v1_1(self):
        # The qualification decision must not revise the four protocols:
        # same-version revision is gated behind the real GS-D1..D4 decisions.
        from research_library.governance import PROTOCOL_FILES

        for rel in PROTOCOL_FILES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("DRAFT v1.1", text)
            self.assertIn("待人工审核", text)


class ContractSelfDescriptionTest(unittest.TestCase):
    def test_cross_record_limitations_are_registered(self):
        # Review P2-2: single-record scope must be declared, not implied.
        contract, _ = load_gs_contract("gs-qualification")
        limitations = {lim.get("id") for lim in contract.get("known_limitations", [])}
        self.assertIn("GS-LIM-01", limitations)
        self.assertIn("GS-LIM-02", limitations)
        text = GS_DOC.read_text(encoding="utf-8")
        self.assertIn("GS-LIM-01", text)
        self.assertIn("GS-LIM-02", text)


class NonRootContractCheckTest(unittest.TestCase):
    """Review P2-3: contract content checks must run for non-ROOT roots."""

    def _make_fixture_root(self, tmp: Path) -> Path:
        (tmp / "docs" / "governance" / "contracts").mkdir(parents=True)
        shutil.copyfile(GS_DOC, tmp / GS_DECISION_DOC)
        shutil.copyfile(
            ROOT / "docs" / "governance" / "contracts" / GS_CONTRACT_FILES["gs-qualification"],
            tmp / "docs" / "governance" / "contracts" / GS_CONTRACT_FILES["gs-qualification"],
        )
        return tmp

    def test_clean_fixture_root_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, warnings = check_growth_support_governance_docs(self._make_fixture_root(Path(tmp)))
        self.assertEqual(errors, [], f"clean fixture must pass: {errors}")
        self.assertEqual(warnings, [])

    def test_tampered_route_decision_is_detected_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_fixture_root(Path(tmp))
            path = root / "docs" / "governance" / "contracts" / GS_CONTRACT_FILES["gs-qualification"]
            data = json.loads(path.read_text(encoding="utf-8"))
            data["route_decision"]["preselected"] = True
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            errors, _ = check_growth_support_governance_docs(root)
        self.assertTrue(any("preselected" in e for e in errors), f"{errors}")

    def test_tampered_negative_example_is_detected_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_fixture_root(Path(tmp))
            path = root / "docs" / "governance" / "contracts" / GS_CONTRACT_FILES["gs-qualification"]
            data = json.loads(path.read_text(encoding="utf-8"))
            data["negative_examples"][0]["expected_rule_ids"] = []
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            errors, _ = check_growth_support_governance_docs(root)
        self.assertTrue(any("negative example" in e for e in errors), f"{errors}")

    def test_missing_contract_outside_root_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_fixture_root(Path(tmp))
            (root / "docs" / "governance" / "contracts" / GS_CONTRACT_FILES["gs-qualification"]).unlink()
            errors, _ = check_growth_support_governance_docs(root)
        self.assertTrue(any("missing" in e for e in errors), f"{errors}")


if __name__ == "__main__":
    unittest.main()
