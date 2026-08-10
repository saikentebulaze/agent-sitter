from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path


MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
BACKTICK_TOKEN = re.compile(r"`([A-Za-z_][A-Za-z0-9_:~<>]*)`")
ARTIFACTS = (
    "proposal.md", "design.md", "tasks.md", "verification.md",
    "knowledge-sync.md", "archive-summary.md",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def git_diff_sha256(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(project_root), "diff", "--binary", "--", "."],
        text=False,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
    return hashlib.sha256(result.stdout).hexdigest()


def validate_markdown_links(change_root: Path, project_root: Path) -> list[str]:
    errors: list[str] = []
    project_root = project_root.resolve()
    for name in ARTIFACTS:
        path = change_root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            candidate = (path.parent / target).resolve()
            try:
                candidate.relative_to(project_root)
            except ValueError:
                errors.append(f"{name}: link escapes project: {raw_target}")
                continue
            if not candidate.exists():
                errors.append(f"{name}: broken link: {raw_target}")
    return errors


def symbol_warnings(change_root: Path, project_root: Path) -> list[str]:
    tokens: set[str] = set()
    for name in ("design.md", "tasks.md", "verification.md"):
        path = change_root / name
        if not path.is_file():
            continue
        for token in BACKTICK_TOKEN.findall(path.read_text(encoding="utf-8")):
            # Restrict to tokens that look like code symbols. Plain English words
            # in backticks should not create noisy repository-wide warnings.
            if "::" in token or token.endswith("_") or "_" in token:
                tokens.add(token)

    warnings: list[str] = []
    for token in sorted(tokens):
        result = subprocess.run(
            ["git", "-C", str(project_root), "grep", "-n", "-F", "--", token],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if result.returncode == 1:
            warnings.append(
                f"symbol not found in tracked project files: {token} "
                "(confirm rename/removal or mark it as historical text)"
            )
        elif result.returncode not in {0, 1}:
            warnings.append(f"could not verify symbol {token}: {result.stderr.strip()}")
    return warnings
