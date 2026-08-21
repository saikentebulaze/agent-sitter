from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import install  # noqa: E402
from providers.claude.projection import skill_wrapper_text as claude_skill_wrapper_text  # noqa: E402
from providers.codex.projection import skill_wrapper_text as codex_skill_wrapper_text  # noqa: E402


GOVERNOR = ROOT / "adapters/default/skills/change-governor/SKILL.md"
MIRROR_REF = ".harness/sitter/adapters/default/skills/change-governor/SKILL.md"


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

    def test_codex_and_claude_skill_bridges_point_to_same_authoritative_governor(self) -> None:
        for projected in (
            codex_skill_wrapper_text(GOVERNOR),
            claude_skill_wrapper_text(GOVERNOR),
        ):
            self.assertIn(MIRROR_REF, projected)
            self.assertIn("generated discovery bridge", projected)
            self.assertNotIn("--readiness-batch", projected)
            self.assertNotIn("--verification-batch", projected)

    def test_dual_provider_install_exposes_normal_path_through_authoritative_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            subprocess.run(
                ["git", "init", str(project)],
                check=True,
                text=True,
                capture_output=True,
            )
            install.install(
                project,
                dry_run=False,
                provider_ids=("codex", "claude"),
            )
            mirror = project / MIRROR_REF
            self.assertTrue(mirror.is_file())
            mirror_text = mirror.read_text(encoding="utf-8")
            self.assertIn("prepare-candidate", mirror_text)
            self.assertIn("--readiness-batch", mirror_text)
            self.assertIn("complete-after-approval", mirror_text)
            self.assertIn("--verification-batch", mirror_text)

            for bridge in (
                project / ".agents/skills/change-governor/SKILL.md",
                project / ".claude/skills/change-governor/SKILL.md",
            ):
                self.assertTrue(bridge.is_file())
                self.assertIn(MIRROR_REF, bridge.read_text(encoding="utf-8"))

            lock = yaml.safe_load(
                (project / ".harness/sitter/manifest-lock.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(lock["enabled_providers"], ["codex", "claude"])

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
