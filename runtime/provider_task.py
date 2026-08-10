"""Provider-aware Task creation without changing legacy Codex defaults."""

from __future__ import annotations

import shutil
from pathlib import Path

from core.provider_registry import get_provider
from governed_validation import validate_governed_work_graph
from governed_work import PivotTransactionError, initialize_task as initialize_legacy_task
from project_context import ProjectContext
from review_transaction import atomic_write_yaml
from work_graph import load_yaml, now_iso


DEFAULT_ORCHESTRATOR_PROVIDER = "codex"


def initialize_provider_task(
    context: ProjectContext,
    *,
    task_id: str,
    title: str,
    entry: str,
    provider_id: str = DEFAULT_ORCHESTRATOR_PROVIDER,
    question: str | None = None,
    signature: str | None = None,
    change_id: str | None = None,
    change_title: str | None = None,
) -> Path:
    """Create one Task and immutably bind its orchestrator Provider.

    The retained V4/V5-A transaction remains the source of Task and Change
    creation semantics. V5-B adds the Provider binding immediately after that
    transaction and removes every newly-created artifact if the binding or the
    final work-graph validation fails.
    """

    provider_id = str(provider_id).strip()
    get_provider(provider_id)

    task_root = context.project_root / ".agent-work" / task_id
    resolved_change_id = change_id or task_id
    change_root = (
        context.project_root / "changes" / "active" / resolved_change_id
        if entry == "change"
        else None
    )
    task_existed = task_root.exists()
    change_existed = bool(change_root and change_root.exists())

    try:
        root = initialize_legacy_task(
            context,
            task_id=task_id,
            title=title,
            entry=entry,
            question=question,
            signature=signature,
            change_id=change_id,
            change_title=change_title,
        )
        task_path = root / "task.yaml"
        task = load_yaml(task_path)
        current = (task.get("execution") or {}).get(
            "orchestrator_provider",
            DEFAULT_ORCHESTRATOR_PROVIDER,
        )
        if current != DEFAULT_ORCHESTRATOR_PROVIDER:
            raise PivotTransactionError(
                "new Task template no longer has the preserved Codex default"
            )
        task["execution"] = {"orchestrator_provider": provider_id}
        task.setdefault("timeline", []).append(
            {
                "type": "orchestrator-provider-bound",
                "at": now_iso(),
                "provider": provider_id,
            }
        )
        atomic_write_yaml(task_path, task)
        validate_governed_work_graph(context, root)
        return root
    except BaseException:
        if not task_existed and task_root.exists():
            shutil.rmtree(task_root, ignore_errors=True)
        if change_root is not None and not change_existed and change_root.exists():
            shutil.rmtree(change_root, ignore_errors=True)
        raise
