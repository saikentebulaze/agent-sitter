from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from providers.claude.settings_anchor import (  # noqa: E402
    ClaudeSettingsAnchorError,
    assert_installed_settings_anchor,
    resolve_settings_anchor,
)


class ClaudeSettingsAnchorTests(unittest.TestCase):
    def repository(self, directory: str) -> Path:
        repository = Path(directory) / "repository"
        repository.mkdir()
        result = subprocess.run(
            ["git", "init", str(repository)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "initial",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return repository

    def linked_worktree(self, directory: str) -> tuple[Path, Path]:
        repository = self.repository(directory)
        worktree = Path(directory) / "linked"
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "add",
                str(worktree),
                "-b",
                "linked-test",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return repository, worktree

    def test_main_checkout_anchors_settings_locally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(directory)
            anchor = resolve_settings_anchor(repository)
            self.assertFalse(anchor.is_linked_worktree)
            self.assertEqual(anchor.main_checkout_root, repository.resolve())
            self.assertEqual(
                anchor.settings_path,
                repository.resolve() / ".claude" / "settings.local.json",
            )

    def test_linked_worktree_resolves_main_checkout_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, worktree = self.linked_worktree(directory)
            anchor = resolve_settings_anchor(worktree)
            self.assertTrue(anchor.is_linked_worktree)
            self.assertEqual(anchor.project_root, worktree.resolve())
            self.assertEqual(anchor.main_checkout_root, repository.resolve())
            self.assertEqual(
                anchor.settings_path,
                repository.resolve() / ".claude" / "settings.local.json",
            )

    def test_worktree_local_projection_is_reported_as_wrong_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, worktree = self.linked_worktree(directory)
            local = worktree / ".claude" / "settings.local.json"
            local.parent.mkdir()
            local.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ClaudeSettingsAnchorError,
                "linked worktree",
            ):
                assert_installed_settings_anchor(worktree)

    def test_shared_main_settings_are_accepted_when_worktree_copy_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, worktree = self.linked_worktree(directory)
            shared = repository / ".claude" / "settings.local.json"
            shared.parent.mkdir()
            shared.write_text("{}\n", encoding="utf-8")
            anchor = assert_installed_settings_anchor(worktree)
            self.assertEqual(anchor.settings_path, shared.resolve())


if __name__ == "__main__":
    unittest.main()
