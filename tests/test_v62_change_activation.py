from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402


def project(root: Path) -> tuple[Path, ProjectContext]:
    value = root / "project"
    value.mkdir()
    subprocess.run(
        ["git", "init", str(value)],
        check=True,
        text=True,
        capture_output=True,
    )
    lock = value / ".harness/sitter/manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return value, ProjectContext(ROOT, value, ROOT / "adapters/default")


def write_task(root: Path, task_id: str) -> None:
    path = root / ".agent-work" / task_id / "task.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 4,
                "id": task_id,
                "status": "active",
                "execution": {"orchestrator_provider": "codex"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class ChangeActivationTests(unittest.TestCase):
    def test_new_provider_task_change_activates_candidate_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, context = project(Path(directory))
            initialize_provider_task(
                context,
                task_id="task-change",
                title="New production change",
                entry="change",
                provider_id="codex",
                change_id="chg-new",
            )
            data = yaml.safe_load(
                (root / "changes/active/chg-new/change.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(data["candidate_readiness_protocol"], 1)
            self.assertEqual(data["status"], "proposed")
            self.assertEqual(data["task_id"], "task-change")

    def test_standalone_create_change_activates_only_with_real_task_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = project(Path(directory))
            write_task(root, "task-owner")
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME / "create_change.py"),
                    "chg-bound",
                    "--title",
                    "Task-bound standalone command",
                    "--task-id",
                    "task-owner",
                    "--project",
                    str(root),
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = yaml.safe_load(
                (root / "changes/active/chg-bound/change.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(data["candidate_readiness_protocol"], 1)
            self.assertEqual(data["task_id"], "task-owner")

    def test_true_standalone_change_remains_legacy_without_provider_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = project(Path(directory))
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME / "create_change.py"),
                    "chg-legacy",
                    "--title",
                    "Unbound standalone change",
                    "--project",
                    str(root),
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = yaml.safe_load(
                (root / "changes/active/chg-legacy/change.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIsNone(data["candidate_readiness_protocol"])
            self.assertFalse(data.get("task_id"))

    def test_nonexistent_task_cannot_be_used_to_claim_v62_provider_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = project(Path(directory))
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME / "create_change.py"),
                    "chg-bad-binding",
                    "--title",
                    "Bad binding",
                    "--task-id",
                    "missing-task",
                    "--project",
                    str(root),
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("task not found", result.stderr.lower())
            self.assertFalse((root / "changes/active/chg-bad-binding").exists())


if __name__ == "__main__":
    unittest.main()
