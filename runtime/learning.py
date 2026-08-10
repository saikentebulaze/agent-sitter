from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from project_context import ProjectContext, resolve_project_context


ENTRY_STATUSES = {
    "observed", "watching", "ready-for-review", "approved",
    "promoted", "dismissed", "stale",
}
KINDS = {
    "pitfall", "procedure", "tool-gap", "skill-gap", "policy-gap", "fact",
    "durable-memory",
}
SCOPES = {"project", "user-environment", "harness"}
TARGETS = {
    "ignore", "project-tool", "local-tool", "project-knowledge",
    "open-thread", "watchpoint",
    "environment-config", "skill", "policy", "harness-change",
}
DURABLE_TARGETS = {"project-knowledge", "open-thread", "watchpoint"}
IMMEDIATE_KINDS = {"security", "data-loss", "silent-numerical-error", "false-validation"}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"expected YAML mapping: {path}")
    return data


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def resolve_task(context: ProjectContext, value: str) -> Path:
    raw = Path(value)
    path = raw.resolve() if raw.is_absolute() else (context.project_root / raw).resolve()
    try:
        path.relative_to(context.project_root)
    except ValueError:
        fail(f"task is outside project: {path}")
    if not path.is_file():
        fail(f"task file not found: {path}")
    return path


def project_relative(context: ProjectContext, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.project_root).as_posix()
    except ValueError:
        fail(f"path is outside project: {path}")


def inbox_path(context: ProjectContext) -> Path:
    return context.project_root / ".agent-work" / "_learning" / "inbox.yaml"


def reviews_dir(context: ProjectContext) -> Path:
    return context.project_root / ".agent-work" / "_learning" / "reviews"


def load_store(context: ProjectContext) -> dict:
    path = inbox_path(context)
    if not path.exists():
        return {"version": 1, "entries": []}
    data = load_yaml(path)
    if data.get("version") != 1 or not isinstance(data.get("entries"), list):
        fail("learning inbox has an unsupported structure")
    for index, entry in enumerate(data["entries"]):
        if not isinstance(entry, dict):
            fail(f"learning inbox entry {index} must be a mapping")
        if str(entry.get("status")) not in ENTRY_STATUSES:
            fail(f"learning inbox entry {index} has invalid status")
    return data


def save_store(context: ProjectContext, data: dict) -> None:
    write_yaml(inbox_path(context), data)


def normalized_key(value: str) -> str:
    text = value.strip().lower().replace("\\", "/")
    text = re.sub(r"[a-z]:/(?:[^\s]+/)+", "<path>/", text)
    text = re.sub(r"/tmp/[^\s]+", "<tmp>", text)
    text = re.sub(r"\s+", " ", text)
    if not text:
        fail("learning signature key cannot be empty")
    return text


def entry_id(signature_key: str) -> str:
    digest = hashlib.sha256(signature_key.encode("utf-8")).hexdigest()[:12]
    return f"learn-{digest}"


def task_id(task: dict, task_path: Path) -> str:
    value = task.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return task_path.parent.name or task_path.stem


def append_unique(values: list, value: object) -> None:
    if value not in values:
        values.append(value)


def entry_search_text(entry: dict) -> str:
    fields = [
        entry.get("id"), entry.get("title"), entry.get("kind"), entry.get("scope"),
        (entry.get("signature") or {}).get("key"),
        (entry.get("signature") or {}).get("category"),
        (entry.get("current_workaround") or {}).get("summary"),
        (entry.get("candidate") or {}).get("recommended_target"),
        ((entry.get("candidate") or {}).get("durable") or {}).get("memory_key"),
    ]
    return " ".join(str(value).lower() for value in fields if value)


def rank_entries(entries: list[dict], keywords: list[str], limit: int) -> list[dict]:
    normalized = [item.lower().strip() for item in keywords if item.strip()]
    ranked: list[tuple[int, str, dict]] = []
    for entry in entries:
        if entry.get("status") in {"dismissed", "stale"}:
            continue
        text = entry_search_text(entry)
        score = sum(3 if keyword in text else 0 for keyword in normalized)
        if entry.get("status") in {"approved", "promoted"}:
            score += 2
        if not normalized:
            score += 1
        if score:
            ranked.append((score, str(entry.get("last_seen", "")), entry))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _, _, entry in ranked[:limit]]


def command_intake(
    context: ProjectContext,
    task_path: Path,
    keywords: list[str],
    limit: int,
) -> None:
    task = load_yaml(task_path)
    store = load_store(context)
    derived = [
        str(task.get("title", "")),
        str(task.get("mode", "")),
        platform.system(),
        os.environ.get("COMSPEC", ""),
        os.environ.get("SHELL", ""),
    ]
    relevant = rank_entries(store["entries"], [*keywords, *derived], limit)
    relevant_ids = [str(entry["id"]) for entry in relevant]
    tools = []
    for entry in relevant:
        promoted = entry.get("promoted_asset") or {}
        if entry.get("status") == "promoted" and promoted.get("path"):
            append_unique(tools, promoted["path"])

    learning = task.setdefault("learning", {})
    learning["intake"] = {
        "status": "completed",
        "checked_at": now_iso(),
        "relevant_entries": relevant_ids,
        "recommended_tools": tools,
        "evidence": project_relative(context, inbox_path(context)),
    }
    learning.setdefault("observations", [])
    learning.setdefault("closeout", {
        "status": "pending",
        "observations_added": 0,
        "existing_entries_updated": 0,
        "candidates_ready_for_review": [],
        "reason": None,
    })
    learning.setdefault("user_attention", {
        "required": False,
        "presented": False,
        "decision": "not-required",
        "evidence": None,
        "candidate_decisions": {},
    })
    write_yaml(task_path, task)
    print(json.dumps({
        "task": task_id(task, task_path),
        "relevant_entries": relevant_ids,
        "recommended_tools": tools,
    }, ensure_ascii=False, indent=2))


def command_observe(
    context: ProjectContext,
    task_path: Path,
    *,
    key: str,
    title: str,
    kind: str,
    scope: str,
    category: str,
    evidence: list[str],
    workaround: str | None,
    candidate_target: str,
    verified_success: bool,
    verified_failure: bool,
    immediate: bool,
) -> None:
    if kind not in KINDS:
        fail(f"invalid learning kind: {kind}")
    if scope not in SCOPES:
        fail(f"invalid learning scope: {scope}")
    if candidate_target not in TARGETS:
        fail(f"invalid candidate target: {candidate_target}")

    task = load_yaml(task_path)
    current_task_id = task_id(task, task_path)
    signature_key = normalized_key(key)
    store = load_store(context)
    existing = next(
        (entry for entry in store["entries"] if (entry.get("signature") or {}).get("key") == signature_key),
        None,
    )
    created = existing is None
    timestamp = now_iso()

    if existing is None:
        existing = {
            "id": entry_id(signature_key),
            "title": title,
            "kind": kind,
            "scope": scope,
            "status": "observed",
            "signature": {
                "key": signature_key,
                "category": category,
                "platform": platform.system().lower(),
            },
            "first_seen": timestamp,
            "last_seen": timestamp,
            "occurrences": 0,
            "task_refs": [],
            "evidence_refs": [],
            "current_workaround": {
                "summary": workaround,
                "verified_successes": 0,
                "verified_failures": 0,
            },
            "candidate": {
                "recommended_target": candidate_target,
                "readiness": "not-ready",
            },
            "review": {"decision": None, "reason": None, "evidence": None},
        }
        store["entries"].append(existing)

    existing["title"] = title
    existing["kind"] = kind
    existing["scope"] = scope
    existing["last_seen"] = timestamp
    existing["occurrences"] = int(existing.get("occurrences", 0)) + 1
    existing.setdefault("task_refs", [])
    existing.setdefault("evidence_refs", [])
    append_unique(existing["task_refs"], current_task_id)
    for value in evidence:
        append_unique(existing["evidence_refs"], value)

    workaround_data = existing.setdefault("current_workaround", {})
    if workaround:
        workaround_data["summary"] = workaround
    workaround_data["verified_successes"] = int(workaround_data.get("verified_successes", 0))
    workaround_data["verified_failures"] = int(workaround_data.get("verified_failures", 0))
    if verified_success:
        workaround_data["verified_successes"] += 1
    if verified_failure:
        workaround_data["verified_failures"] += 1

    candidate = existing.setdefault("candidate", {})
    candidate["recommended_target"] = candidate_target
    cross_task = len(existing["task_refs"]) >= 2
    repeated = int(existing["occurrences"]) >= 3 and cross_task
    deterministic_tool = (
        candidate_target in {"project-tool", "local-tool"}
        and workaround_data["verified_successes"] >= 2
        and cross_task
    )
    if immediate or category in IMMEDIATE_KINDS or repeated or deterministic_tool:
        existing["status"] = "ready-for-review"
        candidate["readiness"] = "ready-for-review"
    elif existing.get("status") not in {"approved", "promoted"}:
        existing["status"] = "watching"
        candidate["readiness"] = "watching"

    learning = task.setdefault("learning", {})
    observations = learning.setdefault("observations", [])
    append_unique(observations, existing["id"])
    write_yaml(task_path, task)
    save_store(context, store)
    print(json.dumps({
        "id": existing["id"],
        "created": created,
        "occurrences": existing["occurrences"],
        "tasks": len(existing["task_refs"]),
        "status": existing["status"],
    }, ensure_ascii=False, indent=2))


def _head_commit(context: ProjectContext) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=context.project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def command_propose_durable(
    context: ProjectContext,
    task_path: Path,
    *,
    key: str,
    title: str,
    target: str,
    summary: str,
    memory_key: str,
    evidence: list[str],
    validity_surface: list[str],
    trigger_terms: list[str],
    trigger_condition: str | None,
) -> None:
    if target not in DURABLE_TARGETS:
        fail(f"invalid durable target: {target}")
    if not summary.strip() or not memory_key.strip():
        fail("durable candidate requires summary and memory-key")
    if target in {"open-thread", "watchpoint"} and not (
        trigger_terms or (trigger_condition and trigger_condition.strip())
    ):
        fail(f"{target} requires a trigger term or trigger condition")

    task = load_yaml(task_path)
    current_task_id = task_id(task, task_path)
    signature_key = normalized_key(key)
    store = load_store(context)
    existing = next(
        (entry for entry in store["entries"] if (entry.get("signature") or {}).get("key") == signature_key),
        None,
    )
    if existing is not None and existing.get("status") not in {"dismissed", "stale"}:
        fail(f"durable candidate already exists for key: {signature_key}")

    timestamp = now_iso()
    durable = {
        "summary": summary.strip(),
        "memory_key": memory_key.strip(),
        "validity_surface": list(dict.fromkeys(validity_surface)),
        "trigger_terms": list(dict.fromkeys(trigger_terms)),
        "trigger_condition": trigger_condition.strip() if trigger_condition and trigger_condition.strip() else None,
        "source_commit": _head_commit(context) if validity_surface else None,
    }
    entry = {
        "id": entry_id(signature_key),
        "title": title,
        "kind": "durable-memory",
        "scope": "project",
        "status": "ready-for-review",
        "signature": {
            "key": signature_key,
            "category": "durable-memory",
            "platform": platform.system().lower(),
        },
        "first_seen": timestamp,
        "last_seen": timestamp,
        "occurrences": 1,
        "task_refs": [current_task_id],
        "evidence_refs": list(dict.fromkeys(evidence)),
        "current_workaround": {
            "summary": None,
            "verified_successes": 0,
            "verified_failures": 0,
        },
        "candidate": {
            "recommended_target": target,
            "readiness": "ready-for-review",
            "durable": durable,
        },
        "review": {"decision": None, "reason": None, "evidence": None},
    }
    if existing is None:
        store["entries"].append(entry)
    else:
        existing.clear()
        existing.update(entry)

    learning = task.setdefault("learning", {})
    observations = learning.setdefault("observations", [])
    append_unique(observations, entry["id"])
    write_yaml(task_path, task)
    save_store(context, store)
    print(json.dumps({
        "id": entry["id"],
        "target": target,
        "status": "ready-for-review",
        "source_commit": durable["source_commit"],
    }, ensure_ascii=False, indent=2))


def command_closeout(context: ProjectContext, task_path: Path, reason: str | None) -> None:
    task = load_yaml(task_path)
    store = load_store(context)
    current_task_id = task_id(task, task_path)
    learning = task.setdefault("learning", {})
    observation_ids = set(learning.get("observations") or [])
    related = [
        entry for entry in store["entries"]
        if entry.get("id") in observation_ids or current_task_id in (entry.get("task_refs") or [])
    ]
    ready = [entry["id"] for entry in related if entry.get("status") == "ready-for-review"]
    new_count = sum(
        1 for entry in related
        if (entry.get("task_refs") or [None])[0] == current_task_id
        and len(entry.get("task_refs") or []) == 1
    )
    updated_count = max(0, len(related) - new_count)

    if not related and not (isinstance(reason, str) and reason.strip()):
        fail("closeout with no observations requires --reason")

    learning["closeout"] = {
        "status": "assessed",
        "assessed_at": now_iso(),
        "observations_added": new_count,
        "existing_entries_updated": updated_count,
        "candidates_ready_for_review": ready,
        "reason": reason.strip() if isinstance(reason, str) and reason.strip() else None,
    }
    if ready:
        learning["user_attention"] = {
            "required": True,
            "presented": False,
            "decision": "pending",
            "evidence": None,
            "candidate_decisions": {},
        }
    else:
        learning["user_attention"] = {
            "required": False,
            "presented": True,
            "decision": "not-required",
            "evidence": "no mature learning candidate at closeout; Task history remains cold archive",
            "candidate_decisions": {},
        }
    write_yaml(task_path, task)
    print(json.dumps({
        "task": current_task_id,
        "observations_added": new_count,
        "existing_entries_updated": updated_count,
        "candidates_ready_for_review": ready,
        "user_attention_required": bool(ready),
        "cold_archive": not bool(ready),
    }, ensure_ascii=False, indent=2))


def command_attention(
    context: ProjectContext,
    task_path: Path,
    decision: str,
    evidence: str,
    candidate_id: str | None,
) -> None:
    if decision not in {"approved", "deferred", "dismissed"}:
        fail("attention decision must be approved, deferred, or dismissed")
    if not evidence.strip():
        fail("attention evidence cannot be empty")
    task = load_yaml(task_path)
    learning = task.get("learning") or {}
    closeout = learning.get("closeout") or {}
    candidates = [str(value) for value in closeout.get("candidates_ready_for_review") or []]
    if not candidates:
        fail("task has no mature learning candidates")
    if candidate_id is None:
        if len(candidates) != 1:
            fail("multiple learning candidates require --candidate for individual curation")
        candidate_id = candidates[0]
    if candidate_id not in candidates:
        fail(f"candidate is not part of this Task closeout: {candidate_id}")

    store = load_store(context)
    entries = {str(entry.get("id")): entry for entry in store["entries"]}
    entry = entries.get(candidate_id)
    if entry is None:
        fail(f"learning candidate is missing from inbox: {candidate_id}")
    review = entry.setdefault("review", {})
    review.update({"decision": decision, "evidence": evidence, "reviewed_at": now_iso()})
    if decision == "approved":
        entry["status"] = "approved"
    elif decision == "dismissed":
        entry["status"] = "dismissed"
    else:
        entry["status"] = "watching"
        entry["candidate"]["readiness"] = "deferred"

    attention = learning.setdefault("user_attention", {})
    per_candidate = attention.setdefault("candidate_decisions", {})
    per_candidate[candidate_id] = {
        "decision": decision,
        "evidence": evidence,
        "reviewed_at": now_iso(),
    }
    remaining = [value for value in candidates if value not in per_candidate]
    if remaining:
        attention.update({
            "required": True,
            "presented": True,
            "decision": "pending",
            "evidence": f"candidate {candidate_id} curated; remaining: {', '.join(remaining)}",
        })
    else:
        distinct = {str(value.get("decision")) for value in per_candidate.values()}
        attention.update({
            "required": True,
            "presented": True,
            "decision": next(iter(distinct)) if len(distinct) == 1 else "resolved",
            "evidence": "all mature learning candidates received individual user decisions",
        })
    write_yaml(task_path, task)
    save_store(context, store)
    print(json.dumps({
        "candidate": candidate_id,
        "decision": decision,
        "remaining": remaining,
    }, ensure_ascii=False, indent=2))


def command_status(context: ProjectContext) -> None:
    store = load_store(context)
    counts: dict[str, int] = {}
    for entry in store["entries"]:
        status = str(entry.get("status"))
        counts[status] = counts.get(status, 0) + 1
    ready = [
        {
            "id": entry.get("id"),
            "title": entry.get("title"),
            "scope": entry.get("scope"),
            "target": (entry.get("candidate") or {}).get("recommended_target"),
            "occurrences": entry.get("occurrences"),
            "tasks": len(entry.get("task_refs") or []),
        }
        for entry in store["entries"]
        if entry.get("status") == "ready-for-review"
    ]
    print(json.dumps({
        "inbox": project_relative(context, inbox_path(context)),
        "counts": counts,
        "ready_for_review": ready,
    }, ensure_ascii=False, indent=2))


def command_review(context: ProjectContext, candidate_id: str) -> None:
    store = load_store(context)
    entry = next((item for item in store["entries"] if item.get("id") == candidate_id), None)
    if entry is None:
        fail(f"learning candidate not found: {candidate_id}")
    if entry.get("status") not in {"ready-for-review", "approved"}:
        fail(f"learning candidate is not ready for review: {entry.get('status')}")

    target = (entry.get("candidate") or {}).get("recommended_target")
    packet = {
        "candidate_id": candidate_id,
        "generated_at": now_iso(),
        "title": entry.get("title"),
        "scope": entry.get("scope"),
        "kind": entry.get("kind"),
        "occurrences": entry.get("occurrences"),
        "affected_tasks": entry.get("task_refs") or [],
        "evidence_refs": entry.get("evidence_refs") or [],
        "root_cause_status": "confirm-before-promotion",
        "recommended_target": target,
        "durable": (entry.get("candidate") or {}).get("durable"),
        "why_program_first": target in {"project-tool", "local-tool"},
        "current_workaround": entry.get("current_workaround") or {},
        "promotion_rule": (
            "This packet may be presented automatically, but creating or modifying a tool, "
            "Skill, Project Knowledge, Open Thread, Watchpoint, policy, user-level configuration, "
            "or Harness code requires explicit user approval and the existing governed promotion path."
        ),
    }
    output = reviews_dir(context) / f"{candidate_id}.yaml"
    write_yaml(output, packet)
    print(project_relative(context, output))


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def command_gc(context: ProjectContext, stale_days: int) -> None:
    if stale_days < 1:
        fail("stale-days must be positive")
    store = load_store(context)
    threshold = datetime.now(timezone.utc) - timedelta(days=stale_days)
    changed = 0
    for entry in store["entries"]:
        if entry.get("status") not in {"observed", "watching"}:
            continue
        last_seen = parse_time(entry.get("last_seen"))
        if last_seen is not None and last_seen < threshold:
            entry["status"] = "stale"
            changed += 1
    save_store(context, store)
    print(json.dumps({"marked_stale": changed, "deleted": 0}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sitter evidence-gated learning inbox")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake = subparsers.add_parser("intake")
    intake.add_argument("task")
    intake.add_argument("--keyword", action="append", default=[])
    intake.add_argument("--limit", type=int, default=5)

    observe = subparsers.add_parser("observe")
    observe.add_argument("task")
    observe.add_argument("--key", required=True)
    observe.add_argument("--title", required=True)
    observe.add_argument("--kind", choices=sorted(KINDS), required=True)
    observe.add_argument("--scope", choices=sorted(SCOPES), required=True)
    observe.add_argument("--category", required=True)
    observe.add_argument("--evidence", action="append", default=[])
    observe.add_argument("--workaround")
    observe.add_argument("--candidate-target", choices=sorted(TARGETS), default="ignore")
    observe.add_argument("--verified-success", action="store_true")
    observe.add_argument("--verified-failure", action="store_true")
    observe.add_argument("--immediate", action="store_true")

    durable = subparsers.add_parser("propose-durable")
    durable.add_argument("task")
    durable.add_argument("--key", required=True)
    durable.add_argument("--title", required=True)
    durable.add_argument("--target", choices=sorted(DURABLE_TARGETS), required=True)
    durable.add_argument("--summary", required=True)
    durable.add_argument("--memory-key", required=True)
    durable.add_argument("--evidence", action="append", default=[])
    durable.add_argument("--validity-surface", action="append", default=[])
    durable.add_argument("--trigger-term", action="append", default=[])
    durable.add_argument("--trigger-condition")

    closeout = subparsers.add_parser("closeout")
    closeout.add_argument("task")
    closeout.add_argument("--reason")

    attention = subparsers.add_parser("attention")
    attention.add_argument("task")
    attention.add_argument("--candidate")
    attention.add_argument(
        "--decision", choices=["approved", "deferred", "dismissed"], required=True
    )
    attention.add_argument("--evidence", required=True)

    subparsers.add_parser("status")

    review = subparsers.add_parser("review")
    review.add_argument("candidate_id")

    gc = subparsers.add_parser("gc")
    gc.add_argument("--stale-days", type=int, default=90)

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        fail(str(error))

    if args.command == "status":
        command_status(context)
        return
    if args.command == "review":
        command_review(context, args.candidate_id)
        return
    if args.command == "gc":
        command_gc(context, args.stale_days)
        return

    task_path = resolve_task(context, args.task)
    if args.command == "intake":
        command_intake(context, task_path, args.keyword, args.limit)
    elif args.command == "observe":
        command_observe(
            context,
            task_path,
            key=args.key,
            title=args.title,
            kind=args.kind,
            scope=args.scope,
            category=args.category,
            evidence=args.evidence,
            workaround=args.workaround,
            candidate_target=args.candidate_target,
            verified_success=args.verified_success,
            verified_failure=args.verified_failure,
            immediate=args.immediate,
        )
    elif args.command == "propose-durable":
        command_propose_durable(
            context,
            task_path,
            key=args.key,
            title=args.title,
            target=args.target,
            summary=args.summary,
            memory_key=args.memory_key,
            evidence=args.evidence,
            validity_surface=args.validity_surface,
            trigger_terms=args.trigger_term,
            trigger_condition=args.trigger_condition,
        )
    elif args.command == "closeout":
        command_closeout(context, task_path, args.reason)
    elif args.command == "attention":
        command_attention(
            context,
            task_path,
            args.decision,
            args.evidence,
            args.candidate,
        )


if __name__ == "__main__":
    main()
