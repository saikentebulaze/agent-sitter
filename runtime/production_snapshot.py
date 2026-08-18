from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


EXCLUDED_PREFIXES = (
    ".agent-work/",
    ".harness/sitter/",
    "changes/",
    "knowledge/",
)


class ProductionSnapshotError(ValueError):
    pass


def _run_git(project_root: Path, args: list[str], *, binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(project_root), *args],
        text=not binary,
        encoding=None if binary else "utf-8",
        capture_output=True,
    )
    if result.returncode:
        stderr = result.stderr if not binary else result.stderr.decode("utf-8", errors="replace")
        raise ProductionSnapshotError(stderr.strip() or "git command failed")
    return result.stdout


def _excluded(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    return any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def _tracked_patch(project_root: Path) -> bytes:
    output = _run_git(project_root, ["diff", "HEAD", "--binary", "--", "."], binary=True)
    return bytes(output)


def _untracked_paths(project_root: Path) -> list[str]:
    output = _run_git(
        project_root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        binary=True,
    )
    values = [item.decode("utf-8", errors="surrogateescape") for item in bytes(output).split(b"\0") if item]
    return sorted(path for path in values if not _excluded(path))


def production_snapshot_sha256(project_root: Path) -> str:
    """Hash production/test changes while excluding Harness-owned lifecycle state.

    The digest covers staged + unstaged tracked changes relative to HEAD and all
    untracked non-Harness files. Harness evidence/projection updates must not
    invalidate a production review snapshot merely by recording the review.
    """

    digest = hashlib.sha256()
    digest.update(b"production-snapshot-v1\0")
    digest.update(_tracked_patch(project_root))
    for relative in _untracked_paths(project_root):
        path = project_root / Path(relative)
        if not path.is_file():
            continue
        digest.update(b"untracked\0")
        digest.update(relative.replace("\\", "/").encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
