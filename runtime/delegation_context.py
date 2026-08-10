from __future__ import annotations

from pathlib import Path
from typing import Iterable

from artifact_consistency import file_sha256
from agent_profiles import AgentProfile
from delegation_policy import DelegationPolicy, project_change
from project_context import ProjectContext
from work_graph import (
    investigation_path,
    load_yaml,
    now_iso,
    project_relative,
    resolve_change_root,
)


class DelegationContextError(ValueError):
    pass


def _safe_project_path(context: ProjectContext, value: str | Path, label: str) -> Path:
    raw = Path(value)
    path = raw.resolve() if raw.is_absolute() else (context.project_root / raw).resolve()
    try:
        path.relative_to(context.project_root)
    except ValueError as error:
        raise DelegationContextError(f"{label} is outside project: {value}") from error
    return path


def _ref(
    context: ProjectContext,
    path: Path,
    purpose: str,
    *,
    freeze: bool = True,
) -> dict:
    if not path.is_file():
        raise DelegationContextError(f"authority ref does not exist: {path}")
    return {
        "ref": project_relative(context, path),
        "purpose": purpose,
        "freeze": freeze,
    }


def _dedupe_refs(values: Iterable[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for item in values:
        ref = str(item.get("ref") or "")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        result.append(item)
    return result


def _snapshot(context: ProjectContext, refs: Iterable[dict], extra_paths: Iterable[Path]) -> dict:
    paths: dict[str, Path] = {}
    for item in refs:
        if not bool(item.get("freeze", True)):
            continue
        path = _safe_project_path(context, str(item["ref"]), "authority ref")
        paths[project_relative(context, path)] = path
    for path in extra_paths:
        paths[project_relative(context, path)] = path
    return {key: file_sha256(path) for key, path in sorted(paths.items())}


def verify_snapshot(context: ProjectContext, packet: dict) -> list[str]:
    expected = packet.get("snapshot") or {}
    if not isinstance(expected, dict):
        raise DelegationContextError("delegation snapshot must be a mapping")
    changed: list[str] = []
    for value, digest in expected.items():
        path = _safe_project_path(context, str(value), "snapshot path")
        if not path.is_file() or file_sha256(path) != digest:
            changed.append(str(value))
    return changed


def _target_context(
    context: ProjectContext,
    task_root: Path,
    task: dict,
    policy: DelegationPolicy,
    target_type: str,
    target_ref: str,
) -> tuple[dict, list[dict], list[Path]]:
    authority_refs: list[dict] = []
    snapshot_paths: list[Path] = []

    if target_type == "task":
        if target_ref != str(task["id"]):
            raise DelegationContextError("task target_ref must match the current task id")
        inline = {
            "task": {
                "id": task.get("id"),
                "title": task.get("title"),
                "status": task.get("status"),
                "current_focus": task.get("current_focus"),
                "work_items": task.get("work_items"),
            }
        }
        authority_refs.append(
            _ref(
                context,
                task_root / "task.yaml",
                "authoritative task state",
                freeze=False,
            )
        )
        return inline, authority_refs, snapshot_paths

    if target_type == "investigation":
        inv_path = investigation_path(task_root, target_ref)
        investigation = load_yaml(inv_path)
        if investigation.get("task_id") != task.get("id"):
            raise DelegationContextError("investigation target belongs to another task")
        inline = {
            "investigation": {
                "id": investigation.get("id"),
                "title": investigation.get("title"),
                "status": investigation.get("status"),
                "execution_state": investigation.get("execution_state"),
                "source": investigation.get("source"),
                "problem": investigation.get("problem"),
                "remaining_unknowns": investigation.get("remaining_unknowns"),
                "disposition": investigation.get("disposition"),
            }
        }
        authority_refs.append(_ref(context, inv_path, "authoritative investigation state"))
        markdown = inv_path.with_suffix(".md")
        if markdown.is_file():
            authority_refs.append(_ref(context, markdown, "investigation findings"))
        snapshot_paths.append(inv_path)
        source = investigation.get("source") or {}
        if source.get("type") == "change":
            change_root = resolve_change_root(context, str(source.get("ref")))
            change = load_yaml(change_root / "change.yaml")
            inline["source_change"] = project_change(change, policy)
            for name in policy.authority_files:
                path = change_root / name
                if path.is_file():
                    authority_refs.append(_ref(context, path, f"source Change {name}"))
                    snapshot_paths.append(path)
        return inline, authority_refs, snapshot_paths

    if target_type == "change":
        change_root = resolve_change_root(context, target_ref)
        change_path = change_root / "change.yaml"
        change = load_yaml(change_path)
        if change.get("task_id") != task.get("id"):
            raise DelegationContextError("change target belongs to another task")
        inline = {"change": project_change(change, policy)}
        for name in policy.authority_files:
            path = change_root / name
            if path.is_file():
                authority_refs.append(_ref(context, path, f"authoritative Change {name}"))
                snapshot_paths.append(path)

        relations = change.get("relations") or {}
        related_ids: list[str] = []
        for relation_name in ("derived_from", "produced"):
            relation = relations.get(relation_name) or {}
            related_ids.extend(map(str, relation.get("investigations") or []))
        for investigation_id in dict.fromkeys(related_ids):
            inv_path = investigation_path(task_root, investigation_id)
            if inv_path.is_file():
                authority_refs.append(
                    _ref(context, inv_path, f"related Investigation {investigation_id}")
                )
                snapshot_paths.append(inv_path)
        return inline, authority_refs, snapshot_paths

    raise DelegationContextError(f"unsupported target type: {target_type}")


def build_request_packet(
    context: ProjectContext,
    task_root: Path,
    task: dict,
    *,
    delegation_id: str,
    attempt: int,
    profile: AgentProfile,
    policy: DelegationPolicy,
    target_type: str,
    target_ref: str,
    purpose: str,
    question: str,
    decision_supported: str,
    include: list[str],
    exclude: list[str],
    start_refs: list[str],
    confirmed_facts: list[str],
    supplemental_refs: list[dict] | None = None,
) -> dict:
    if target_type not in policy.allowed_targets:
        allowed = ", ".join(sorted(policy.allowed_targets))
        raise DelegationContextError(
            f"{profile.name} cannot target {target_type}; allowed: {allowed}"
        )
    if not question.strip():
        raise DelegationContextError("delegation question is required")
    if not purpose.strip():
        raise DelegationContextError("delegation purpose is required")
    if not decision_supported.strip():
        raise DelegationContextError("delegation decision_supported is required")
    if not include and not start_refs:
        raise DelegationContextError(
            "delegation needs at least one include scope or start ref"
        )

    inline, authority_refs, snapshot_paths = _target_context(
        context, task_root, task, policy, target_type, target_ref
    )
    start: list[dict] = []
    for value in start_refs:
        path = _safe_project_path(context, value, "start ref")
        if not path.exists():
            raise DelegationContextError(f"start ref does not exist: {value}")
        start.append(
            {"ref": project_relative(context, path), "reason": "explicit start anchor"}
        )

    supplements = list(supplemental_refs or [])
    for item in supplements:
        path = _safe_project_path(context, str(item.get("ref") or ""), "supplement ref")
        if not path.exists():
            raise DelegationContextError(f"supplement ref does not exist: {path}")
        authority_refs.append(
            {
                "ref": project_relative(context, path),
                "purpose": str(item.get("reason") or "context supplement"),
                "freeze": True,
            }
        )
        snapshot_paths.append(path)

    authority_refs = _dedupe_refs(authority_refs)
    packet = {
        "schema_version": 1,
        "delegation": {
            "id": delegation_id,
            "attempt": attempt,
            "task_id": task["id"],
            "role": profile.name,
        },
        "requested_profile": {
            "agent": profile.name,
            "model": profile.model,
            "tier": profile.tier,
            "reasoning_effort": profile.reasoning_effort,
            "sandbox_mode": profile.sandbox_mode,
            "execution": "native-subagent",
        },
        "context_policy": {
            "inheritance": "none",
            "additional_repository_search": "bounded",
            "scope_expansion": "forbidden",
            "max_context_supplements": policy.max_context_supplements,
        },
        "objective": {
            "question": question,
            "decision_supported": decision_supported,
            "purpose": purpose,
        },
        "scope": {"include": include, "exclude": exclude},
        "target": {"type": target_type, "ref": target_ref},
        "projection": {
            "id": policy.projection,
            "inline": inline,
            "authority_refs": authority_refs,
        },
        "start_here": start,
        "confirmed_facts": [
            {"id": f"fact-{index:03d}", "statement": statement}
            for index, statement in enumerate(confirmed_facts, start=1)
        ],
        "bias_control": {
            "parent_hypotheses": "withheld",
            "desired_outcome": "withheld",
            "proposed_patch": "withheld",
        },
        "output_contract": {
            "required_sections": [
                "key conclusions",
                "evidence index",
                "unresolved questions",
            ],
            "forbidden": [
                "production file modifications",
                "unsupported root-cause claims",
            ],
            "need_context_status": "NEED_CONTEXT",
        },
        "context_supplements": supplements,
        "created_at": now_iso(),
    }
    packet["snapshot"] = _snapshot(context, authority_refs, snapshot_paths)
    return packet


def build_supplemented_packet(
    context: ProjectContext,
    task_root: Path,
    task: dict,
    previous: dict,
    *,
    refs: list[dict],
) -> dict:
    delegation = previous.get("delegation") or {}
    profile_data = previous.get("requested_profile") or {}
    profile = AgentProfile(
        name=str(profile_data["agent"]),
        model=str(profile_data["model"]),
        tier=str(profile_data["tier"]),
        reasoning_effort=str(profile_data["reasoning_effort"]),
        sandbox_mode=str(profile_data["sandbox_mode"]),
        source=Path("<frozen-request>"),
    )
    from delegation_policy import policy_for_role

    policy = policy_for_role(profile.name)
    objective = previous.get("objective") or {}
    scope = previous.get("scope") or {}
    target = previous.get("target") or {}
    start_refs = [str(item["ref"]) for item in previous.get("start_here") or []]
    facts = [
        str(item.get("statement"))
        for item in previous.get("confirmed_facts") or []
        if item.get("statement")
    ]
    prior = list(previous.get("context_supplements") or [])
    return build_request_packet(
        context,
        task_root,
        task,
        delegation_id=str(delegation["id"]),
        attempt=int(delegation["attempt"]) + 1,
        profile=profile,
        policy=policy,
        target_type=str(target["type"]),
        target_ref=str(target["ref"]),
        purpose=str(objective.get("purpose") or ""),
        question=str(objective.get("question") or ""),
        decision_supported=str(objective.get("decision_supported") or ""),
        include=list(scope.get("include") or []),
        exclude=list(scope.get("exclude") or []),
        start_refs=start_refs,
        confirmed_facts=facts,
        supplemental_refs=[*prior, *refs],
    )
