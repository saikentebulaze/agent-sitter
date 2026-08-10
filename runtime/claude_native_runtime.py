"""Strict native Claude runtime CLI for Sitter delegation attempts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delegation_transaction import DelegationTransactionError
from project_context import resolve_project_context
from providers.claude.delegation_runtime import ClaudeDelegationRuntimeError
from providers.claude.delegation_runtime_strict import collect_native_attempt, launch_native_attempt, prepare_native_attempt, record_native_result
from providers.claude.governed_session import ClaudeGovernedSessionError
from providers.claude.native_runtime import ClaudeNativeRuntimeError
from work_graph import project_relative


def main() -> None:
    parser = argparse.ArgumentParser(description="Strict native Claude invocation/Hook/transcript operations")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "launch", "collect"):
        value = subparsers.add_parser(name); value.add_argument("task"); value.add_argument("delegation")
    record = subparsers.add_parser("record"); record.add_argument("task"); record.add_argument("delegation")
    record.add_argument("--outcome", choices=("completed", "need-context", "failed"), required=True)
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        if args.command == "prepare":
            path, contract = prepare_native_attempt(context, args.task, args.delegation)
            print(project_relative(context, path)); print(json.dumps(contract, ensure_ascii=False, indent=2)); return
        if args.command == "launch": raise SystemExit(launch_native_attempt(context, args.task, args.delegation))
        if args.command == "collect":
            for path in collect_native_attempt(context, args.task, args.delegation): print(project_relative(context, path))
            return
        result_path, outcome, repeated = record_native_result(context, args.task, args.delegation, outcome=args.outcome)
        print(project_relative(context, result_path)); print(f"outcome: {outcome}"); print(f"idempotent: {'yes' if repeated else 'no'}")
    except (ClaudeDelegationRuntimeError, ClaudeGovernedSessionError, ClaudeNativeRuntimeError, DelegationTransactionError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr); raise SystemExit(1) from error


if __name__ == "__main__": main()
