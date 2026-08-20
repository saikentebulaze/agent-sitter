from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from project_context import resolve_project_context
from review_transaction import atomic_write_text, atomic_write_yaml


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise SystemExit(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise SystemExit(f"expected YAML mapping: {path}")
    return data


def _validate(context, source: Path) -> None:
    cmd = [
        sys.executable,
        str(context.package_root / "runtime" / "validate_change.py"),
        str(source),
    ]
    result = subprocess.run(cmd, cwd=context.project_root)
    if result.returncode:
        raise SystemExit(result.returncode)


def _rebase_ref(value: object, active_prefix: str, archive_prefix: str) -> object:
    if isinstance(value, str) and value.replace("\\", "/").startswith(active_prefix):
        normalized = value.replace("\\", "/")
        return archive_prefix + normalized[len(active_prefix):]
    return value


def _rebase_change_local_refs(data: dict, change_id: str) -> None:
    """Rebase only operational refs whose files move with the Change.

    Do not rewrite Readiness/Verification/Human-Decision evidence strings: those
    values participate in frozen semantic digests. The paths below are closure
    plumbing rather than reviewed production semantics.
    """

    active_prefix = f"changes/active/{change_id}/"
    archive_prefix = f"changes/archive/{change_id}/"

    methodology = data.get("methodology") or {}
    methodology["test_cleanup_evidence"] = _rebase_ref(
        methodology.get("test_cleanup_evidence"), active_prefix, archive_prefix
    )

    review = data.get("review") or {}
    execution = review.get("execution") or {}
    execution["output_ref"] = _rebase_ref(
        execution.get("output_ref"), active_prefix, archive_prefix
    )
    for round_data in data.get("review_history") or []:
        if not isinstance(round_data, dict):
            continue
        round_execution = round_data.get("execution") or {}
        round_execution["output_ref"] = _rebase_ref(
            round_execution.get("output_ref"), active_prefix, archive_prefix
        )

    knowledge = data.get("knowledge_sync") or {}
    for key in ("candidate_ref", "rendered_diff_ref"):
        knowledge[key] = _rebase_ref(knowledge.get(key), active_prefix, archive_prefix)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("change", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    source = args.change.resolve()
    active_root = (context.project_root / "changes/active").resolve()
    if source.parent != active_root:
        raise SystemExit("change must be a direct child of changes/active")
    if not source.is_dir():
        raise SystemExit(f"change directory not found: {source}")

    change_yaml = source / "change.yaml"
    data = _load(change_yaml)
    if str(data.get("status") or "") != "ready-to-archive":
        raise SystemExit("Change must be ready-to-archive before archive transaction")

    _validate(context, source)
    target = context.project_root / "changes/archive" / source.name
    if target.exists():
        raise SystemExit(f"archive target exists: {target}")
    print(f"{source} -> {target}")
    if args.dry_run:
        return

    original = change_yaml.read_text(encoding="utf-8")
    data["status"] = "archived"
    _rebase_change_local_refs(data, source.name)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        atomic_write_yaml(target / "change.yaml", data)
        # Archived state must itself validate at its final location. This catches
        # stale active-path refs before the archive transaction can report success.
        _validate(context, target)
    except BaseException:
        if target.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(source))
        if source.exists():
            atomic_write_text(source / "change.yaml", original)
        raise
    print("archived")


if __name__ == "__main__":
    main()
