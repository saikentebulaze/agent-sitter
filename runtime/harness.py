"""Public Sitter Harness CLI with stable V6.2 command discovery."""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

import _harness_v62_impl as _v62
from _harness_v62_impl import *  # noqa: F401,F403
from archive_lifecycle import ArchiveLifecycleError, finalize_archive_cleanup
from change_budget_preflight import (
    ChangeBudgetPreflightError,
    validate_change_budget_preflight,
)
from knowledge_lifecycle import KnowledgeLifecycleError, defer_knowledge
from project_context import resolve_project_context


# Preserve the historical seam used by V6 regression tests and downstream
# callers that replace the base Knowledge mutation while proving the authority
# preflight fails first. The wrapper synchronizes the facade value into the
# implementation module before dispatch, so moving CLI discovery into this thin
# module does not silently break the old monkeypatch contract.
_base_command_promote_knowledge = _v62._base_command_promote_knowledge


def command_promote_knowledge(context, change, reviewed_by, evidence):
    _v62._base_command_promote_knowledge = _base_command_promote_knowledge
    return _v62.command_promote_knowledge(context, change, reviewed_by, evidence)


_V62_HELP = """
V6.2 high-level commands:
  freeze-readiness CHANGE
      Freeze the Candidate Readiness contract before implementation evidence.
  record-readiness CHANGE --criterion ID --result pass|fail ...
      Record snapshot-bound Candidate Readiness evidence.
  finalize-readiness CHANGE
      Require all frozen readiness criteria to pass on the current production snapshot.
  review CHANGE --run [--reviewer maintainer|deep]
      Run, attest, parse, and record the independent Provider-bound reviewer atomically.
  prepare-candidate CHANGE [--retain PATH=REASON] [--preexisting PATH=REASON]
      Finalize readiness/tests, scope-preflight, run independent review, and advance to the human stop.
  user-review CHANGE --decision approved|changes-requested|not-required --evidence TEXT
      Record the human Candidate acceptance decision transactionally.
  record-verification CHANGE --id ID --kind KIND --result pass|partial|fail ...
      Record authoritative final-verification evidence after human acceptance.
  defer-knowledge CHANGE --reason TEXT
      Explicitly defer Knowledge when syncing has no durable Knowledge candidates.
  finalize-archive-cleanup CHANGE --evidence TEXT
      Prove Task experiments and temporary production artifacts are cleared before archive.
  render CHANGE
      Regenerate deterministic Markdown projections from structured evidence.
  advance CHANGE
      Advance exactly one semantically legal lifecycle transition; arbitrary --to jumps are unsupported.

Reference forms:
  CHANGE accepts a Change ID, Change directory, or change.yaml path.
  Task-taking Work/Learning commands accept a Task ID, Task directory, or task.yaml path.

Legacy/manual review commands remain available for historical V5/V6 Changes.
Activated V6.2 Changes should use `review CHANGE --run` or `prepare-candidate CHANGE`.
""".strip()


def _print_combined_help() -> None:
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            _v62._impl.main()
    except SystemExit as error:
        if error.code not in {None, 0}:
            raise
    base = output.getvalue().rstrip()
    if base:
        print(base)
        print()
    print(_V62_HELP)


def _run_defer_knowledge(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Explicitly defer zero-candidate Knowledge")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("defer-knowledge")
    command.add_argument("change")
    command.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    context = resolve_project_context(args.project)
    try:
        status = defer_knowledge(context, args.change, reason=args.reason)
        _v62.render_evidence(context, args.change)
    except (KnowledgeLifecycleError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Knowledge: {status}")


def _run_finalize_archive_cleanup(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Finalize V6.2 archive cleanup")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("finalize-archive-cleanup")
    command.add_argument("change")
    command.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    context = resolve_project_context(args.project)
    try:
        status = finalize_archive_cleanup(context, args.change, evidence=args.evidence)
        _v62.render_evidence(context, args.change)
    except (ArchiveLifecycleError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Archive cleanup: {status}")


def _preflight_direct_atomic_review(argv: list[str]) -> None:
    if "review" not in argv or "--run" not in argv:
        return
    review_index = argv.index("review")
    if review_index + 1 >= len(argv):
        return
    change = argv[review_index + 1]
    project = Path.cwd()
    if "--project" in argv:
        index = argv.index("--project")
        if index + 1 >= len(argv):
            return
        project = Path(argv[index + 1])
    try:
        context = resolve_project_context(project)
        validate_change_budget_preflight(context, change)
    except (ChangeBudgetPreflightError, ValueError) as error:
        raise SystemExit(str(error)) from error


def main() -> None:
    argv = sys.argv[1:]
    if argv in (["--help"], ["-h"]):
        _print_combined_help()
        return
    if "defer-knowledge" in argv:
        _run_defer_knowledge(argv)
        return
    if "finalize-archive-cleanup" in argv:
        _run_finalize_archive_cleanup(argv)
        return
    _preflight_direct_atomic_review(argv)
    if not _v62._run_v62_command(argv):
        _v62._impl.main()


if __name__ == "__main__":
    main()
