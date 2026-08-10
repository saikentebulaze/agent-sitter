from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "runtime"))

from project_context import resolve_project_context  # noqa: E402
from check_agent_profiles import validate_agent_profiles  # noqa: E402
from launch_scout import build_command  # noqa: E402
from self_check import run_self_check  # noqa: E402


class ProjectContextTests(unittest.TestCase):
    def create_project_with_lock(self, directory: str) -> Path:
        project_root = Path(directory) / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        lock = project_root / ".harness" / "sitter" / "manifest-lock.yaml"
        lock.parent.mkdir(parents=True)
        lock.write_text(
            yaml.safe_dump(
                {"package": "sitter", "format_version": 1},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return project_root

    def test_resolves_package_and_project_from_a_local_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = self.create_project_with_lock(directory)

            context = resolve_project_context(project_root, package_root=PACKAGE_ROOT)

            self.assertEqual(context.package_root, PACKAGE_ROOT)
            self.assertEqual(context.project_root, project_root.resolve())
            self.assertEqual(context.adapter_root, PACKAGE_ROOT / "adapters" / "default")

    def test_agent_tools_use_adapter_configuration_and_project_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = self.create_project_with_lock(directory)
            context = resolve_project_context(project_root, package_root=PACKAGE_ROOT)

            validate_agent_profiles(context)
            metadata, command = build_command(
                "context-scout",
                "Inspect no files.",
                context,
            )

            self.assertEqual(command[command.index("-C") + 1], str(project_root.resolve()))
            self.assertEqual(metadata["agent"], "context_scout")
            self.assertEqual(metadata["model"], "gpt-5.6-luna")
            self.assertIn("gpt-5.6-luna", command)

    def test_self_check_uses_the_explicit_project_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = self.create_project_with_lock(directory)
            context = resolve_project_context(project_root, package_root=PACKAGE_ROOT)

            run_self_check(context)

    def test_rejects_a_project_without_the_local_harness_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory) / "project"
            project_root.mkdir()
            (project_root / ".git").mkdir()

            with self.assertRaisesRegex(ValueError, "manifest-lock"):
                resolve_project_context(project_root, package_root=PACKAGE_ROOT)


if __name__ == "__main__":
    unittest.main()
