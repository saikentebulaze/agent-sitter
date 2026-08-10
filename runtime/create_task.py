from __future__ import annotations

import argparse
from pathlib import Path

from core.provider_registry import registered_providers
from governed_work import PivotTransactionError
from project_context import resolve_project_context
from provider_task import initialize_provider_task


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Sitter v4 task and its first work item")
    parser.add_argument("task_id")
    parser.add_argument("--title", required=True)
    parser.add_argument("--entry", choices=("investigation", "change"), default="investigation")
    parser.add_argument("--question")
    parser.add_argument("--signature")
    parser.add_argument("--change-id")
    parser.add_argument("--change-title")
    parser.add_argument(
        "--provider",
        choices=registered_providers(),
        default="codex",
        help="immutably bind the Task to one orchestrator runtime provider",
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()

    if args.entry == "investigation" and not args.signature:
        parser.error("--signature is required for an investigation entry")
    if args.entry == "change" and args.question:
        parser.error("--question only applies to an investigation entry")

    try:
        context = resolve_project_context(args.project)
        root = initialize_provider_task(
            context,
            task_id=args.task_id,
            title=args.title,
            entry=args.entry,
            provider_id=args.provider,
            question=args.question,
            signature=args.signature,
            change_id=args.change_id,
            change_title=args.change_title,
        )
    except (ValueError, PivotTransactionError) as error:
        raise SystemExit(str(error)) from error
    print(root.relative_to(context.project_root))


if __name__ == "__main__":
    main()
