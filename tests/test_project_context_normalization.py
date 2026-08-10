from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402


class ProjectContextNormalizationTests(unittest.TestCase):
    def test_direct_construction_normalizes_all_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            context = ProjectContext(
                base / "package" / ".." / "package",
                base / "project" / ".." / "project",
                base / "adapter" / ".." / "adapter",
            )
            self.assertEqual(context.package_root, (base / "package").resolve())
            self.assertEqual(context.project_root, (base / "project").resolve())
            self.assertEqual(context.adapter_root, (base / "adapter").resolve())


if __name__ == "__main__":
    unittest.main()
