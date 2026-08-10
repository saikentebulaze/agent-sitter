from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import yaml

import install as installer_module


ROOT = Path(__file__).resolve().parents[1]


class ProviderInstallationTests(unittest.TestCase):
    def create_project(self, directory: str) -> Path:
        project = Path(directory) / "project"
        project.mkdir()
        completed = subprocess.run(
            ["git", "init", str(project)],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return project

    def test_manifest_records_provider_ownership_with_portable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(directory)
            installer_module.install(project, dry_run=False)
            lock = yaml.safe_load(
                (
                    project
                    / ".harness"
                    / "sitter"
                    / "manifest-lock.yaml"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(lock["enabled_providers"], ["codex"])
            self.assertEqual(
                set(lock["projection_owners"]),
                set(lock["projections"]),
            )
            self.assertEqual(set(lock["projection_owners"].values()), {"codex"})
            self.assertTrue(
                all("\\" not in value for value in lock["projections"])
            )

    def test_post_swap_failure_restores_projection_and_exclude_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(directory)
            installer_module.install(project, dry_run=False)
            entrypoint = project / "AGENTS.md"
            exclude = installer_module.git_path(project, "info/exclude")
            before_entrypoint = entrypoint.read_bytes()
            before_exclude = exclude.read_bytes()

            with mock.patch.object(
                installer_module,
                "ensure_project_trusted",
                side_effect=ValueError("injected provider install failure"),
            ):
                with self.assertRaisesRegex(ValueError, "injected provider install failure"):
                    installer_module.install(
                        project,
                        dry_run=False,
                        reinstall=True,
                        trust_project=True,
                        codex_home=Path(directory) / "codex-home",
                    )

            self.assertEqual(entrypoint.read_bytes(), before_entrypoint)
            self.assertEqual(exclude.read_bytes(), before_exclude)

    def test_provider_projection_conflicts_fail_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_project(directory)
            from core.projection_plan import Projection, ProjectionPlan

            conflicting = (
                ProjectionPlan(
                    "codex",
                    (Projection("codex", Path("AGENTS.md"), "codex"),),
                ),
                ProjectionPlan(
                    "claude",
                    (Projection("claude", Path("AGENTS.md"), "claude"),),
                ),
            )
            with mock.patch.object(
                installer_module,
                "provider_plans",
                return_value=conflicting,
            ):
                with self.assertRaisesRegex(ValueError, "ownership conflict"):
                    installer_module.install(project, dry_run=False)
            self.assertFalse((project / "AGENTS.md").exists())
            self.assertFalse((project / ".harness").exists())


if __name__ == "__main__":
    unittest.main()
