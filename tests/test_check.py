from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PACKAGE_ROOT / "install.py"
CHECKER = PACKAGE_ROOT / "check.py"


def run_command(script: Path, project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--project", str(project)],
        cwd=PACKAGE_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


class CheckTests(unittest.TestCase):
    def create_installed_project(self, directory: str) -> Path:
        project = Path(directory) / "project"
        project.mkdir()
        result = subprocess.run(["git", "init", str(project)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_command(INSTALLER, project)
        self.assertEqual(result.returncode, 0, result.stderr)
        return project

    def test_check_passes_for_a_fresh_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_installed_project(directory)

            result = run_command(CHECKER, project)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("harness_check: passed", result.stdout)

    def test_check_reports_a_modified_generated_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_installed_project(directory)
            entrypoint = project / "AGENTS.md"
            entrypoint.write_text(entrypoint.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

            result = run_command(CHECKER, project)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AGENTS.md", result.stderr)

    def test_update_repairs_a_drifted_generated_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.create_installed_project(directory)
            entrypoint = project / "AGENTS.md"
            entrypoint.write_text(entrypoint.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(INSTALLER), "--project", str(project), "--update"],
                cwd=PACKAGE_ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_command(CHECKER, project)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
