from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from production_snapshot import (  # noqa: E402
    production_review_diff,
    production_snapshot_sha256,
)


def git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        text=True,
        capture_output=True,
    )


class ProductionSnapshotBoundaryTests(unittest.TestCase):
    def test_hidden_harness_runtime_artifacts_do_not_change_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            git(project, "init")
            git(project, "config", "user.email", "tests@example.com")
            git(project, "config", "user.name", "Sitter Tests")
            (project / "src.cpp").write_text("// baseline\n", encoding="utf-8")
            git(project, "add", ".")
            git(project, "commit", "-m", "baseline")
            before = production_snapshot_sha256(project)

            for relative in (
                ".agent-work/task/review-staging/output.md",
                ".harness/sitter/runtime-evidence.yaml",
                "changes/active/chg/review-request.yaml",
                "knowledge/index.yaml",
            ):
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("harness state\n", encoding="utf-8")
            self.assertEqual(before, production_snapshot_sha256(project))

            (project / "new-production.cpp").write_text("// new\n", encoding="utf-8")
            self.assertNotEqual(before, production_snapshot_sha256(project))

    def test_review_diff_contains_tracked_and_untracked_but_not_harness_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            git(project, "init")
            git(project, "config", "user.email", "tests@example.com")
            git(project, "config", "user.name", "Sitter Tests")
            tracked = project / "src.cpp"
            tracked.write_text("int value = 1;\n", encoding="utf-8")
            git(project, "add", ".")
            git(project, "commit", "-m", "baseline")

            tracked.write_text("int value = 2;\n", encoding="utf-8")
            (project / "new.cpp").write_text("int added = 3;\n", encoding="utf-8")
            hidden = project / ".agent-work/task/reviewer-output.md"
            hidden.parent.mkdir(parents=True)
            hidden.write_text("must stay out of review diff\n", encoding="utf-8")

            diff = production_review_diff(project)
            self.assertIn("src.cpp", diff)
            self.assertIn("int value = 2", diff)
            self.assertIn("new.cpp", diff)
            self.assertIn("int added = 3", diff)
            self.assertNotIn("reviewer-output.md", diff)
            self.assertNotIn("must stay out of review diff", diff)


if __name__ == "__main__":
    unittest.main()
