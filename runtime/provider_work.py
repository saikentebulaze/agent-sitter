"""Provider-neutral delegation work commands using model grades."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from delegation_transaction import (
    DelegationTransactionError,
    authorize_delegation,
    request_delegation,
)
from core.task_runtime import orchestrator_provider
from project_context import resolve_project_context
from work_graph import load_yaml, project_relative, resolve_task_root


_GRADE_TO_CODEX_TIER = {
    "low": "luna",
    "medium": "terra",
    "high": "sol",
    "unknown": "unknown",
}


def provider_parent_tier(provider_id: str, grade: str) -> str:
    if grade not in _GRADE_TO_CODEX_TIER:
        raise ValueError(f"invalid parent model grade: {grade}")
    return _GRADE_TO_CODEX_TIER[grade] if provider_id == "codex" else grade


def task_provider(context, task_value: str) -> str:
    task_root = resolve_task_root(context, task_value)
    return orchestrator_provider(load_yaml(task_root / "task.yaml"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provider-neutral Sitter delegation commands"
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    authorize = subparsers.add_parser("authorize-delegation")
    authorize.add_argument("task")
    authorize.add_argument(
        "--decision",
        choices=("required", "optional"),
        required=True,
    )
    authorize.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        choices=("readonly-exploration", "readonly-review"),
        required=True,
    )
    authorize.add_argument("--evidence", required=True)
    authorize.add_argument("--parent-model", required=True)
    authorize.add_argument(
        "--parent-grade",
        choices=("low", "medium", "high", "unknown"),
        default="unknown",
    )

    request = subparsers.add_parser("request-delegation")
    request.add_argument("task")
    request.add_argument("--role", required=True)
    request.add_argument(
        "--target-type",
        choices=("task", "investigation", "change"),
        required=True,
    )
    request.add_argument("--target-ref", required=True)
    request.add_argument("--purpose", required=True)
    request.add_argument("--question", required=True)
    request.add_argument("--decision-supported", required=True)
    request.add_argument("--include", action="append", default=[])
    request.add_argument("--exclude", action="append", default=[])
    request.add_argument("--start-ref", action="append", default=[])
    request.add_argument("--confirmed-fact", action="append", default=[])

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        provider_id = task_provider(context, args.task)
        if args.command == "authorize-delegation":
            authorize_delegation(
                context,
                args.task,
                decision=args.decision,
                scopes=args.scopes,
                evidence=args.evidence,
                parent_model=args.parent_model,
                parent_tier=provider_parent_tier(
                    provider_id,
                    args.parent_grade,
                ),
            )
            print(f"provider: {provider_id}")
            print(f"parent_model_grade: {args.parent_grade}")
            return
        path = request_delegation(
            context,
            args.task,
            role=args.role,
            target_type=args.target_type,
            target_ref=args.target_ref,
            purpose=args.purpose,
            question=args.question,
            decision_supported=args.decision_supported,
            include=args.include,
            exclude=args.exclude,
            start_refs=args.start_ref,
            confirmed_facts=args.confirmed_fact,
        )
        print(project_relative(context, path))
    except (DelegationTransactionError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
