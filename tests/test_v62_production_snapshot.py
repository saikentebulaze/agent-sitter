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

from production_snapshot import production_snapshot_sha256  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
