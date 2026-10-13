"""CE-01R governance contract and document-consistency tests.

Covers the machine-checkable deliverables of Issue #1 (CE-01R):
- mini JSON-Schema subset validator behaviour (legal + illegal samples);
- contract envelopes (pending-approval status, schema name/version);
- 3 example research questions against the RQ registry contract;
- decision-scope separation (catalog vs review×RQ value domains);
- label tiers incl. the no-model-self-gold rule;
- POC errata pointer values matched against the v2 metrics CSV;
- cross-document consistency of the four DRAFT v1.1 protocols, AGENTS.md,
  governance docs and the unsigned human-approval checklist.

All checks are offline and read-only against repository files.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from research_library.governance import (  # noqa: E402
    CONTRACT_FILES,
    check_governance_docs,
    check_poc_metrics_pointer,
    load_contract,
    validate,
    validate_decision_record,
    validate_label_record,
    validate_research_question,
)

CONTRACT_SCHEMA = {
    "type": "object",
    "required": ["$schema_name", "$schema_version", "status"],
    "properties": {
        "$schema_name": {"type": "string"},
        "$schema_version": {"type": "integer"},
        "status": {"type": "string"},
    },
}


class MiniValidatorTest(unittest.TestCase):
    def test_type_and_required_ok(self):
        schema = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        }
        self.assertEqual(validate({"a": "x", "b": 2}, schema), [])

    def test_missing_required_and_wrong_type(self):
        schema = {
            "type": "object",
            "required": ["a"],
            "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        }
        errors = validate({"b": "not-int"}, schema)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("missing required property 'a'" in e for e in errors))
        self.assertTrue(any("$.b: expected type integer" in e for e in errors))

    def test_enum_pattern_minlength(self):
        schema = {"type": "string", "enum": ["a", "b"], "pattern": "^[a-z]$", "minLength": 1}
        self.assertEqual(validate("a", schema), [])
        self.assertEqual(len(validate("c", schema)), 1)  # enum miss only (pattern ok)
        self.assertEqual(len(validate("ab", schema)), 2)  # enum miss + pattern miss
        self.assertEqual(len(validate("", schema)), 3)  # enum + pattern + minLength

    def test_array_items_and_min_items(self):
        schema = {"type": "array", "minItems": 1, "items": {"type": "string", "enum": ["en", "zh"]}}
        self.assertEqual(validate(["en", "zh"], schema), [])
        self.assertEqual(len(validate([], schema)), 1)
        self.assertEqual(len(validate(["en", "fr"], schema)), 1)

    def test_nested_paths_are_reported(self):
        schema = {"type": "object", "properties": {"scope": {"type": "object", "properties": {"age": {"type": "string"}}}}}
        errors = validate({"scope": {"age": 7}}, schema)
        self.assertEqual(errors, ["$.scope.age: expected type string, got int"])

    def test_type_union(self):
        schema = {"type": ["string", "null"]}
        self.assertEqual(validate(None, schema), [])
        self.assertEqual(validate("x", schema), [])
        self.assertEqual(len(validate(3, schema)), 1)


class ContractEnvelopeTest(unittest.TestCase):
    def test_all_contracts_exist_and_declare_pending_approval(self):
        for name in CONTRACT_FILES:
            data, errors = load_contract(name)
            self.assertEqual(errors, [], f"contract {name}: {errors}")
            self.assertEqual(validate(data, CONTRACT_SCHEMA), [])
            self.assertIn("pending human approval", data["status"])

    def test_example_rqs_validate_against_registry_contract(self):
        registry, _ = load_contract("rq-registry")
        rqs_doc, _ = load_contract("example-rqs")
        rqs = rqs_doc["research_questions"]
        self.assertEqual(len(rqs), 3)
        ids = {rq["rq_id"] for rq in rqs}
        self.assertEqual(len(ids), 3)
        for rq in rqs:
            self.assertEqual(validate(rq, registry["schema"]), [])
            for e in validate_research_question(rq):
                self.fail(f"{rq['rq_id']}: {e}")

    def test_example_rqs_cover_issue_topics_and_stay_unapproved(self):
        _, _ = load_contract("rq-registry")
        rqs_doc, _ = load_contract("example-rqs")
        joined = " ".join(rq["rq_id"] for rq in rqs_doc["research_questions"])
        self.assertIn("task-initiation", joined)
        self.assertIn("emotion-regulation", joined)
        self.assertIn("ai-companion", joined)
        for rq in rqs_doc["research_questions"]:
            self.assertEqual(rq["status"], "registered")
            self.assertIsNone(rq["approved_by"])

    def test_rq_rule_violations_are_detected(self):
        bad = {
            "rq_id": "rq-demo",
            "version": 1,
            "question": "demo question text",
            "background": "demo background",
            "scope": {
                "population": "p", "age_range": "6-12", "languages": ["en"],
                "publication_types": ["empirical"], "time_window": "2020-2026",
            },
            "search_queries": [{"source": "openalex", "query": "test query"}],
            "inclusion_hints": [], "exclusion_hints": [],
            "domain": "learning_sciences",
            "status": "active",  # violation: approved_by missing
            "created_by": "tester", "approved_by": None,
            "retire_reason": None,
            "history": [{"version": 1, "date": "2026-10-13", "summary": "s", "author": "a"}],
        }
        errors = validate_research_question(bad)
        self.assertTrue(any("RQ-01" in e for e in errors))

    def test_retired_rq_requires_reason(self):
        base = {
            "rq_id": "rq-demo2", "version": 1, "question": "demo question text",
            "background": "demo background",
            "scope": {
                "population": "p", "age_range": "6-12", "languages": ["en"],
                "publication_types": ["empirical"], "time_window": "2020-2026",
            },
            "search_queries": [{"source": "openalex", "query": "test query"}],
            "inclusion_hints": [], "exclusion_hints": [],
            "domain": "ai_children", "status": "retired",
            "created_by": "tester", "approved_by": "owner", "retire_reason": None,
            "history": [{"version": 1, "date": "2026-10-13", "summary": "s", "author": "a"}],
        }
        errors = validate_research_question(base)
        self.assertTrue(any("RQ-02" in e for e in errors))


class DecisionScopeContractTest(unittest.TestCase):
    def test_contract_examples_pass(self):
        contract, _ = load_contract("decision-scope")
        rqs_doc, _ = load_contract("example-rqs")
        rq_ids = {rq["rq_id"] for rq in rqs_doc["research_questions"]}
        layers = {ex["layer"] for ex in contract["examples"]}
        self.assertEqual(layers, {"catalog", "review"})
        for ex in contract["examples"]:
            self.assertEqual(validate_decision_record(ex), [], f"{ex['record_id']}: errors")
        for ex in contract["examples"]:
            if ex["layer"] == "review":
                self.assertIn(ex["rq_id"], rq_ids)

    def test_review_decision_requires_rq(self):
        record = {
            "record_id": "dec-x", "work_ref": "work:w", "layer": "review",
            "decision": "included", "reason_code": "A01", "reason_text": "ok",
            "reviewer_id": "r1", "decided_at": "2026-10-13", "label_tier": "provisional",
            "rq_id": None, "rq_version": None, "track": "review",
        }
        errors = validate_decision_record(record)
        self.assertTrue(any("DS-02" in e for e in errors))

    def test_catalog_decision_must_use_catalog_domain(self):
        record = {
            "record_id": "dec-y", "work_ref": "work:w", "layer": "catalog",
            "decision": "included", "reason_code": "A01", "reason_text": "ok",
            "reviewer_id": "r1", "decided_at": "2026-10-13", "label_tier": "provisional",
            "rq_id": None, "rq_version": None, "track": "catalog",
        }
        errors = validate_decision_record(record)
        self.assertTrue(any("DS-01" in e for e in errors))

    def test_value_domains_do_not_overlap(self):
        contract, _ = load_contract("decision-scope")
        catalog = set(contract["layers"]["catalog"]["value_domain"])
        review = set(contract["layers"]["review"]["value_domain"])
        self.assertEqual(catalog, {"ingested", "rejected", "pending"})
        self.assertEqual(review, {"included", "excluded", "pending"})
        self.assertEqual(catalog & review, {"pending"})  # shared state, distinct meaning
        self.assertTrue(contract["layers"]["review"]["requires_rq"])
        self.assertFalse(contract["layers"]["catalog"]["requires_rq"])

    def test_forbidden_transitions_declared(self):
        contract, _ = load_contract("decision-scope")
        pairs = {(t["from"], t["to"]) for t in contract["forbidden_state_transitions"]}
        for terminal in ("rejected", "superseded", "retracted"):
            self.assertIn((terminal, "approved"), pairs)


class LabelTiersContractTest(unittest.TestCase):
    def test_contract_examples_pass(self):
        contract, _ = load_contract("label-tiers")
        self.assertEqual(len(contract["examples"]), 2)
        for ex in contract["examples"]:
            self.assertEqual(validate_label_record(ex), [], f"{ex['record_id']}: errors")

    def test_model_may_not_self_confirm_gold(self):
        record = {
            "record_id": "lab-x", "label_tier": "gold", "produced_by_kind": "model",
            "ai_assisted": True, "model_id": "m1", "reviewer_ids": [],
            "sign_off_by": "some-model", "sign_off_date": "2026-10-13",
        }
        errors = validate_label_record(record)
        self.assertTrue(any("LT-03" in e for e in errors))
        self.assertTrue(any("LT-04" in e for e in errors))

    def test_provisional_requires_single_human(self):
        record = {
            "record_id": "lab-y", "label_tier": "provisional",
            "produced_by_kind": "model", "ai_assisted": True, "model_id": "m1",
            "reviewer_ids": [], "sign_off_by": None, "sign_off_date": None,
        }
        errors = validate_label_record(record)
        self.assertTrue(any("LT-02" in e for e in errors))
        self.assertTrue(any("LT-04" in e for e in errors))

    def test_gate_only_accepts_gold(self):
        contract, _ = load_contract("label-tiers")
        gate = contract["tier_rank_for_gate"]
        self.assertTrue(gate["gold"])
        self.assertFalse(gate["provisional"])


class PocMetricsPointerTest(unittest.TestCase):
    def test_pointer_matches_v2_csv(self):
        errors, warnings = check_poc_metrics_pointer()
        self.assertEqual(errors, [], f"poc pointer errors: {errors}")
        self.assertEqual(warnings, [])

    def test_v1_numbers_are_preserved_not_rewritten(self):
        text = (ROOT / "docs/assessment/2026-10-13-poc-tech-evaluation"
                / "FINAL_RECOMMENDATION.md").read_text(encoding="utf-8")
        for probe in ("0.118±.018", "0.152±.011", "0.146±.013", "0.075±.016", "0.067±.034",
                      "| 59 | 68 | 71 | 127 | 136 |"):
            self.assertIn(probe, text, f"original v1 record must stay intact: {probe}")
        self.assertIn("CE-01R-ERRATA.md", text)

    def test_errata_documents_v2_values(self):
        errata = (ROOT / "docs/governance/CE-01R-ERRATA.md").read_text(encoding="utf-8")
        for probe in ("svm 0.068", "nb 0.102", "logistic 0.096", "tfidf_sim 0.025",
                      "random 0.017", "42.6", "72.4", "superseded"):
            self.assertIn(probe, errata)


class DocsConsistencyTest(unittest.TestCase):
    def test_document_set_is_consistent(self):
        errors, warnings = check_governance_docs()
        self.assertEqual(errors, [], f"governance docs errors: {errors}")
        self.assertEqual(warnings, [])

    def test_protocols_stay_draft_and_pending(self):
        from research_library.governance import PROTOCOL_FILES
        for rel in PROTOCOL_FILES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("DRAFT v1.1", text)
            self.assertIn("待人工审核", text)
            self.assertNotIn("APPROVED", text)

    def test_agents_md_declares_draft_not_effective(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("DRAFT 规程不可被 Agent 当作生效准则", agents)
        self.assertIn("被当作不可变规范引用", agents)
        self.assertIn("test_governance_contracts.py", agents)

    def test_checklist_requires_human_signoff_and_is_unsigned(self):
        checklist = (ROOT / "docs/governance/CE-01R-CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("不得自动勾选、代签", checklist)
        self.assertIn("最终生效签署", checklist)
        self.assertNotIn("| APPROVE |", checklist)

    def test_decision_scope_examples_use_registered_rq_ids(self):
        ds, _ = load_contract("decision-scope")
        rqs_doc, _ = load_contract("example-rqs")
        rq_ids = {rq["rq_id"] for rq in rqs_doc["research_questions"]}
        for ex in ds["examples"]:
            if ex.get("rq_id"):
                self.assertIn(ex["rq_id"], rq_ids)


if __name__ == "__main__":
    unittest.main()
