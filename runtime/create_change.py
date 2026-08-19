from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from project_context import resolve_project_context
from reference_resolver import ReferenceResolutionError, resolve_task_ref


FILES = [
    "change.yaml",
    "proposal.md",
    "design.md",
    "tasks.md",
    "verification.md",
    "knowledge-sync.md",
    "archive-summary.md",
]
CHANGE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("change_id")
    parser.add_argument("--title", required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()

    if not CHANGE_ID.fullmatch(args.change_id):
        raise SystemExit(
            "change_id must contain only lowercase letters, digits, and hyphens"
        )
    if args.task_id and not CHANGE_ID.fullmatch(args.task_id):
        raise SystemExit(
            "task_id must contain only lowercase letters, digits, and hyphens"
        )
    try:
        context = resolve_project_context(args.project)
        if args.task_id:
            # Review Protocol 2 is Provider-bound through the owning Task. Do
            # not create a Change that claims V6.2 activation but has no real
            # orchestrator binding to resolve later.
            resolve_task_ref(context, args.task_id)
    except (ValueError, ReferenceResolutionError) as error:
        raise SystemExit(str(error)) from error

    assets = context.adapter_root / "skills/change-governor/assets"
    target = (context.project_root / "changes/active" / args.change_id).resolve()
    active_root = (context.project_root / "changes/active").resolve()
    if target.parent != active_root:
        raise SystemExit("change_id resolves outside changes/active")
    if target.exists():
        raise SystemExit(f"change exists: {target}")

    target.mkdir(parents=True)
    for name in FILES:
        src = assets / f"{name}.template"
        text = src.read_text(encoding="utf-8")
        if name == "change.yaml":
            text = text.replace("replace-with-change-id", args.change_id)
            text = text.replace(
                "replace-with-title",
                json.dumps(args.title, ensure_ascii=False),
            )
            task_value = json.dumps(args.task_id) if args.task_id else ""
            text = text.replace(
                "task_id: replace-with-task-id",
                f"task_id: {task_value}",
            )
            if args.task_id:
                text = text.replace(
                    "candidate_readiness_protocol:\n",
                    "candidate_readiness_protocol: 1\n",
                    1,
                )
        (target / name).write_text(text, encoding="utf-8")

    print(target.relative_to(context.project_root))


if __name__ == "__main__":
    main()
