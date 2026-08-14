from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
ACCEPTANCE = ROOT / "scripts" / "acceptance"


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project


def run(project: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


class V6ContextAuthorityTests(unittest.TestCase):
    def test_frozen_baseline_remains_distinct_from_v6_candidate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ACCEPTANCE / "v6-behavior-baseline.py")],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["G1-exploration-gate"]["g1_v6_pass"])
        self.assertFalse(data["task-status-dashboard"]["current_read_only"])
        self.assertTrue(data["task-status-dashboard"]["status_artifact_changed"])

    def test_high_investigation_dashboard_exposes_allowed_and_blocked_next(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            task = "dashboard-critical"
            created = run(
                project,
                "create_task.py",
                task,
                "--title",
                "Dashboard critical",
                "--entry",
                "investigation",
                "--signature",
                "dashboard-critical",
                "--project",
                str(project),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            raised = run(
                project,
                "work.py",
                "--project",
                str(project),
                "reassess-risk",
                task,
                "--semantic",
                "critical",
                "--repository-change",
                "critical",
                "--reason",
                "exercise dashboard gate",
            )
            self.assertEqual(raised.returncode, 0, raised.stderr)

            status_path = project / ".agent-work" / task / "status.md"
            before = status_path.read_bytes()
            status = run(
                project,
                "work.py",
                "--project",
                str(project),
                "task-status",
                task,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            dashboard = json.loads(status.stdout)
            self.assertEqual(before, status_path.read_bytes())
            self.assertEqual(dashboard["risk"]["current"]["semantic"], "critical")
            self.assertIn("record-evidence", dashboard["allowed_next"])
            self.assertIn("record-decision:accepted", dashboard["blocked_next"])
            self.assertIn("conclude-investigation", dashboard["blocked_next"])
            self.assertIn("pivot-to-change", dashboard["blocked_next"])
            self.assertTrue(dashboard["ACTION REQUIRED"])


if __name__ == "__main__":
    unittest.main()
