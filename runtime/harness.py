"""Public Sitter Harness CLI with stable V6.2 command discovery."""

from __future__ import annotations

import contextlib
import io
import sys

import _harness_v62_impl as _v62
from _harness_v62_impl import *  # noqa: F401,F403


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
      Finalize readiness/tests, run independent review, and advance to the human stop.
  user-review CHANGE --decision approved|changes-requested|not-required --evidence TEXT
      Record the human Candidate acceptance decision transactionally.
  record-verification CHANGE --id ID --kind KIND --result pass|partial|fail ...
      Record authoritative final-verification evidence after human acceptance.
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


def main() -> None:
    argv = sys.argv[1:]
    if argv in (["--help"], ["-h"]):
        _print_combined_help()
        return
    if not _v62._run_v62_command(argv):
        _v62._impl.main()


if __name__ == "__main__":
    main()
