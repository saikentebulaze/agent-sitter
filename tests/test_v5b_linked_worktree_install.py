from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

import yaml

import check
import install


class V5BLinkedWorktreeInstallTests(unittest.TestCase):
    def repository_and_worktree(self, directory: str) -> tuple[Path, Path]:
        repository = Path(directory) / "repository"
        repository.mkdir()
        subprocess.run(
            ["git", "init", str(repository)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
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
            check=True,
            capture_output=True,
        )
        worktree = Path(directory) / "worktree"
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "add",
                str(worktree),
                "-b",
                "v5b-test",
            ],
            check=True,
            capture_output=True,
        )
        return repository, worktree

    def test_fresh_linked_install_does_not_create_user_local_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, worktree = self.repository_and_worktree(directory)
            install.install(
                worktree,
                dry_run=False,
                provider_ids=("claude",),
            )

            self.assertFalse(
                (repository / ".claude" / "settings.local.json").exists()
            )
            self.assertFalse(
                (worktree / ".claude" / "settings.local.json").exists()
            )
            governed = (
                worktree
                / ".harness"
                / "sitter"
                / "adapters"
                / "default"
                / "claude"
                / "governed-settings.json"
            )
            self.assertTrue(governed.is_file())
            lock = yaml.safe_load(
                (
                    worktree
                    / ".harness"
                    / "sitter"
                    / "manifest-lock.yaml"
                ).read_text(encoding="utf-8")
            )
            self.assertNotIn(
                ".claude/settings.local.json",
                lock["projections"],
            )
            check.check(worktree)

    def test_main_and_worktree_user_settings_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, worktree = self.repository_and_worktree(directory)
            main = repository / ".claude" / "settings.local.json"
            local = worktree / ".claude" / "settings.local.json"
            main.parent.mkdir()
            local.parent.mkdir()
            main.write_text('{"main":"user"}\n', encoding="utf-8")
            local.write_text('{"worktree":"user"}\n', encoding="utf-8")
            before = (main.read_bytes(), local.read_bytes())

            install.install(
                worktree,
                dry_run=False,
                provider_ids=("claude",),
            )
            install.install(worktree, dry_run=False)

            self.assertEqual((main.read_bytes(), local.read_bytes()), before)
            check.check(worktree)


if __name__ == "__main__":
    unittest.main()
