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
    ROOT / "adapters/default/skills/change-governor/assets/task.yaml.template"
)


def create_project(root: Path) -> tuple[Path, Path]:
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
    data = yaml.safe_load(TASK_TEMPLATE.read_text(encoding="utf-8"))
    data["id"] = "task-ref"
    data["title"] = "Task reference fixture"
    data["status"] = "intake"
    task = project / ".agent-work/task-ref/task.yaml"
    task.parent.mkdir(parents=True)
    task.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return project, task


def work(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RUNTIME / "work.py"),
            "--project",
            str(project),
            *args,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


class WorkTaskRefCompatibilityTests(unittest.TestCase):
    def test_task_status_accepts_id_directory_and_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, task = create_project(Path(directory))
            values = (
                "task-ref",
                ".agent-work/task-ref",
                str(task.relative_to(project)),
            )
            outputs: list[str] = []
            for value in values:
                result = work(project, "task-status", value)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(result.stdout)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[1], outputs[2])


if __name__ == "__main__":
    unittest.main()
