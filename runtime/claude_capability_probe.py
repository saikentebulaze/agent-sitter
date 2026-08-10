"""CLI for real Claude Code managed capability probes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from project_context import resolve_project_context
from providers.claude.capability_probe import (
    load_current_report,
    probe_managed,
    write_report,
)
from providers.claude.managed_runtime import ClaudeManagedRuntimeError
from work_graph import project_relative


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run real managed Claude probes for the configured low, medium, "
            "and high model grades"
        )
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument(
        "--show-current",
        action="store_true",
        help="show a cached report only when its runtime and projection fingerprint is current",
    )
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        if args.show_current:
            report = load_current_report(context)
            if report is None:
                raise ValueError(
                    "no current Claude capability report; run the probe again"
                )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        report = probe_managed(context)
        path = write_report(context, report)
        print(project_relative(context, path))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        unsupported = [
            grade
            for grade, result in (report.get("managed") or {}).items()
            if result.get("status") != "supported"
        ]
        if unsupported:
            raise SystemExit(2)
    except (ClaudeManagedRuntimeError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
