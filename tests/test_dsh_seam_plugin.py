"""DSH seam-verification plugin tests (Issue #13).

Covers the repository-checkable deliverables of Issue #13
(``[P0][DSH] 验证原生插件、统一接口与受控输出接缝``):

- the plugin package is dependency-free so ``pnpm add file:`` installs offline
  in an isolated profile;
- the Cordis bundle patch declares the plugin and demo-only fixture config
  (parsed with the repo's standard-library mini YAML parser);
- shipped schema mirrors stay inside the schema subset the installed host
  enforces and match the structure documented in contracts.md §2/§4;
- synthetic hygiene: only ``demo-*`` fixture identifiers, no credentials;
- the Node self-check (controlled flow, refusals, unknown preservation,
  subject isolation, idempotency, cooperative cancel, load/unload receipts)
  passes under a real Node runtime when one is available;
- verification docs exist and keep the supported/unsupported/unknown matrix
  with the full issue URL.

All checks are offline. Node-dependent tests are skipped (not failed) when no
Node runtime can be located; the live isolated-profile verification steps are
documented in docs/verification/ and additionally run when the environment
variable ``CE_DSH_VERIFY_PROFILE`` points at an installed profile.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "plugins" / "growth-support-seams"
ISSUE_URL = "https://github.com/lybym/ChildEvidence/issues/13"

SCHEMA_KEYS_ALLOWED = {"type", "properties", "required", "enum", "items", "description", "$id"}

CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
)


def _load_package_json() -> dict:
    return json.loads((PLUGIN_DIR / "package.json").read_text(encoding="utf-8"))


def _schema_files() -> list[Path]:
    return sorted((PLUGIN_DIR / "schemas").glob("*.json"))


def _find_node() -> str | None:
    """Locate a Node runtime: explicit env override, PATH, then the bundled
    DeepSeek Harness runtime (Windows layout)."""
    override = os.environ.get("CE_DSH_NODE")
    if override and Path(override).is_file():
        return override
    found = shutil.which("node")
    if found:
        return found
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidate = (
            Path(local_app)
            / "Programs"
            / "DeepSeek Harness"
            / "resources"
            / "runtime"
            / "primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        )
        if candidate.is_file():
            return str(candidate)
    return None


class PluginPackageTests(unittest.TestCase):
    """Repo-level contract of the shipped plugin bundle."""

    def test_package_manifest_declares_dependency_free_bundle(self) -> None:
        manifest = _load_package_json()
        self.assertEqual(manifest["name"], "ce-growth-support-seams")
        self.assertEqual(manifest["type"], "module")
        for dep_key in (
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies",
        ):
            self.assertNotIn(dep_key, manifest, f"{dep_key} would force network resolution on install")
        patch_rel = manifest["dsh"]["bundle"]["patch"]
        self.assertTrue((PLUGIN_DIR / patch_rel).is_file(), "bundle patch file must exist")
        for entry_rel in (manifest["main"], *manifest["exports"].values()):
            self.assertTrue((PLUGIN_DIR / entry_rel).is_file(), f"declared export missing: {entry_rel}")

    def test_bundle_patch_declares_plugin_and_demo_config(self) -> None:
        from research_library.mini_yaml import parse

        patch = parse((PLUGIN_DIR / "cordis.patch.yml").read_text(encoding="utf-8"))
        self.assertIsInstance(patch, list)
        self.assertEqual(len(patch), 1)
        insert_entries = patch[0]["insert"]
        self.assertEqual(len(insert_entries), 1)
        entry = insert_entries[0]
        self.assertEqual(entry["id"], "ce-growth-support-seams")
        self.assertEqual(entry["name"], "ce-growth-support-seams")
        config = entry["config"]
        self.assertNotIn("receipt_dir", config, "receipts are enabled by a verification overlay, not by default")
        for scope in config["authorized_scopes"]:
            self.assertTrue(scope["scope_ref"].startswith("demo-"))
            self.assertTrue(scope["subject_ref"].startswith("demo-"))
            self.assertTrue(scope["allow"])
        for method in config["methods"]:
            self.assertTrue(method["ref"].startswith("demo-method-"))
            self.assertEqual(method["basis_kind"], "design_choice")
            self.assertTrue(method["action_kinds"])
            self.assertTrue(method["intents"])

    def test_schema_mirrors_exist_and_stay_inside_host_subset(self) -> None:
        files = _schema_files()
        self.assertGreaterEqual(len(files), 5, "contract mirrors must ship with the plugin")
        allowed_types = {"string", "number", "integer", "boolean", "object", "array", "null"}

        def walk(node: dict, path: str) -> None:
            self.assertIsInstance(node, dict)
            unknown = set(node) - SCHEMA_KEYS_ALLOWED
            self.assertFalse(unknown, f"{path} uses keys outside the host subset: {sorted(unknown)}")
            self.assertIn(node["type"], allowed_types, f"{path}.type not in host subset")
            for child in (node.get("properties") or {}).values():
                walk(child, path)

        for schema_file in files:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            self.assertTrue(schema["$id"].startswith("ce.support-"), schema_file.name)
            walk(schema, schema_file.name)

    def test_synthetic_hygiene_demo_only_and_no_credentials(self) -> None:
        scanned = 0
        for pattern in PLUGIN_DIR.rglob("*"):
            if pattern.is_file() and pattern.suffix in {".js", ".mjs", ".json", ".yml", ".md"}:
                text = pattern.read_text(encoding="utf-8")
                for regex in CREDENTIAL_PATTERNS:
                    self.assertIsNone(
                        regex.search(text),
                        f"credential-like literal found in {pattern.relative_to(PLUGIN_DIR)}",
                    )
                scanned += 1
        self.assertGreaterEqual(scanned, 10)
        patch_text = (PLUGIN_DIR / "cordis.patch.yml").read_text(encoding="utf-8")
        for match in re.finditer(r"(scope_ref|subject_ref|ref):\s*(\S+)", patch_text):
            value = match.group(2)
            self.assertTrue(
                value.startswith("demo-"),
                f"non-demo fixture identifier in bundle patch: {value}",
            )


class NodeSelfCheckTests(unittest.TestCase):
    """Behavioral checks that need a real Node runtime; skipped without one."""

    NODE: str | None = _find_node()

    @classmethod
    def setUpClass(cls) -> None:
        if cls.NODE is None:
            raise unittest.SkipTest(
                "no Node runtime found (set CE_DSH_NODE or install Node); "
                "the bundled DeepSeek Harness runtime is used when present"
            )

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.NODE, *args],
            cwd=PLUGIN_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

    def test_node_self_check_passes(self) -> None:
        result = self._run(str(PLUGIN_DIR / "tests" / "self-check.mjs"))
        self.assertEqual(
            result.returncode,
            0,
            f"node self-check failed:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}",
        )
        self.assertIn("pass 20", result.stdout)
        self.assertIn("fail 0", result.stdout)

    def test_host_schema_validation_against_isolated_profile(self) -> None:
        profile_dir = os.environ.get("CE_DSH_VERIFY_PROFILE")
        if not profile_dir:
            self.skipTest(
                "CE_DSH_VERIFY_PROFILE not set; live isolated-profile validation is "
                "performed once per verification run and recorded in docs/verification/"
            )
        script = PLUGIN_DIR / "tools" / "validate-with-host.mjs"
        result = self._run(str(script), profile_dir)
        self.assertEqual(
            result.returncode,
            0,
            f"host validation failed:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}",
        )
        self.assertIn("ALL HOST-VALIDATION CHECKS PASSED", result.stdout)


class VerificationDocsTests(unittest.TestCase):
    """The issue requires a capability matrix and honest verification scope."""

    def test_verification_docs_exist_with_matrix_and_issue_url(self) -> None:
        verification_dir = ROOT / "docs" / "verification" / "dsh-seam-verification"
        matrix = verification_dir / "CAPABILITY-MATRIX.md"
        report = verification_dir / "REPORT.md"
        self.assertTrue(matrix.is_file(), "supported/unsupported/unknown capability matrix must be delivered")
        self.assertTrue(report.is_file(), "verification report must be delivered")
        matrix_text = matrix.read_text(encoding="utf-8")
        for status in ("supported", "unsupported", "unknown"):
            self.assertIn(status, matrix_text)
        report_text = report.read_text(encoding="utf-8")
        self.assertIn(ISSUE_URL, report_text, "the report must carry the full issue URL")
        self.assertIn("0.2.1-rc.2", report_text, "the actually installed host version must be recorded")

    def test_plugin_readme_documents_isolated_lifecycle(self) -> None:
        readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
        for required in (
            "--from-default-profile",
            "DSH_HOME",
            "dsh plugin",
            "dsh --profile",
            ISSUE_URL,
        ):
            self.assertIn(required, readme, f"plugin README must document {required!r}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
