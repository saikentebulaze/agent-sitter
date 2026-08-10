from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_local_update_and_sharing_guide_exists(self) -> None:
        guide = ROOT / "docs" / "local-update-and-sharing.md"

        self.assertTrue(guide.is_file())
        text = guide.read_text(encoding="utf-8")
        self.assertIn("--project", text)
        self.assertIn("worktree", text.lower())
        self.assertIn(".git/info/exclude", text)


if __name__ == "__main__":
    unittest.main()
