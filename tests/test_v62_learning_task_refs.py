from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TASK_TEMPLATE = (
    ROOT
    / "adapters/default/skills/change-governor/assets/task.yaml.template"
)


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", str(project)],
        check=True,
        text=True,
        capture_output=True,
    )
    lock = project / ".harness/sitter/manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project


def create_task(project: Path, task_id: str) -> Path:
    data = yaml.safe_load(TASK_TEMPLATE.read_text(encoding="utf-8"))
    data["id"] = task_id
    data["title"] = task_id
    data["status"] = "active"
    path = project / ".agent-work" / task_id / "task.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def learning(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RUNTIME / "learning.py"),
            "--project",
            str(project),
            *args,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


class LearningTaskRefCompatibilityTests(unittest.TestCase):
    def test_learning_accepts_id_directory_and_yaml_forms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            first = create_task(project, "task-id-form")
            second = create_task(project, "task-yaml-form")

            result = learning(project, "intake", "task-id-form")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = learning(
                project,
                "closeout",
                ".agent-work/task-id-form",
                "--reason",
                "no durable learning",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = learning(
                project,
                "intake",
                str(second.relative_to(project)),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = learning(
                project,
                "closeout",
                "task-yaml-form",
                "--reason",
                "no durable learning",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())


if __name__ == "__main__":
    unittest.main()
