from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

import check as checker
import install as installer


class ProviderCheckTests(unittest.TestCase):
    def project(self, directory: str) -> Path:
        project = Path(directory) / "project"
        project.mkdir()
        result = subprocess.run(
            ["git", "init", str(project)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return project

    def test_default_and_dual_provider_installations_pass(self) -> None:
        for providers in (("codex",), ("codex", "claude")):
            with self.subTest(providers=providers), tempfile.TemporaryDirectory() as directory:
                project = self.project(directory)
                installer.install(
                    project,
                    dry_run=False,
                    provider_ids=providers,
                )
                checker.check(project)

    def test_modified_claude_projection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            installer.install(
                project,
                dry_run=False,
                provider_ids=("claude",),
            )
            agent = project / ".claude" / "agents" / "context-scout.md"
            agent.write_text(
                agent.read_text(encoding="utf-8") + "\nuser mutation\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "modified"):
                checker.check(project)

    def test_model_override_without_update_is_reported_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            installer.install(
                project,
                dry_run=False,
                provider_ids=("claude",),
            )
            local = (
                project
                / ".harness"
                / "sitter.models.local.yaml"
            )
            local.write_text(
                "schema_version: 1\n"
                "providers:\n"
                "  claude:\n"
                "    models:\n"
                "      low:\n"
                "        selector: claude-haiku-future\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "stale"):
                checker.check(project)

    def test_update_after_model_override_restores_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            installer.install(
                project,
                dry_run=False,
                provider_ids=("claude",),
            )
            local = (
                project
                / ".harness"
                / "sitter.models.local.yaml"
            )
            local.write_text(
                "schema_version: 1\n"
                "providers:\n"
                "  claude:\n"
                "    models:\n"
                "      low:\n"
                "        selector: claude-haiku-future\n",
                encoding="utf-8",
            )
            installer.install(project, dry_run=False)
            checker.check(project)
            projected = (
                project
                / ".claude"
                / "agents"
                / "context-scout.md"
            ).read_text(encoding="utf-8")
            self.assertIn("model: claude-haiku-future", projected)


if __name__ == "__main__":
    unittest.main()
