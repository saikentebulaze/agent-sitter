from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HARNESS_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = HARNESS_ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from knowledge_gate import validate_project_knowledge_for_change
from project_context import ProjectContext


class KnowledgeGateTests(unittest.TestCase):
    def context(self, root: Path) -> ProjectContext:
        return ProjectContext(
            package_root=HARNESS_ROOT,
            project_root=root,
            adapter_root=HARNESS_ROOT / "adapters" / "default",
        )

    def write_legacy_project(self, root: Path, status: str) -> Path:
        (root / "knowledge").mkdir(parents=True)
        (root / "knowledge" / "legacy.md").write_text(
            "legacy content",
            encoding="utf-8",
        )
        (root / "knowledge" / "index.yaml").write_text(
            yaml.safe_dump({
                "version": 1,
                "entries": [{
                    "id": "legacy",
                    "title": "Legacy",
                    "kind": "flow",
                    "status": "current",
                    "path": "knowledge/legacy.md",
                    "domains": [],
                    "keywords": [],
                    "related": [],
                }],
            }, sort_keys=False),
            encoding="utf-8",
        )
        change = root / "changes" / "active" / "fixture"
        change.mkdir(parents=True)
        (change / "change.yaml").write_text(
            yaml.safe_dump({
                "status": status,
                "knowledge_sync": {"status": "pending"},
            }),
            encoding="utf-8",
        )
        return change

    def test_legacy_index_warns_before_knowledge_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            change = self.write_legacy_project(root, "approved")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                validate_project_knowledge_for_change(
                    self.context(root),
                    change,
                )
            self.assertIn("WARNING: knowledge index", output.getvalue())
            self.assertIn("migration-plan", output.getvalue())

    def test_legacy_index_blocks_sync_and_archive(self) -> None:
        for status in ("syncing", "ready-to-archive", "archived"):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    change = self.write_legacy_project(root, status)
                    error = io.StringIO()
                    with contextlib.redirect_stderr(error):
                        with self.assertRaises(SystemExit):
                            validate_project_knowledge_for_change(
                                self.context(root),
                                change,
                            )
                    self.assertIn("ERROR: knowledge index", error.getvalue())


if __name__ == "__main__":
    unittest.main()
