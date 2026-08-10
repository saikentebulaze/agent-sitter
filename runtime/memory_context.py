from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from common import fail, load_json_or_yaml_like
from knowledge_tool import validate_entries
from project_context import ProjectContext, resolve_project_context


FRESHNESS = {"fresh", "suspect", "unknown"}
TRIGGERED_TYPES = {"open-thread", "watchpoint"}


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def _normalize_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _matches_surface(path: str, surface: str) -> bool:
    path_key = _normalize_path(path)
    surface_key = _normalize_path(surface)
    if not path_key or not surface_key:
        return False
    return path_key == surface_key or path_key.startswith(surface_key + "/")


def _changed_paths(project_root: Path, source_commit: str) -> set[str] | None:
    result = _git(project_root, "diff", "--name-only", f"{source_commit}..HEAD", "--")
    if result.returncode != 0:
        return None
    return {
        _normalize_path(line)
        for line in result.stdout.splitlines()
        if _normalize_path(line)
    }


def _working_paths(project_root: Path) -> set[str] | None:
    result = _git(project_root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        return None
    paths: set[str] = set()
    for raw in result.stdout.splitlines():
        if len(raw) < 4:
            continue
        value = raw[3:].strip()
        if " -> " in value:
            before, after = value.split(" -> ", 1)
            for candidate in (before, after):
                normalized = _normalize_path(candidate.strip('"'))
                if normalized:
                    paths.add(normalized)
        else:
            normalized = _normalize_path(value.strip('"'))
            if normalized:
                paths.add(normalized)
    return paths


def memory_freshness(context: ProjectContext, entry: dict) -> dict:
    """Lazily classify one code-bound memory as fresh/suspect/unknown.

    `fresh` means no invalidating repository evolution was detected. It never
    means the historical statement was re-verified against current code.
    """

    source_commit = str(entry.get("source_commit") or "").strip()
    surfaces = entry.get("validity_surface")
    if not source_commit or not isinstance(surfaces, list) or not surfaces:
        return {
            "status": "unknown",
            "reason": "memory has no complete code-bound provenance",
            "usable_as_current_fact": False,
        }

    ancestor = _git(
        context.project_root,
        "merge-base",
        "--is-ancestor",
        source_commit,
        "HEAD",
    )
    if ancestor.returncode != 0:
        return {
            "status": "unknown",
            "reason": "source commit is not an ancestor of HEAD",
            "usable_as_current_fact": False,
        }

    committed = _changed_paths(context.project_root, source_commit)
    working = _working_paths(context.project_root)
    if committed is None or working is None:
        return {
            "status": "unknown",
            "reason": "Git freshness check could not be completed",
            "usable_as_current_fact": False,
        }

    normalized_surfaces = [
        _normalize_path(str(value))
        for value in surfaces
        if isinstance(value, str) and _normalize_path(value)
    ]
    committed_hits = sorted(
        path
        for path in committed
        if any(_matches_surface(path, surface) for surface in normalized_surfaces)
    )
    working_hits = sorted(
        path
        for path in working
        if any(_matches_surface(path, surface) for surface in normalized_surfaces)
    )
    if committed_hits or working_hits:
        return {
            "status": "suspect",
            "reason": "validity surface changed after the memory source commit",
            "committed_hits": committed_hits,
            "working_tree_hits": working_hits,
            "usable_as_current_fact": False,
        }
    return {
        "status": "fresh",
        "reason": "no invalidating change detected on the declared validity surface",
        "committed_hits": [],
        "working_tree_hits": [],
        "usable_as_current_fact": True,
        "note": "fresh is a negative freshness check, not re-verification",
    }


def _load_index(context: ProjectContext) -> list[dict]:
    index = context.project_root / "knowledge" / "index.yaml"
    if not index.exists():
        return []
    data = load_json_or_yaml_like(index)
    if data.get("version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("knowledge index has an unsupported structure")
    values = data["entries"]
    errors = validate_entries(context.project_root, values)
    if errors:
        raise ValueError("knowledge index is invalid: " + "; ".join(errors))
    return values


def _query_terms(query: str) -> list[str]:
    values = re.findall(r"[\w./:+-]+", query.lower(), flags=re.UNICODE)
    return list(dict.fromkeys(value for value in values if len(value) >= 2))


def _field_values(entry: dict) -> list[str]:
    return [
        str(entry.get("id") or ""),
        str(entry.get("title") or ""),
        str(entry.get("type") or ""),
        str(entry.get("memory_key") or ""),
        str(entry.get("trigger_condition") or ""),
        *map(str, entry.get("domains") or []),
        *map(str, entry.get("keywords") or []),
        *map(str, entry.get("trigger_terms") or []),
    ]


def _triggered(entry: dict, terms: list[str]) -> bool:
    if entry.get("type") not in TRIGGERED_TYPES:
        return True
    trigger_blob = " ".join(
        [
            str(entry.get("trigger_condition") or ""),
            *map(str, entry.get("trigger_terms") or []),
        ]
    ).lower()
    return bool(terms) and any(term in trigger_blob for term in terms)


def _score(entry: dict, terms: list[str]) -> int:
    if not terms or not _triggered(entry, terms):
        return 0
    fields = _field_values(entry)
    score = 0
    for term in terms:
        for index, value in enumerate(fields):
            if term in value.lower():
                score += 6 if index < 4 else 3
    if entry.get("evidence_status") == "verified":
        score += 2
    if entry.get("architecture_status") == "current":
        score += 1
    return score


def _superseded_ids(values: list[dict]) -> set[str]:
    return {
        str(target)
        for entry in values
        for target in (entry.get("supersedes") or [])
        if isinstance(target, str)
    }


def memory_conflicts(values: list[dict]) -> list[dict]:
    superseded = _superseded_ids(values)
    groups: dict[str, list[str]] = {}
    for entry in values:
        entry_id = str(entry.get("id") or "")
        key = str(entry.get("memory_key") or "").strip()
        if not entry_id or not key or entry_id in superseded:
            continue
        groups.setdefault(key, []).append(entry_id)
    return [
        {"memory_key": key, "entry_ids": sorted(ids), "status": "conflict"}
        for key, ids in sorted(groups.items())
        if len(ids) > 1
    ]


def recall_memory(
    context: ProjectContext,
    query: str,
    *,
    limit: int = 3,
) -> dict:
    if limit < 1 or limit > 10:
        raise ValueError("memory recall limit must be between 1 and 10")
    values = _load_index(context)
    terms = _query_terms(query)
    superseded = _superseded_ids(values)
    conflicts = memory_conflicts(values)
    conflict_ids = {
        entry_id for conflict in conflicts for entry_id in conflict["entry_ids"]
    }

    ranked: list[tuple[int, str, dict]] = []
    for entry in values:
        entry_id = str(entry.get("id") or "")
        if entry_id in superseded:
            continue
        score = _score(entry, terms)
        if score:
            ranked.append((score, entry_id, entry))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    selected: list[dict] = []
    for score, entry_id, entry in ranked[:limit]:
        freshness = memory_freshness(context, entry)
        path = context.project_root / str(entry["path"])
        selected.append(
            {
                "id": entry_id,
                "title": entry.get("title"),
                "type": entry.get("type"),
                "memory_key": entry.get("memory_key"),
                "score": score,
                "freshness": freshness,
                "conflict": entry_id in conflict_ids,
                "usage": (
                    "historical-lead"
                    if entry_id in conflict_ids or freshness["status"] != "fresh"
                    else "current-context-candidate"
                ),
                "content": path.read_text(encoding="utf-8"),
            }
        )

    return {
        "schema_version": 1,
        "query_terms": terms,
        "selected": selected,
        "selected_count": len(selected),
        "conflicts": conflicts,
        "index_entries_considered": len(values),
        "history_tasks_scanned": 0,
        "rule": (
            "suspect, unknown, or conflicting memory is historical lead only; "
            "current code or new evidence must re-establish the fact"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Structured V6 Project Knowledge recall and lazy freshness checking"
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    recall = subparsers.add_parser("recall")
    recall.add_argument("query")
    recall.add_argument("--limit", type=int, default=3)

    fresh = subparsers.add_parser("freshness")
    fresh.add_argument("entry_id")

    subparsers.add_parser("conflicts")

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        values = _load_index(context)
        if args.command == "recall":
            payload = recall_memory(context, args.query, limit=args.limit)
        elif args.command == "conflicts":
            payload = {"conflicts": memory_conflicts(values)}
        else:
            entry = next(
                (item for item in values if str(item.get("id") or "") == args.entry_id),
                None,
            )
            if entry is None:
                raise ValueError(f"unknown memory entry: {args.entry_id}")
            payload = {
                "id": args.entry_id,
                "freshness": memory_freshness(context, entry),
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except ValueError as error:
        fail(str(error))


if __name__ == "__main__":
    main()
