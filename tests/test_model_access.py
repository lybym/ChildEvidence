import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research_library import model_access as access


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pdf = self.root / "source.pdf"
        self.pdf.write_bytes(b"synthetic PDF fixture")
        self.source = self.root / "source.txt"
        self.source.write_text("allowed text SECRET excluded", encoding="utf-8")
        self.directory = self.root / "permissions"
        self.record = dict(work_id="lt-test", pdf_sha256=access.sha(self.pdf), source_url="https://publisher.example/article",
                           rights_basis="synthetic owner confirmation", scope=["article_text"], decision="allowed",
                           confirmed_by="fixture owner", confirmed_at="2026-10-14T00:00:00Z",
                           policy_version=access.POLICY_VERSION, codex_environment="fixture-account/settings-v1",
                           sources=[dict(sha256=access.sha(self.source), scope="article_text", ranges=[[0, 12]])])
        access.register(self.record, self.directory)

    def prepare(self, **changes):
        args = dict(work_id="lt-test", pdf=self.pdf, source=self.source, scope="article_text", spans=[[0, 7]],
                    mode="appraise", environment="fixture-account/settings-v1", directory=self.directory)
        args.update(changes)
        return access.prepare(**args)

    def test_current_policy_blocks_even_registered(self):
        result = self.prepare()
        self.assertEqual("policy_not_active", result["reason"])
        self.assertEqual("blocked", result["decision"])
        self.assertFalse((self.directory / "packages").exists())
        self.assertNotIn("SECRET", json.dumps(result))

    def test_staged_builder_minimizes_and_audits(self):
        with patch.object(access, "POLICY_ACTIVE", True):
            result = self.prepare()
        self.assertEqual("allowed", result["decision"])
        package = access.read(result["package_path"])
        self.assertEqual("allowed", package["segments"][0]["text"])
        self.assertNotIn("SECRET", json.dumps(package))
        self.assertEqual(access.sha(result["package_path"]), result["output_sha256"])
        self.assertEqual(1, len(list((self.directory / "audit").iterdir())))

    def test_wrong_bindings_and_excluded_ranges_block(self):
        with patch.object(access, "POLICY_ACTIVE", True):
            for change in (dict(work_id="wrong"), dict(environment="changed"), dict(scope="abstract"),
                           dict(spans=[[0, 20]]), dict(spans=[[True, 2]]), dict(mode="publish"), dict(spans=[])):
                self.assertEqual("blocked", self.prepare(**change)["decision"])
            self.pdf.write_bytes(b"changed")
            self.assertEqual("blocked", self.prepare()["decision"])

    def test_derivative_mutation_and_revocation(self):
        with patch.object(access, "POLICY_ACTIVE", True):
            for decision in ("needs_verification", "restricted"):
                access.register(dict(self.record, decision=decision), self.directory)
                self.assertEqual("blocked", self.prepare()["decision"])
            access.register(self.record, self.directory)
            self.source.write_text("changed text", encoding="utf-8")
            self.assertEqual("blocked", self.prepare()["decision"])
        self.assertEqual(4, len(access.read(self.directory / "permissions.json")))

    def test_invalid_registry_and_no_network(self):
        (self.directory / "permissions.json").write_text('{"decision":"allowed","decision":"restricted"}', encoding="utf-8")
        with patch("socket.socket", side_effect=AssertionError("network")):
            self.assertEqual("blocked", self.prepare()["decision"])
        for field in ("confirmed_by", "rights_basis", "source_url"):
            with self.assertRaises(ValueError):
                access.register(dict(self.record, **{field: ""}), self.directory)

    def test_policy_change_unregistered_and_container_rejected(self):
        with patch.object(access, "POLICY_ACTIVE", True):
            access.register(dict(self.record, policy_version="old"), self.directory)
            self.assertEqual("blocked", self.prepare()["decision"])
            access.register(self.record, self.directory)
            renamed = self.root / "review.json"
            renamed.write_bytes(self.source.read_bytes())
            self.assertEqual("blocked", self.prepare(source=renamed)["decision"])
            self.assertEqual("blocked", self.prepare(directory=self.root / "empty")["decision"])
            result = self.prepare(spans=[["SECRET", "SECRET"]])
            self.assertNotIn("SECRET", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
