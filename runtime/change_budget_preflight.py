from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from production_snapshot import EXCLUDED_PREFIXES
from project_context import ProjectContext
from reference_resolver import resolve_change_ref


class ChangeBudgetPreflightError(ValueError):
    pass


def _run_git(project_root: Path, args: list[str], *, allow_failure: bool = False):
    result = subprocess.run(
        ["git", "-C", str(project_root), *args],
        text=False,
        capture_output=True,
    )
    if result.returncode and not allow_failure:
        raise ChangeBudgetPreflightError(
            result.stderr.decode("utf-8", errors="replace").strip() or "git command failed"
        )
    return result


def _has_head(project_root: Path) -> bool:
    return _run_git(project_root, ["rev-parse", "--verify", "HEAD"], allow_failure=True).returncode == 0


def _normalize(path: str) -> str:
    value = path.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _excluded(path: str) -> bool:
    value = _normalize(path) + "/"
    return any(value.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def changed_production_paths(project_root: Path) -> list[str]:
    """Return changed/untracked production paths used by Candidate scope preflight."""

    if _has_head(project_root):
        tracked_args = ["diff", "HEAD", "--name-only", "-z", "--", "."]
    else:
        tracked_args = ["diff", "--cached", "--name-only", "-z", "--", "."]
    tracked = _run_git(project_root, tracked_args).stdout.split(b"\0")
    untracked = _run_git(
        project_root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ).stdout.split(b"\0")
    values: set[str] = set()
    for raw in [*tracked, *untracked]:
        if not raw:
            continue
        path = _normalize(raw.decode("utf-8", errors="surrogateescape"))
        if path and not _excluded(path):
            values.add(path)
    return sorted(values)


def _path_allowed(path: str, *, files: set[str], prefixes: tuple[str, ...]) -> bool:
    if path in files:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def validate_change_budget_preflight(
    context: ProjectContext,
    change_value: str | Path,
) -> list[str]:
    """Mechanically reject out-of-budget production/test paths before Reviewer cost.

    Compatibility rule: a Change that declares no path-level budget at all keeps
    legacy behavior.  Once any allowed file/module/test path is declared, every
    changed production/test path must fit that declared surface.
    """

    ref = resolve_change_ref(context, change_value)
    try:
        data = yaml.safe_load(ref.yaml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ChangeBudgetPreflightError(f"cannot read {ref.yaml_path}: {error}") from error
    if not isinstance(data, dict):
        raise ChangeBudgetPreflightError(f"expected YAML mapping: {ref.yaml_path}")

    budget = data.get("change_budget") or {}
    allowed_files = {
        _normalize(str(value))
        for value in (budget.get("allowed_files") or [])
        if str(value).strip()
    }
    module_prefixes = tuple(
        sorted(
            {
                _normalize(str(value))
                for value in (budget.get("allowed_modules") or [])
                if str(value).strip()
            }
        )
    )
    test_values = {
        _normalize(str(value))
        for value in (budget.get("allowed_test_changes") or [])
        if str(value).strip()
    }

    # Historical/direct fixtures often leave the path budget empty. Do not make
    # RC2 a retroactive schema migration; explicit path budgets opt into the
    # mechanical preflight.
    if not allowed_files and not module_prefixes and not test_values:
        return []

    files = allowed_files | test_values
    test_prefixes = tuple(sorted(test_values))
    prefixes = tuple(dict.fromkeys([*module_prefixes, *test_prefixes]))
    changed = changed_production_paths(context.project_root)
    outside = [
        path for path in changed
        if not _path_allowed(path, files=files, prefixes=prefixes)
    ]
    if outside:
        raise ChangeBudgetPreflightError(
            "out-of-budget production/test paths before Candidate review: "
            + ", ".join(outside)
        )
    return changed
