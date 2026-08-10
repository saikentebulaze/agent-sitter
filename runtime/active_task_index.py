from __future__ import annotations

from pathlib import Path

from project_context import ProjectContext
from review_transaction import atomic_write_yaml
from work_graph import load_yaml, now_iso


INDEX_VERSION = 1
MAX_ACTIVE_TASKS = 32


def index_path(context: ProjectContext) -> Path:
    return context.project_root / ".agent-work" / "_context" / "active-tasks.yaml"


def load_active_task_index(context: ProjectContext) -> dict:
    path = index_path(context)
    if not path.exists():
        return {"version": INDEX_VERSION, "tasks": []}
    data = load_yaml(path)
    if data.get("version") != INDEX_VERSION or not isinstance(data.get("tasks"), list):
        raise ValueError("active task index has an unsupported structure")
    if len(data["tasks"]) > MAX_ACTIVE_TASKS:
        raise ValueError(
            f"active task index exceeds bounded limit {MAX_ACTIVE_TASKS}; close or consolidate Tasks"
        )
    ids: set[str] = set()
    for index, entry in enumerate(data["tasks"]):
        if not isinstance(entry, dict):
            raise ValueError(f"active task index entry {index} must be a mapping")
        task_id = str(entry.get("id") or "").strip()
        title = str(entry.get("title") or "").strip()
        provider = str(entry.get("provider") or "").strip()
        if not task_id or not title or not provider:
            raise ValueError(f"active task index entry {index} is incomplete")
        if task_id in ids:
            raise ValueError(f"active task index contains duplicate Task: {task_id}")
        ids.add(task_id)
    return data


def _write(context: ProjectContext, data: dict) -> None:
    tasks = data.get("tasks") or []
    if len(tasks) > MAX_ACTIVE_TASKS:
        raise ValueError(
            f"active task index exceeds bounded limit {MAX_ACTIVE_TASKS}; close or consolidate Tasks"
        )
    atomic_write_yaml(index_path(context), data)


def register_active_task(context: ProjectContext, task_root: Path) -> None:
    task = load_yaml(task_root / "task.yaml")
    if str(task.get("status") or "") == "completed":
        raise ValueError("completed Task cannot be registered as active")
    task_id = str(task.get("id") or "").strip()
    title = str(task.get("title") or "").strip()
    provider = str((task.get("execution") or {}).get("orchestrator_provider") or "codex")
    if not task_id or not title:
        raise ValueError("Task requires id and title before active-index registration")

    data = load_active_task_index(context)
    tasks = data["tasks"]
    existing = next((item for item in tasks if item.get("id") == task_id), None)
    entry = {
        "id": task_id,
        "title": title,
        "provider": provider,
        "registered_at": now_iso(),
    }
    if existing is None:
        tasks.append(entry)
    else:
        registered_at = existing.get("registered_at") or entry["registered_at"]
        existing.clear()
        existing.update(entry)
        existing["registered_at"] = registered_at
    _write(context, data)


def unregister_active_task(context: ProjectContext, task_id: str) -> None:
    data = load_active_task_index(context)
    tasks = data["tasks"]
    filtered = [item for item in tasks if str(item.get("id") or "") != task_id]
    if len(filtered) == len(tasks):
        return
    data["tasks"] = filtered
    _write(context, data)


def session_start_payload(context: ProjectContext) -> dict:
    """Read only the bounded Active Task Index; never scan Task history."""

    data = load_active_task_index(context)
    tasks = [
        {
            "id": item["id"],
            "title": item["title"],
            "provider": item["provider"],
        }
        for item in data["tasks"]
    ]
    return {
        "schema_version": 1,
        "active_tasks": tasks,
        "active_task_count": len(tasks),
        "resume_hint": tasks[0]["id"] if len(tasks) == 1 else None,
        "files_read": [index_path(context).relative_to(context.project_root).as_posix()],
        "history_scanned": False,
        "durable_memory_loaded": False,
    }
