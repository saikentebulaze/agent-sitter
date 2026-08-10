"""Resolve and diagnose repository-shared Claude local settings anchors."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class ClaudeSettingsAnchorError(ValueError):
    pass


@dataclass(frozen=True)
class ClaudeSettingsAnchor:
    project_root: Path
    git_common_dir: Path
    main_checkout_root: Path
    settings_path: Path
    is_linked_worktree: bool


def _git_path(project: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project), *arguments],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if completed.returncode:
        raise ClaudeSettingsAnchorError(
            f"project is not a usable Git worktree: {project}"
        )
    value = completed.stdout.strip()
    if not value:
        raise ClaudeSettingsAnchorError(
            f"Git returned no value for {' '.join(arguments)}"
        )
    return value


def resolve_settings_anchor(project: Path) -> ClaudeSettingsAnchor:
    project = Path(project).resolve()
    top = Path(_git_path(project, "rev-parse", "--show-toplevel")).resolve()
    raw_common = Path(_git_path(project, "rev-parse", "--git-common-dir"))
    common = raw_common.resolve() if raw_common.is_absolute() else (top / raw_common).resolve()
    if common.name != ".git":
        raise ClaudeSettingsAnchorError(
            "Git common directory is not anchored by a normal main checkout: "
            f"{common}"
        )
    main = common.parent.resolve()
    verification = Path(
        _git_path(main, "rev-parse", "--show-toplevel")
    ).resolve()
    if verification != main:
        raise ClaudeSettingsAnchorError(
            f"resolved main checkout is inconsistent: {main} != {verification}"
        )
    return ClaudeSettingsAnchor(
        project_root=top,
        git_common_dir=common,
        main_checkout_root=main,
        settings_path=main / ".claude" / "settings.local.json",
        is_linked_worktree=(top != main),
    )


def assert_installed_settings_anchor(project: Path) -> ClaudeSettingsAnchor:
    anchor = resolve_settings_anchor(project)
    worktree_settings = anchor.project_root / ".claude" / "settings.local.json"
    if anchor.is_linked_worktree:
        if worktree_settings.is_file() and worktree_settings.resolve() != anchor.settings_path:
            raise ClaudeSettingsAnchorError(
                "Claude local settings are projected into the linked worktree, "
                "but the repository-shared settings anchor is the main checkout: "
                f"{anchor.settings_path}"
            )
        if not anchor.settings_path.is_file():
            raise ClaudeSettingsAnchorError(
                "Claude repository-shared settings are missing from the main checkout: "
                f"{anchor.settings_path}"
            )
    elif not worktree_settings.is_file():
        raise ClaudeSettingsAnchorError(
            f"Claude local settings are missing: {worktree_settings}"
        )
    return anchor
