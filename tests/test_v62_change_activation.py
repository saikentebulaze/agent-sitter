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

    def test_standalone_create_change_activates_protocol_and_binds_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = project(Path(directory))
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME / "create_change.py"),
                    "chg-standalone",
                    "--title",
                    "Standalone change",
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
                (root / "changes/active/chg-standalone/change.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(data["candidate_readiness_protocol"], 1)
            self.assertEqual(data["task_id"], "task-owner")


if __name__ == "__main__":
    unittest.main()
