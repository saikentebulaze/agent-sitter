from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[1]


class HighRiskAcceptanceFixtureTests(unittest.TestCase):
    def test_fixture_proves_change_and_task_human_gates(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(
                    HARNESS_ROOT
                    / "scripts"
                    / "acceptance"
                    / "high-risk-governance-fixture.py"
                ),
            ],
            cwd=HARNESS_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in (
            "change-proposed-unresolved: pass",
            "change-advanced-unresolved: blocked",
            "change-resolved-unapproved: blocked",
            "change-resolved-approved: pass",
            "task-human-checkpoint-active: blocked",
            "task-human-checkpoint-blocked: pass",
            "high_risk_fixture: passed",
        ):
            self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
