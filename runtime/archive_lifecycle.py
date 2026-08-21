from __future__ import annotations

from pathlib import Path

import yaml

from change_validation import ChangeValidationError, validate_change_in_process
from project_context import ProjectContext
from reference_resolver import resolve_change_ref, resolve_task_ref
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import now_iso


class ArchiveLifecycleError(ValueError):
    pass


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ArchiveLifecycleError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ArchiveLifecycleError(f"expected YAML mapping: {path}")
    return data


def _remaining_experiments(task_root: Path) -> list[str]:
    root = task_root / "experiments"
    if not root.exists():
        return []
    if not root.is_dir():
        raise ArchiveLifecycleError(f"Task experiments path is not a directory: {root}")
    values: list[str] = []
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            values.append(path.relative_to(task_root).as_posix())
    return sorted(values)


def finalize_archive_cleanup(
    context: ProjectContext,
    change_value: str | Path,
    *,
    evidence: str,
) -> str:
    """Explicitly prove that development experiments are gone before archive.

    The transaction never deletes experiments or temporary production files.
    It only records completion after the owning Task's experiments directory is
    empty and the Change has no declared temporary production artifacts.
    """

    evidence = evidence.strip()
    if not evidence:
        raise ArchiveLifecycleError("archive cleanup evidence is required")

    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise ArchiveLifecycleError(
            "finalize-archive-cleanup is only available for candidate_readiness_protocol 1 Changes"
        )
    if str(data.get("status") or "") != "syncing":
        raise ArchiveLifecycleError(
            "archive cleanup can only be finalized while Change status is syncing"
        )

    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise ArchiveLifecycleError("V6.2 Change has no owning Task for experiment cleanup")
    task = resolve_task_ref(context, task_id)
    remaining = _remaining_experiments(task.root)
    if remaining:
        raise ArchiveLifecycleError(
            "development experiments remain; remove or promote them before archive cleanup: "
            + ", ".join(remaining)
        )

    archive = data.setdefault("archive", {})
    temporary = archive.get("temporary_production_files") or []
    if not isinstance(temporary, list):
        raise ArchiveLifecycleError("archive.temporary_production_files must be a list")
    if temporary:
        raise ArchiveLifecycleError(
            "temporary production files remain: " + ", ".join(map(str, temporary))
        )

    if archive.get("experiment_cleanup_complete") is True:
        existing = str(archive.get("cleanup_evidence") or "").strip()
        if existing == evidence:
            return "complete"
        raise ArchiveLifecycleError(
            "archive cleanup is already complete with different evidence"
        )

    original = ref.yaml_path.read_text(encoding="utf-8")
    archive.update(
        {
            "experiment_cleanup_complete": True,
            "cleanup_evidence": evidence,
            "cleanup_at": now_iso(),
        }
    )
    try:
        atomic_write_yaml(ref.yaml_path, data)
        validate_change_in_process(ref.root)
    except (ChangeValidationError, OSError, ValueError) as error:
        atomic_write_text(ref.yaml_path, original)
        raise ArchiveLifecycleError(str(error)) from error
    return "complete"
