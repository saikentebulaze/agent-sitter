from __future__ import annotations

import argparse
import copy
from pathlib import Path

from common import fail, load_json_or_yaml_like
from decision_authority import human_decision_digest, resolved_human_decisions
from knowledge_tool import validate_entries
from learning import inbox_path, load_store
from project_context import ProjectContext, resolve_project_context
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import load_yaml, now_iso


TARGET_TO_TYPE = {
    "project-knowledge": "fact",
    "open-thread": "open-thread",
    "watchpoint": "watchpoint",
}


class DurableMemoryError(ValueError):
    pass


def _knowledge_index_path(context: ProjectContext) -> Path:
    return context.project_root / "knowledge" / "index.yaml"


def _load_knowledge(context: ProjectContext) -> dict:
    path = _knowledge_index_path(context)
    if not path.exists():
        return {"version": 1, "entries": []}
    data = load_json_or_yaml_like(path)
    if data.get("version") != 1 or not isinstance(data.get("entries"), list):
        raise DurableMemoryError("knowledge index has an unsupported structure")
    errors = validate_entries(context.project_root, data["entries"])
    if errors:
        raise DurableMemoryError("knowledge index is invalid: " + "; ".join(errors))
    return data


def _active_entries(values: list[dict]) -> list[dict]:
    superseded = {
        str(target)
        for entry in values
        for target in (entry.get("supersedes") or [])
        if isinstance(target, str)
    }
    return [entry for entry in values if str(entry.get("id") or "") not in superseded]


def _task_authority(context: ProjectContext, task_id: str | None) -> str | None:
    if not task_id:
        return None
    path = context.project_root / ".agent-work" / task_id / "task.yaml"
    if not path.is_file():
        return None
    task = load_yaml(path)
    if not resolved_human_decisions(task):
        return None
    return human_decision_digest(task)


def _task_authority_digest(context: ProjectContext, task_id: str | None) -> str | None:
    if not task_id:
        return None
    path = context.project_root / ".agent-work" / task_id / "task.yaml"
    if not path.is_file():
        return None
    return human_decision_digest(load_yaml(path))


def _render_markdown(entry: dict, durable: dict, evidence_refs: list[str]) -> str:
    lines = [
        f"# {entry['title']}",
        "",
        str(durable["summary"]).strip(),
        "",
        "## Durable context",
        "",
        f"- Type: `{entry['type']}`",
        f"- Memory key: `{entry['memory_key']}`",
    ]
    if entry.get("source_task"):
        lines.append(f"- Source Task: `{entry['source_task']}`")
    if entry.get("source_commit"):
        lines.append(f"- Source commit: `{entry['source_commit']}`")
    if entry.get("validity_surface"):
        lines.append("- Validity surface: " + ", ".join(f"`{value}`" for value in entry["validity_surface"]))
    if entry.get("trigger_condition"):
        lines.append(f"- Trigger condition: {entry['trigger_condition']}")
    if entry.get("trigger_terms"):
        lines.append("- Trigger terms: " + ", ".join(f"`{value}`" for value in entry["trigger_terms"]))
    if entry.get("supersedes"):
        lines.append("- Explicitly supersedes: " + ", ".join(f"`{value}`" for value in entry["supersedes"]))
    if evidence_refs:
        lines.extend(["", "## Evidence refs", ""])
        lines.extend(f"- `{value}`" for value in evidence_refs)
    lines.extend(
        [
            "",
            "This durable entry is intentionally semantic and compact. Current code and new evidence remain authoritative when historical memory is suspect or unknown.",
            "",
        ]
    )
    return "\n".join(lines)


def promote_candidate(
    context: ProjectContext,
    candidate_id: str,
    *,
    supersede: list[str],
) -> dict:
    store = load_store(context)
    candidate = next(
        (entry for entry in store["entries"] if str(entry.get("id") or "") == candidate_id),
        None,
    )
    if candidate is None:
        raise DurableMemoryError(f"learning candidate not found: {candidate_id}")
    if candidate.get("status") != "approved":
        raise DurableMemoryError("durable memory promotion requires an individually approved candidate")
    target = str((candidate.get("candidate") or {}).get("recommended_target") or "")
    if target not in TARGET_TO_TYPE:
        raise DurableMemoryError(f"candidate is not durable Project Knowledge: {target}")
    durable = (candidate.get("candidate") or {}).get("durable") or {}
    summary = str(durable.get("summary") or "").strip()
    memory_key = str(durable.get("memory_key") or "").strip()
    if not summary or not memory_key:
        raise DurableMemoryError("durable candidate has no semantic summary or memory_key")

    knowledge = _load_knowledge(context)
    values = knowledge["entries"]
    ids = {str(entry.get("id") or "") for entry in values}
    if candidate_id in ids:
        raise DurableMemoryError(f"knowledge entry already exists: {candidate_id}")

    active_same_key = [
        str(entry.get("id"))
        for entry in _active_entries(values)
        if str(entry.get("memory_key") or "") == memory_key
    ]
    explicit = list(dict.fromkeys(str(value) for value in supersede if str(value)))
    unknown = [value for value in explicit if value not in ids]
    if unknown:
        raise DurableMemoryError("cannot supersede unknown memory: " + ", ".join(unknown))
    wrong_key = [
        value
        for value in explicit
        if str(next(entry for entry in values if str(entry.get("id")) == value).get("memory_key") or "") != memory_key
    ]
    if wrong_key:
        raise DurableMemoryError("supersede targets use another memory_key: " + ", ".join(wrong_key))
    unresolved = [value for value in active_same_key if value not in explicit]
    if unresolved:
        raise DurableMemoryError(
            "durable memory conflict requires explicit user supersession or re-verification: "
            + ", ".join(unresolved)
        )

    source_task = str((candidate.get("task_refs") or [None])[0] or "") or None
    expected_authority = str(durable.get("authority_sha256") or "").strip()
    if not expected_authority:
        raise DurableMemoryError(
            "durable candidate has no human decision authority snapshot; re-propose it"
        )
    current_authority = _task_authority_digest(context, source_task)
    if current_authority is None:
        raise DurableMemoryError("durable candidate source Task is unavailable")
    if expected_authority != current_authority:
        raise DurableMemoryError(
            "durable candidate is stale; authoritative human decisions changed"
        )
    entry_type = TARGET_TO_TYPE[target]
    path = f"knowledge/memory/{candidate_id}.md"
    entry = {
        "id": candidate_id,
        "title": str(candidate.get("title") or candidate_id),
        "type": entry_type,
        "evidence_status": "verified",
        "architecture_status": "current",
        "path": path,
        "domains": [str((candidate.get("signature") or {}).get("category") or "durable-memory")],
        "keywords": [memory_key, *map(str, durable.get("trigger_terms") or [])],
        "related": [],
        "reviewed_by": "user",
        "reviewed_at": str((candidate.get("review") or {}).get("reviewed_at") or now_iso()),
        "source_task": source_task,
        "memory_key": memory_key,
        "supersedes": explicit,
    }
    source_commit = durable.get("source_commit")
    validity_surface = durable.get("validity_surface") or []
    if source_commit and validity_surface:
        entry["source_commit"] = str(source_commit)
        entry["validity_surface"] = list(map(str, validity_surface))
    trigger_terms = list(map(str, durable.get("trigger_terms") or []))
    trigger_condition = str(durable.get("trigger_condition") or "").strip()
    if trigger_terms:
        entry["trigger_terms"] = trigger_terms
    if trigger_condition:
        entry["trigger_condition"] = trigger_condition
    authority = _task_authority(context, source_task)
    if authority:
        entry["authority_sha256"] = authority

    proposed = copy.deepcopy(knowledge)
    proposed["entries"].append(entry)
    errors = validate_entries(context.project_root, proposed["entries"], require_paths=False)
    if errors:
        raise DurableMemoryError("promoted memory would violate Knowledge schema: " + "; ".join(errors))

    index_path = _knowledge_index_path(context)
    content_path = context.project_root / path
    inbox = inbox_path(context)
    snapshots = {
        index_path: index_path.read_bytes() if index_path.exists() else None,
        content_path: content_path.read_bytes() if content_path.exists() else None,
        inbox: inbox.read_bytes() if inbox.exists() else None,
    }
    try:
        atomic_write_text(content_path, _render_markdown(entry, durable, list(map(str, candidate.get("evidence_refs") or []))))
        atomic_write_yaml(index_path, proposed)
        candidate["status"] = "promoted"
        candidate["promoted_asset"] = {
            "path": path,
            "knowledge_id": candidate_id,
            "promoted_at": now_iso(),
        }
        atomic_write_yaml(inbox, store)
        final_errors = validate_entries(context.project_root, proposed["entries"])
        if final_errors:
            raise DurableMemoryError("promoted memory failed final validation: " + "; ".join(final_errors))
    except BaseException:
        for path_value, content in snapshots.items():
            if content is None:
                path_value.unlink(missing_ok=True)
            else:
                path_value.parent.mkdir(parents=True, exist_ok=True)
                path_value.write_bytes(content)
        raise

    return {
        "candidate_id": candidate_id,
        "knowledge_id": candidate_id,
        "path": path,
        "type": entry_type,
        "memory_key": memory_key,
        "supersedes": explicit,
        "source_commit": entry.get("source_commit"),
        "authority_sha256": entry.get("authority_sha256"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote individually approved Learning into durable Project Knowledge")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    promote = subparsers.add_parser("promote")
    promote.add_argument("candidate_id")
    promote.add_argument("--supersede", action="append", default=[])
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        result = promote_candidate(context, args.candidate_id, supersede=args.supersede)
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, DurableMemoryError) as error:
        fail(str(error))


if __name__ == "__main__":
    main()
