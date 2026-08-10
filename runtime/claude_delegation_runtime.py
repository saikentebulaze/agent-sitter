"""Public CLI for attested Claude managed delegation attempts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from delegation_transaction import DelegationTransactionError
from project_context import resolve_project_context
from providers.claude.delegation_runtime import (
    ClaudeDelegationRuntimeError,
    record_isolated_result,
    run_isolated,
)
from providers.claude.managed_runtime import ClaudeManagedRuntimeError
from work_graph import project_relative


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attested Claude managed runtime operations for Sitter delegation"
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run-isolated")
    run_parser.add_argument("task")
    run_parser.add_argument("delegation")

    record_parser = subparsers.add_parser("record-isolated-result")
    record_parser.add_argument("task")
    record_parser.add_argument("delegation")
    record_parser.add_argument(
        "--outcome",
        choices=("completed", "need-context", "failed"),
        required=True,
    )

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        if args.command == "run-isolated":
            for path in run_isolated(context, args.task, args.delegation):
                print(project_relative(context, path))
            return
        result_path, outcome, repeated = record_isolated_result(
            context,
            args.task,
            args.delegation,
            outcome=args.outcome,
        )
        print(project_relative(context, result_path))
        print(f"outcome: {outcome}")
        print(f"idempotent: {'yes' if repeated else 'no'}")
    except (
        ClaudeDelegationRuntimeError,
        ClaudeManagedRuntimeError,
        DelegationTransactionError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
