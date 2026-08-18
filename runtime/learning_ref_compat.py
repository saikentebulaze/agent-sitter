from __future__ import annotations

from pathlib import Path

from project_context import ProjectContext
from reference_resolver import resolve_task_ref


def resolve_task_yaml(context: ProjectContext, value: str | Path) -> Path:
    """Resolve Task ID, Task directory, or task.yaml to the canonical YAML path."""

    return resolve_task_ref(context, value).yaml_path
