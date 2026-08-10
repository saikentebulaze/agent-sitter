from __future__ import annotations

from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.provider_registry import registered_providers  # noqa: E402


class PublicReleaseContractTests(unittest.TestCase):
    def test_manifest_and_readme_describe_sitter_1_0(self) -> None:
        manifest = yaml.safe_load(
            (ROOT / "manifest.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["package"], "sitter")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["adapters"]["default"]["path"], "adapters/default")
        self.assertEqual(registered_providers(), ("claude", "codex"))

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Sitter", readme)
        self.assertIn("A babysitter for coding agents.", readme)
        self.assertIn("Codex", readme)
        self.assertIn("Claude Code", readme)
        self.assertIn("fresh install defaults to Codex-only", readme)

    def test_release_has_one_install_and_one_check_entrypoint(self) -> None:
        self.assertTrue((ROOT / "install.py").is_file())
        self.assertTrue((ROOT / "check.py").is_file())
        self.assertFalse((ROOT / "install_v5b.py").exists())
        self.assertFalse((ROOT / "check_v5b.py").exists())

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("install_v5b.py", readme)
        self.assertNotIn("check_v5b.py", readme)

    def test_public_release_keeps_implemented_provider_and_design_assets(self) -> None:
        for relative in (
            "docs/V5-Provider架构重构说明.md",
            "docs/V5-B-Claude-Code-Provider-Design.md",
            "docs/V5-B-Model-Profiles.md",
            "docs/v5-codex-preservation-contract.md",
            "docs/local-update-and-sharing.md",
            "adapters/default/docs/Claude子Agent运行时验收.md",
            "scripts/acceptance/codex-static-regression.ps1",
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

        provider_root = ROOT / "runtime" / "providers"
        self.assertTrue((provider_root / "codex").exists())
        self.assertTrue((provider_root / "claude").exists())
        self.assertFalse((provider_root / "kimicode").exists())
        self.assertFalse((provider_root / "opencode").exists())
        self.assertFalse((provider_root / "pi").exists())

    def test_public_snapshot_excludes_private_evolution_artifacts(self) -> None:
        self.assertFalse((ROOT / "docs" / "plans").exists())
        self.assertFalse((ROOT / "adapters" / "default" / "examples").exists())

        acceptance = ROOT / "docs" / "acceptance"
        forbidden_dated_reports = (
            "v5a-codex-20260805-final.md",
            "v5a-codex-20260805-initial.md",
            "v5b-automated-20260805-initial.md",
            "v5b-claude-20260806-final.md",
            "v5b-claude-20260807-final-verdict.md",
            "v5b-codex-regression-20260807-final.md",
            "v5b-dual-provider-20260807-final.md",
        )
        for name in forbidden_dated_reports:
            with self.subTest(path=name):
                self.assertFalse((acceptance / name).exists())

        for name in (
            "dynamic-risk-codex-claude-acceptance-template.md",
            "v5b-claude-acceptance-template.md",
            "v5b-codex-regression-template.md",
            "v5b-dual-provider-template.md",
        ):
            with self.subTest(path=name):
                self.assertTrue((acceptance / name).is_file())

    def test_public_release_has_license(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)


if __name__ == "__main__":
    unittest.main()
