from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-or-update-harness.ps1"
DOC = ROOT / "docs" / "one-click-install.md"


class OneClickInstallScriptTests(unittest.TestCase):
    def test_script_contains_guarded_install_and_validation_flow(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        required_fragments = (
            "[string]$ProjectRoot",
            '[string]$HarnessBranch = "master"',
            "--ff-only",
            '"--reinstall"',
            '"--dry-run"',
            '"--trust-project"',
            '"--force-trust-project"',
            '"--adopt-existing"',
            '"unittest", "discover"',
            '"check.py"',
            '"self_check.py"',
            '"work.py"',
            '"delegation_runtime.py"',
            '"status", "--short", "--untracked-files=no"',
            "Installed Harness version",
            "Close existing Codex sessions",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_script_requires_explicit_override_for_risky_cases(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("-ForceTrustProject and -NoTrustProject cannot be used together", text)
        self.assertIn("Harness repository has local changes", text)
        self.assertIn("ProjectRoot must be the Git worktree root", text)
        self.assertIn("Tracked project status changed during Harness installation", text)

    def test_documentation_covers_new_and_existing_projects(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn("Existing Git project", text)
        self.assertIn("New project directory", text)
        self.assertIn("-InitializeGit", text)
        self.assertIn("-AdoptExisting", text)
        self.assertIn("-ForceTrustProject", text)
        self.assertIn("Safety behavior", text)


if __name__ == "__main__":
    unittest.main()
