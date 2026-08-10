from __future__ import annotations

import argparse
from pathlib import Path

from common import fail
from governed_validation import validate_governed_work_graph
from project_context import resolve_project_context
from work_graph import WorkGraphError, resolve_task_root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        task_root = resolve_task_root(context, args.task)
        validate_governed_work_graph(context, task_root)
    except (ValueError, WorkGraphError) as error:
        fail(str(error))
    print("work_graph: valid")


if __name__ == "__main__":
    main()
