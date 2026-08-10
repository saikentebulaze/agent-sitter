from __future__ import annotations

import copy
from pathlib import Path

from agent_profiles import AgentProfileError, load_agent_profile
from delegation_context import (
    DelegationContextError,
    build_request_packet,
    build_supplemented_packet,
    verify_snapshot,
)
from delegation_policy import DelegationPolicyError, policy_for_role
from delegation_validation import validate_delegation_state
from project_context import ProjectContext
from review_transaction import atomic_write_text
from work_graph import (
    WorkGraphError,
    load_yaml,
    now_iso,
    project_relative,
    resolve_task_root,
    valid_id,
)


class DelegationTransactionError(WorkGraphError):
    pass


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content.decode("utf-8"))


def _transaction(
    writes: dict[Path, str],
    *,
    validator,
    cleanup_dirs: list[Path] | None = None,
) -> None:
    before = _snapshot(list(writes))
    try:
        for path, content in writes.items():
            atomic_write_text(path, content)
        validator()
    except BaseException:
        _restore(before)
        for directory in cleanup_dirs or []:
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        raise


def _load_task(
    context: ProjectContext, task_value: str | Path
) -> tuple[Path, Path, dict]:
    task_root = resolve_task_root(context, task_value)
    task_path = task_root / "task.yaml"
    return task_root, task_path, load_yaml(task_path)


def _delegation(task: dict) -> dict:
    value = task.setdefault("delegation", {})
    value.setdefault("protocol_version", 1)
    value.setdefault("planned", [])
    value.setdefault("completed", [])
    value.setdefault("failed", [])
    return value


def _entry_by_id(task: dict, delegation_id: str) -> dict:
    for item in (_delegation(task).get("planned") or []):
        if item.get("id") == delegation_id:
            return item
    raise DelegationTransactionError(f"delegation not found: {delegation_id}")


def _next_id(task: dict) -> str:
    maximum = 0
    delegation = _delegation(task)
    for collection in ("planned", "completed", "failed"):
        for item in delegation.get(collection) or []:
            value = str(item.get("id") or "")
            if value.startswith("dlg-") and value[4:].isdigit():
                maximum = max(maximum, int(value[4:]))
    return f"dlg-{maximum + 1:03d}"


def _relation(parent_tier: str, child_tier: str) -> tuple[str, bool]:
    order = {"luna": 0, "terra": 1, "sol": 2}
    if parent_tier not in order:
        return "unknown", child_tier in {"terra", "sol"}
    delta = order[child_tier] - order[parent_tier]
    return (
        "stronger" if delta > 0 else ("same" if delta == 0 else "weaker"),
        delta > 0,
    )


def authorize_delegation(
    context: ProjectContext,
    task_value: str | Path,
    *,
    decision: str,
    scopes: list[str],
    evidence: str,
    parent_model: str,
    parent_tier: str,
) -> None:
    if decision not in {"required", "optional"}:
        raise DelegationTransactionError("delegation decision must be required or optional")
    allowed = {"readonly-exploration", "readonly-review"}
    if not scopes or any(scope not in allowed for scope in scopes):
        raise DelegationTransactionError(
            "delegation scopes must contain readonly-exploration and/or readonly-review"
        )
    if parent_tier not in {"luna", "terra", "sol", "unknown"}:
        raise DelegationTransactionError("invalid parent tier")
    if not evidence.strip():
        raise DelegationTransactionError("delegation authorization evidence is required")

    task_root, task_path, task = _load_task(context, task_value)
    delegation = _delegation(task)
    if delegation.get("planned") or delegation.get("completed") or delegation.get("failed"):
        raise DelegationTransactionError(
            "delegation authorization cannot be replaced after delegation work exists"
        )
    delegation["decision"] = decision
    delegation["authorization"] = {
        "status": "granted",
        "scopes": list(dict.fromkeys(scopes)),
        "evidence": evidence,
    }
    budget = delegation.setdefault("model_budget", {})
    budget["parent_model"] = parent_model
    budget["parent_tier"] = parent_tier
    budget.setdefault("default_ceiling", "parent")
    task["delegation"] = delegation
    task.setdefault("timeline", []).append(
        {
            "type": "delegation-authorized",
            "at": now_iso(),
            "decision": decision,
            "scopes": list(dict.fromkeys(scopes)),
            "evidence": evidence,
        }
    )
    import yaml

    _transaction(
        {task_path: yaml.safe_dump(task, allow_unicode=True, sort_keys=False)},
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
    )


def request_delegation(
    context: ProjectContext,
    task_value: str | Path,
    *,
    role: str,
    target_type: str,
    target_ref: str,
    purpose: str,
    question: str,
    decision_supported: str,
    include: list[str],
    exclude: list[str],
    start_refs: list[str],
    confirmed_facts: list[str],
) -> Path:
    task_root, task_path, task = _load_task(context, task_value)
    if task.get("status") == "completed":
        raise DelegationTransactionError("cannot delegate from a completed task")
    escalation = task.get("escalation") or {}
    if escalation.get("level") in {"stronger-model", "human-checkpoint", "blocked"}:
        raise DelegationTransactionError(
            "regular delegation is blocked during an active escalation"
        )
    delegation = _delegation(task)
    authorization = delegation.get("authorization") or {}
    if authorization.get("status") != "granted":
        raise DelegationTransactionError("delegation authorization is not granted")

    try:
        profile = load_agent_profile(context, role)
        policy = policy_for_role(role)
    except (AgentProfileError, DelegationPolicyError) as error:
        raise DelegationTransactionError(str(error)) from error
    if policy.authorization_scope not in (authorization.get("scopes") or []):
        raise DelegationTransactionError(
            f"{role} requires authorization scope {policy.authorization_scope}"
        )

    budget = delegation.get("model_budget") or {}
    parent_tier = str(budget.get("parent_tier", "unknown"))
    relation, elevated = _relation(parent_tier, profile.tier)
    elevation_status = "not-required"
    if elevated:
        elevated_auth = budget.get("elevated_authorization") or {}
        approved = set(map(str, elevated_auth.get("approved_tiers") or []))
        if elevated_auth.get("status") != "granted" or profile.tier not in approved:
            raise DelegationTransactionError(
                f"{role} requires elevated-model authorization for tier {profile.tier}"
            )
        elevation_status = "granted"

    delegation_id = _next_id(task)
    directory = task_root / "delegations" / delegation_id
    packet_path = directory / "attempt-01.request.yaml"
    if directory.exists():
        raise DelegationTransactionError(
            f"delegation directory already exists: {delegation_id}"
        )

    try:
        packet = build_request_packet(
            context,
            task_root,
            task,
            delegation_id=delegation_id,
            attempt=1,
            profile=profile,
            policy=policy,
            target_type=target_type,
            target_ref=target_ref,
            purpose=purpose,
            question=question,
            decision_supported=decision_supported,
            include=include,
            exclude=exclude,
            start_refs=start_refs,
            confirmed_facts=confirmed_facts,
        )
    except DelegationContextError as error:
        raise DelegationTransactionError(str(error)) from error

    entry = {
        "id": delegation_id,
        "agent": profile.name,
        "model": profile.model,
        "tier": profile.tier,
        "reasoning_effort": profile.reasoning_effort,
        "default_reasoning_effort": profile.reasoning_effort,
        "effort_escalation": "not-required",
        "purpose": purpose,
        "relation_to_parent": relation,
        "elevation_authorization": elevation_status,
        "target": {"type": target_type, "ref": target_ref},
        "context": {
            "inheritance": "none",
            "projection": policy.projection,
            "attempt": 1,
            "request_ref": project_relative(context, packet_path),
        },
        "status": "requested",
    }
    task_after = copy.deepcopy(task)
    _delegation(task_after).setdefault("planned", []).append(entry)
    task_after.setdefault("timeline", []).append(
        {
            "type": "delegation-requested",
            "at": now_iso(),
            "ref": delegation_id,
            "agent": profile.name,
            "target": entry["target"],
        }
    )
    import yaml

    writes = {
        packet_path: yaml.safe_dump(packet, allow_unicode=True, sort_keys=False),
        task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False),
    }
    _transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
        cleanup_dirs=[directory],
    )
    return packet_path


def _safe_artifact(context: ProjectContext, value: Path, label: str) -> Path:
    path = value.resolve() if value.is_absolute() else (context.project_root / value).resolve()
    try:
        path.relative_to(context.project_root)
    except ValueError as error:
        raise DelegationTransactionError(f"{label} is outside project") from error
    if not path.is_file():
        raise DelegationTransactionError(f"{label} does not exist: {path}")
    return path


def _validate_attestation(packet: dict, attestation: dict) -> None:
    execution = attestation.get("execution") or {}
    observed = attestation.get("observed") or {}
    expected = packet.get("requested_profile") or {}
    evidence = attestation.get("evidence") or {}
    if attestation.get("schema_version") != 2:
        raise DelegationTransactionError("runtime attestation schema_version must be 2")
    if execution.get("method") != "native-subagent":
        raise DelegationTransactionError("attestation must prove native-subagent execution")
    if execution.get("collector") != "codex-rollout-app-server-v1":
        raise DelegationTransactionError(
            "runtime attestation must come from codex-rollout-app-server-v1"
        )
    if evidence.get("source") != "verified-combined":
        raise DelegationTransactionError(
            "runtime attestation must use verified-combined evidence"
        )
    if not execution.get("spawn_call_id") or not execution.get("session_ref"):
        raise DelegationTransactionError(
            "runtime attestation is missing the spawn call or child session"
        )
    checks = {
        "agent": expected.get("agent"),
        "model": expected.get("model"),
        "tier": expected.get("tier"),
        "reasoning_effort": expected.get("reasoning_effort"),
        "sandbox_mode": expected.get("sandbox_mode"),
    }
    mismatches = [
        key for key, value in checks.items() if observed.get(key) != value
    ]
    if observed.get("context_inheritance") != "none":
        mismatches.append("context_inheritance")
    if not observed.get("child_thread_id"):
        mismatches.append("child_thread_id")
    if not observed.get("parent_thread_id"):
        mismatches.append("parent_thread_id")
    if mismatches:
        raise DelegationTransactionError(
            "runtime attestation mismatch: " + ", ".join(mismatches)
        )


def record_delegation_result(
    context: ProjectContext,
    task_value: str | Path,
    delegation_id: str,
    *,
    artifact: Path,
    outcome: str,
    evidence_ref: str,
    attestation: Path,
) -> tuple[Path, str, bool]:
    if outcome not in {"completed", "need-context", "failed"}:
        raise DelegationTransactionError(
            "delegation outcome must be completed, need-context, or failed"
        )
    if not evidence_ref.strip():
        raise DelegationTransactionError("delegation evidence_ref is required")

    task_root, task_path, task = _load_task(context, task_value)
    delegation_id = valid_id(delegation_id, "delegation_id")
    planned = _entry_by_id(task, delegation_id)
    context_data = planned.get("context") or {}
    packet_path = context.project_root / str(context_data.get("request_ref"))
    packet = load_yaml(packet_path)
    attempt = int((packet.get("delegation") or {}).get("attempt", 0))
    directory = packet_path.parent
    result_path = directory / f"attempt-{attempt:02d}.result.md"
    record_path = directory / f"attempt-{attempt:02d}.record.yaml"

    artifact_path = _safe_artifact(context, artifact, "delegation artifact")
    artifact_text = artifact_path.read_text(encoding="utf-8")
    if not artifact_text.strip():
        raise DelegationTransactionError("delegation artifact is empty")
    attestation_path = _safe_artifact(context, attestation, "delegation attestation")
    attestation_data = load_yaml(attestation_path)
    _validate_attestation(packet, attestation_data)

    changed = verify_snapshot(context, packet)
    effective_outcome = "stale" if changed else outcome
    stable_record = {
        "schema_version": 1,
        "delegation_id": delegation_id,
        "attempt": attempt,
        "outcome": effective_outcome,
        "requested_outcome": outcome,
        "evidence_ref": evidence_ref,
        "request_ref": project_relative(context, packet_path),
        "output_ref": project_relative(context, result_path),
        "attestation": attestation_data,
        "stale_inputs": changed,
    }

    if record_path.exists():
        existing = load_yaml(record_path)
        existing_stable = dict(existing)
        existing_stable.pop("recorded_at", None)
        if (
            existing_stable == stable_record
            and result_path.is_file()
            and result_path.read_text(encoding="utf-8") == artifact_text
        ):
            return result_path, effective_outcome, True
        raise DelegationTransactionError(
            f"conflicting delegation result already exists: {record_path}"
        )
    if result_path.exists():
        raise DelegationTransactionError(
            f"delegation output exists without matching record: {result_path}"
        )
    record = {**stable_record, "recorded_at": now_iso()}

    task_after = copy.deepcopy(task)
    planned_after = _entry_by_id(task_after, delegation_id)
    planned_after["status"] = effective_outcome
    profile = packet["requested_profile"]
    completed_entry = {
        "id": delegation_id,
        "agent": profile["agent"],
        "model": profile["model"],
        "tier": profile["tier"],
        "reasoning_effort": profile["reasoning_effort"],
        "execution": "native-subagent",
        "context": {
            "inheritance": "none",
            "projection": planned_after["context"]["projection"],
            "attempt": attempt,
            "request_ref": project_relative(context, packet_path),
        },
        "output_ref": project_relative(context, result_path),
        "record_ref": project_relative(context, record_path),
        "evidence_ref": evidence_ref,
    }
    delegation_after = _delegation(task_after)
    if effective_outcome == "completed":
        delegation_after.setdefault("completed", []).append(completed_entry)
    elif effective_outcome in {"failed", "stale"}:
        delegation_after.setdefault("failed", []).append(
            {
                "id": delegation_id,
                "agent": profile["agent"],
                "reason": (
                    "stale-context: " + ", ".join(changed)
                    if effective_outcome == "stale"
                    else "child-agent-reported-failure"
                ),
                "output_ref": project_relative(context, result_path),
                "evidence_ref": evidence_ref,
            }
        )
    task_after.setdefault("timeline", []).append(
        {
            "type": "delegation-result-recorded",
            "at": now_iso(),
            "ref": delegation_id,
            "attempt": attempt,
            "outcome": effective_outcome,
        }
    )

    import yaml

    writes = {
        result_path: artifact_text,
        record_path: yaml.safe_dump(record, allow_unicode=True, sort_keys=False),
        task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False),
    }
    _transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
    )
    return result_path, effective_outcome, False


def supplement_delegation_context(
    context: ProjectContext,
    task_value: str | Path,
    delegation_id: str,
    *,
    refs: list[str],
    reasons: list[str],
) -> Path:
    if not refs or len(refs) != len(reasons):
        raise DelegationTransactionError(
            "supplement refs and reasons must be non-empty and have matching counts"
        )
    task_root, task_path, task = _load_task(context, task_value)
    planned = _entry_by_id(task, valid_id(delegation_id, "delegation_id"))
    if planned.get("status") != "need-context":
        raise DelegationTransactionError(
            "delegation must be in need-context state before supplementing"
        )
    current_request = context.project_root / str((planned.get("context") or {}).get("request_ref"))
    previous = load_yaml(current_request)
    current_attempt = int((previous.get("delegation") or {}).get("attempt", 0))
    max_supplements = int(
        (previous.get("context_policy") or {}).get("max_context_supplements", 2)
    )
    if current_attempt - 1 >= max_supplements:
        raise DelegationTransactionError("delegation context supplement limit exceeded")

    supplements = [
        {"ref": ref, "reason": reason} for ref, reason in zip(refs, reasons)
    ]
    try:
        packet = build_supplemented_packet(
            context, task_root, task, previous, refs=supplements
        )
    except DelegationContextError as error:
        raise DelegationTransactionError(str(error)) from error
    attempt = int(packet["delegation"]["attempt"])
    packet_path = current_request.parent / f"attempt-{attempt:02d}.request.yaml"
    if packet_path.exists():
        raise DelegationTransactionError(
            f"supplemented request already exists: {packet_path}"
        )

    task_after = copy.deepcopy(task)
    planned_after = _entry_by_id(task_after, delegation_id)
    planned_after["status"] = "requested"
    planned_after["context"]["attempt"] = attempt
    planned_after["context"]["request_ref"] = project_relative(context, packet_path)
    task_after.setdefault("timeline", []).append(
        {
            "type": "delegation-context-supplemented",
            "at": now_iso(),
            "ref": delegation_id,
            "attempt": attempt,
            "supplements": supplements,
        }
    )
    import yaml

    writes = {
        packet_path: yaml.safe_dump(packet, allow_unicode=True, sort_keys=False),
        task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False),
    }
    _transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
    )
    return packet_path


def close_delegation(
    context: ProjectContext,
    task_value: str | Path,
    delegation_id: str,
    *,
    outcome: str,
    reason: str,
    evidence_ref: str,
) -> None:
    if outcome not in {"failed", "cancelled"}:
        raise DelegationTransactionError("close outcome must be failed or cancelled")
    if not reason.strip() or not evidence_ref.strip():
        raise DelegationTransactionError("reason and evidence_ref are required")
    task_root, task_path, task = _load_task(context, task_value)
    delegation_id = valid_id(delegation_id, "delegation_id")
    planned = _entry_by_id(task, delegation_id)
    if planned.get("status") in {"completed", "failed", "cancelled", "stale"}:
        raise DelegationTransactionError("delegation is already closed")

    task_after = copy.deepcopy(task)
    planned_after = _entry_by_id(task_after, delegation_id)
    planned_after["status"] = outcome
    _delegation(task_after).setdefault("failed", []).append(
        {
            "id": delegation_id,
            "agent": planned_after["agent"],
            "reason": f"{outcome}: {reason}",
            "evidence_ref": evidence_ref,
        }
    )
    task_after.setdefault("timeline", []).append(
        {
            "type": f"delegation-{outcome}",
            "at": now_iso(),
            "ref": delegation_id,
            "reason": reason,
            "evidence_ref": evidence_ref,
        }
    )
    import yaml

    _transaction(
        {task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False)},
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
    )


def delegation_status(
    context: ProjectContext, task_value: str | Path, delegation_id: str | None
) -> dict:
    _, _, task = _load_task(context, task_value)
    delegation = _delegation(task)
    if delegation_id is None:
        return {
            "decision": delegation.get("decision"),
            "authorization": delegation.get("authorization"),
            "planned": delegation.get("planned") or [],
            "completed": delegation.get("completed") or [],
            "failed": delegation.get("failed") or [],
        }
    entry = _entry_by_id(task, valid_id(delegation_id, "delegation_id"))
    completed = next(
        (
            item
            for item in delegation.get("completed") or []
            if item.get("id") == delegation_id
        ),
        None,
    )
    failed = next(
        (
            item
            for item in delegation.get("failed") or []
            if item.get("id") == delegation_id
        ),
        None,
    )
    return {"planned": entry, "completed": completed, "failed": failed}
