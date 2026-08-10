from __future__ import annotations

import argparse
import json
from pathlib import Path

from active_task_index import session_start_payload
from common import fail
from project_context import resolve_project_context


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read bounded V6 session continuity context without scanning history"
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("command", choices=("startup",))
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        print(
            json.dumps(
                session_start_payload(context),
                ensure_ascii=False,
                indent=2,
            )
        )
    except ValueError as error:
        fail(str(error))


if __name__ == "__main__":
    main()
