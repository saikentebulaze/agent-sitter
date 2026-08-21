from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from project_context import ProjectContext


class ReferenceResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class TaskRef:
    id: str
    root: Path
    yaml_path: Path


@dataclass(frozen=True)
class ChangeRef:
    id: str
    root: Path
    yaml_path: Path


def _inside_project(context: ProjectContext, path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(context.project_root)
    except ValueError as error:
        raise ReferenceResolutionError(f"path is outside project: {path}") from error
    return resolved


def _task_candidates(context: ProjectContext, value: str | Path) -> list[Path]:
    raw = Path(value)
    if raw.is_absolute():
        return [raw]
    if len(raw.parts) == 1:
        return [context.project_root / ".agent-work" / raw]
    project_value = context.project_root / raw
    if raw.name == "task.yaml":
        return [project_value.parent]
    return [project_value]


def resolve_task_ref(context: ProjectContext, value: str | Path) -> TaskRef:
    for candidate in _task_candidates(context, value):
        try:
            root = _inside_project(context, candidate)
        except ReferenceResolutionError:
            continue
        if root.is_file() and root.name == "task.yaml":
            root = root.parent
        yaml_path = root / "task.yaml"
        if yaml_path.is_file():
            return TaskRef(id=root.name, root=root, yaml_path=yaml_path)
    raise ReferenceResolutionError(f"task not found: {value}")


def _change_candidates(context: ProjectContext, value: str | Path) -> list[Path]:
    raw = Path(value)
    if raw.is_absolute():
        return [raw]
    if len(raw.parts) == 1:
        return [
            context.project_root / "changes" / "active" / raw,
            context.project_root / "changes" / "archive" / raw,
        ]
    project_value = context.project_root / raw
    if raw.name == "change.yaml":
        return [project_value.parent]
    return [project_value]


def resolve_change_ref(context: ProjectContext, value: str | Path) -> ChangeRef:
    for candidate in _change_candidates(context, value):
        try:
            root = _inside_project(context, candidate)
        except ReferenceResolutionError:
            continue
        if root.is_file() and root.name == "change.yaml":
            root = root.parent
        yaml_path = root / "change.yaml"
        if yaml_path.is_file():
            return ChangeRef(id=root.name, root=root, yaml_path=yaml_path)
    raise ReferenceResolutionError(f"change not found: {value}")
