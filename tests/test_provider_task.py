from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import provider_task  # noqa: E402
from core.task_runtime import orchestrator_provider  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from work_graph import load_yaml  # noqa: E402


class ProviderTaskTests(unittest.TestCase):
    def context(self, project: Path) -> ProjectContext:
        return ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    def test_default_creation_preserves_codex_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = provider_task.initialize_provider_task(
                self.context(project),
                task_id="provider-task-codex",
                title="Codex task",
                entry="investigation",
                signature="provider-task-codex",
            )
            task = load_yaml(root / "task.yaml")
            self.assertEqual(orchestrator_provider(task), "codex")

    def test_claude_creation_binds_task_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = provider_task.initialize_provider_task(
                self.context(project),
                task_id="provider-task-claude",
                title="Claude task",
                entry="investigation",
                provider_id="claude",
                signature="provider-task-claude",
            )
            task = load_yaml(root / "task.yaml")
            self.assertEqual(orchestrator_provider(task), "claude")
            self.assertEqual(
                [
                    item.get("provider")
                    for item in task.get("timeline") or []
                    if item.get("type") == "orchestrator-provider-bound"
                ],
                ["claude"],
            )

    def test_unknown_provider_creates_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with self.assertRaisesRegex(ValueError, "Unsupported runtime provider"):
                provider_task.initialize_provider_task(
                    self.context(project),
                    task_id="provider-task-unknown",
                    title="Unknown task",
                    entry="investigation",
                    provider_id="opencode",
                    signature="provider-task-unknown",
                )
            self.assertFalse((project / ".agent-work").exists())

    def test_post_binding_validation_failure_rolls_back_task_and_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with mock.patch.object(
                provider_task,
                "validate_governed_work_graph",
                side_effect=ValueError("injected provider validation failure"),
            ):
                with self.assertRaisesRegex(ValueError, "injected provider"):
                    provider_task.initialize_provider_task(
                        self.context(project),
                        task_id="provider-task-rollback",
                        title="Rollback task",
                        entry="change",
                        provider_id="claude",
                        change_id="provider-change-rollback",
                    )
            self.assertFalse(
                (project / ".agent-work" / "provider-task-rollback").exists()
            )
            self.assertFalse(
                (
                    project
                    / "changes"
                    / "active"
                    / "provider-change-rollback"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
