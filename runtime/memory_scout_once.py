from __future__ import annotations

import argparse
import json
from pathlib import Path

from delegate_once import DelegateOnceError, delegate_once
from delegation_transaction import DelegationTransactionError
from memory_context import recall_memory
from project_context import resolve_project_context
from work_graph import load_yaml, project_relative, resolve_task_root


class MemoryScoutError(RuntimeError):
    pass


def _next_recall_path(task_root: Path) -> Path:
    directory = task_root / "memory-recalls"
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = directory / f"recall-{index:03d}.json"
        if not candidate.exists():
            return candidate
        index += 1


def run_memory_scout(
    project: Path,
    task_value: str,
    *,
    query: str,
    limit: int,
) -> dict:
    context = resolve_project_context(project)
    task_root = resolve_task_root(context, task_value)
    task = load_yaml(task_root / "task.yaml")
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise MemoryScoutError("Task has no stable id")

    recall = recall_memory(context, query, limit=limit)
    if not recall["selected"]:
        return {
            "task": task_id,
            "query": query,
            "selected_count": 0,
            "memory_scout_started": False,
            "reason": "deterministic recall found no relevant durable memory",
        }

    recall_path = _next_recall_path(task_root)
    recall_path.write_text(
        json.dumps(recall, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    recall_ref = project_relative(context, recall_path)

    result = delegate_once(
        context,
        task_id,
        role="memory_scout",
        target_type="task",
        target_ref=task_id,
        purpose="recover and compress bounded version-aware historical context",
        question=(
            "Recover only the relevant historical context in the frozen recall packet. "
            "Preserve freshness/conflict labels and do not form new engineering conclusions."
        ),
        decision_supported=(
            "Provide historical leads and fresh context candidates to the parent; "
            "no engineering decision is delegated to the Memory Scout."
        ),
        include=[recall_ref],
        exclude=[],
        start_refs=[recall_ref],
        confirmed_facts=[
            "The recall packet was selected deterministically from Project Knowledge metadata.",
            "fresh means no invalidating Git change was detected, not that the fact was re-verified.",
            "suspect, unknown, and conflicting entries are historical leads only.",
        ],
        outcome="auto",
    )
    return {
        "task": task_id,
        "query": query,
        "selected_count": recall["selected_count"],
        "memory_scout_started": True,
        "recall_ref": recall_ref,
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one low-cost Memory Scout over a deterministic frozen recall packet"
    )
    parser.add_argument("task")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                run_memory_scout(
                    args.project,
                    args.task,
                    query=args.query,
                    limit=args.limit,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    except (ValueError, MemoryScoutError, DelegateOnceError, DelegationTransactionError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
