from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HarnessCliTests(unittest.TestCase):
    def test_closure_cli_lists_review_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "harness.py"), "--help"],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in (
            "status", "validate-change", "review", "record-review",
            "render-knowledge-diff", "promote-knowledge", "archive",
        ):
            self.assertIn(command, result.stdout)

    def test_work_cli_lists_v4_graph_and_delegation_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "work.py"), "--help"],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in (
            "task-status", "validate", "record-evidence", "record-claim", "record-decision",
            "pivot-to-change", "investigate-change", "conclude-investigation",
            "request-model-review", "record-model-review", "resolve-human-checkpoint",
            "complete-task", "authorize-delegation", "request-delegation",
            "record-delegation-result", "supplement-delegation-context",
            "fail-delegation", "cancel-delegation", "delegation-status",
        ):
            self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
