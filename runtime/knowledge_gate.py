from __future__ import annotations

import sys
from pathlib import Path

import yaml

from knowledge_tool import validate_entries
from project_context import ProjectContext


STRICT_CHANGE_STATUSES = {"syncing", "ready-to-archive", "archived"}
STRICT_KNOWLEDGE_STATUSES = {"candidate", "reviewed", "promoted"}


def validate_project_knowledge_for_change(
    context: ProjectContext,
    change: Path,
) -> None:
    index = context.project_root / "knowledge" / "index.yaml"
    if not index.is_file():
        return

    raw = yaml.safe_load(index.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        errors = ["knowledge/index.yaml must be a mapping"]
    else:
        values = raw.get("entries") or []
        if raw.get("version") != 1:
            errors = ["knowledge index version must be 1"]
        elif not isinstance(values, list):
            errors = ["knowledge index entries must be a list"]
        else:
            errors = validate_entries(context.project_root, values)

    if not errors:
        return

    change_data = yaml.safe_load(
        (change / "change.yaml").read_text(encoding="utf-8")
    )
    change_data = change_data if isinstance(change_data, dict) else {}
    change_status = str(change_data.get("status") or "")
    knowledge_status = str(
        (change_data.get("knowledge_sync") or {}).get("status") or "pending"
    )
    strict = (
        change_status in STRICT_CHANGE_STATUSES
        or knowledge_status in STRICT_KNOWLEDGE_STATUSES
    )
    prefix = "ERROR" if strict else "WARNING"
    stream = sys.stderr if strict else sys.stdout
    for error in errors:
        print(f"{prefix}: knowledge index: {error}", file=stream)
    print(
        f"{prefix}: knowledge index migration is separate from the current "
        "pre-sync Change gate; run knowledge_tool.py diagnose and "
        "migration-plan before knowledge sync or archive",
        file=stream,
    )
    if strict:
        raise SystemExit(1)
