from __future__ import annotations

import shutil
from pathlib import Path

import governed_work as _base
from core.work_risk import RiskLevel, RiskVector, raise_to_floor
from governed_validation import validate_governed_work_graph
from project_context import ProjectContext
from review_transaction import atomic_write_yaml
from risk_transaction import current_work_risk, reassess_task_risk
from work_graph import (
    investigation_markdown_path,
    investigation_path,
    load_yaml,
    resolve_change_root,
    resolve_task_root,
)


PivotTransactionError = _base.PivotTransactionError


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.adaptive-restore")
            temporary.write_bytes(content)
            temporary.replace(path)


def pivot_to_change(
    context: ProjectContext,
    task_value: str | Path,
    investigation_id: str,
    *,
    change_id: str,
    title: str,
    rationale: str,
    supersede_change: str | None = None,
) -> Path:
    """Pivot and propagate current Task risk into Production Change assurance.

    An Investigation cannot lower current risk while it is open, so current risk
    at this boundary represents the minimum production proof discovered by the
    Investigation. The existing Change template remains the lower floor.
    """

    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    inv_path = investigation_path(task_root, investigation_id)
    old_paths = [task_path, inv_path]
    if supersede_change:
        old_paths.append(resolve_change_root(context, supersede_change) / "change.yaml")
    before = _snapshot(old_paths)
    new_root = context.project_root / "changes" / "active" / change_id
    new_root_existed = new_root.exists()

    try:
        root = _base.pivot_to_change(
            context,
            task_value,
            investigation_id,
            change_id=change_id,
            title=title,
            rationale=rationale,
            supersede_change=supersede_change,
        )
        change_path = root / "change.yaml"
        change = load_yaml(change_path)
        change["candidate_readiness_protocol"] = 1
        atomic_write_yaml(change_path, change)

        task = load_yaml(task_path)
        risk = current_work_risk(task)
        reassess_task_risk(
            context,
            task_value,
            target=risk,
            reason="propagate current Investigation risk into Production Change assurance",
            evidence_ref=f"investigation:{investigation_id}",
            raise_assurance=True,
        )
        validate_governed_work_graph(context, task_root)
        return root
    except BaseException:
        _restore(before)
        if not new_root_existed and new_root.exists():
            shutil.rmtree(new_root, ignore_errors=True)
        raise


def investigate_change(
    context: ProjectContext,
    change_value: str | Path,
    *,
    title: str,
    question: str,
    signature: str,
    discrimination_rationale: str | None,
) -> str:
    """Pause a Change and automatically raise uncertain production work to HIGH.

    A Change -> Investigation pivot means a production assumption failed or a
    material unknown appeared during implementation/verification. That is at
    least HIGH semantic execution risk. Repository-change risk remains at least
    MEDIUM until further facts justify a stronger floor.
    """

    change_root = resolve_change_root(context, change_value)
    change_path = change_root / "change.yaml"
    change = load_yaml(change_path)
    task_root = resolve_task_root(context, str(change.get("task_id")))
    task_path = task_root / "task.yaml"
    before = _snapshot([task_path, change_path])
    investigation_id: str | None = None

    try:
        investigation_id = _base.investigate_change(
            context,
            change_value,
            title=title,
            question=question,
            signature=signature,
            discrimination_rationale=discrimination_rationale,
        )
        task = load_yaml(task_path)
        floor = RiskVector(RiskLevel.HIGH, RiskLevel.MEDIUM)
        target = raise_to_floor(current_work_risk(task), floor)
        reassess_task_risk(
            context,
            str(task.get("id")),
            target=target,
            reason="production Change produced a new Investigation",
            evidence_ref=f"investigation:{investigation_id}",
            raise_assurance=True,
        )
        validate_governed_work_graph(context, task_root)
        return investigation_id
    except BaseException:
        _restore(before)
        if investigation_id is not None:
            investigation_path(task_root, investigation_id).unlink(missing_ok=True)
            investigation_markdown_path(task_root, investigation_id).unlink(missing_ok=True)
        raise
