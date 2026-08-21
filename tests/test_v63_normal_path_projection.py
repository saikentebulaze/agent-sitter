from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from providers.claude.projection import skill_wrapper_text as claude_skill_wrapper_text  # noqa: E402
from providers.codex.projection import skill_wrapper_text as codex_skill_wrapper_text  # noqa: E402


GOVERNOR = ROOT / "adapters/default/skills/change-governor/SKILL.md"


class V63NormalPathProjectionTests(unittest.TestCase):
    def test_governor_projects_compact_two_transaction_normal_path(self) -> None:
        text = GOVERNOR.read_text(encoding="utf-8")
        self.assertLess(len(text.encode("utf-8")), 10000)
        for marker in (
            "prepare-candidate",
            "--readiness-batch",
            "candidate-review",
            "complete-after-approval",
            "--verification-batch",
            "governance-closure-pending",
            "recovery/compatibility APIs",
            "not the normal success path",
            "finalize_tests.py",
        ):
            self.assertIn(marker, text)

    def test_codex_and_claude_skill_wrappers_expose_same_normal_path(self) -> None:
        for projected in (
            codex_skill_wrapper_text(GOVERNOR),
            claude_skill_wrapper_text(GOVERNOR),
        ):
            self.assertIn("prepare-candidate", projected)
            self.assertIn("--readiness-batch", projected)
            self.assertIn("complete-after-approval", projected)
            self.assertIn("--verification-batch", projected)
            self.assertIn("recovery/compatibility", projected)

    def test_public_harness_help_advertises_v63_before_recovery_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RUNTIME / "harness.py"), "--help"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("V6.3 normal-path commands", result.stdout)
        self.assertIn("prepare-candidate CHANGE --readiness-batch FILE", result.stdout)
        self.assertIn("complete-after-approval CHANGE", result.stdout)
        self.assertIn("V6.2 compatibility/recovery commands", result.stdout)


if __name__ == "__main__":
    unittest.main()
