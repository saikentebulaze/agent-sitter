"""Provider-aware delegation transactions for non-legacy Runtime Providers.

Codex continues to use the retained V5-A transaction implementation. This
module supplies the schema-v2 path needed by Claude without reinterpreting a
Task's immutable orchestrator Provider or flattening Provider-native execution
methods into Codex vocabulary.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import yaml

import _delegation_transaction_impl as legacy
from core.provider_registry import get_provider
from core.task_runtime import orchestrator_provider
from delegation_context import (
    DelegationContextError,
    build_request_packet,
    build_supplemented_packet,
    verify_snapshot,
)
from delegation_policy import DelegationPolicyError, policy_for_role
from delegation_validation import EFFORTS, TIER_RANKS, validate_delegation_state
from provider_attestation import validate_provider_attestation
from project_context import ProjectContext
from work_graph import load_yaml, now_iso, project_relative, valid_id


class ProviderDelegationTransactionError(legacy.DelegationTransactionError):
    pass


@dataclass(frozen=True)
class _ContextProfile:
    name: str
    model: str
    tier: str
    reasoning_effort: str
    sandbox_mode: str
    source: Path


def _provider_profile(context: ProjectContext, task: dict, role: str):
    provider_id = orchestrator_provider(task)
    provider = get_provider(provider_id)
    try:
        profile = provider.load_role_profile(context, role)
        policy = policy_for_role(role)
    except (ValueError, DelegationPolicyError) as error:
        raise ProviderDelegationTransactionError(str(error)) from error
    return provider_id, provider, profile, policy


def _context_profile(profile) -> _ContextProfile:
    return _ContextProfile(
        name=profile.role_id,
        model=profile.model,
        tier=profile.tier,
        reasoning_effort=profile.reasoning_effort,
        sandbox_mode=profile.write_isolation,
        source=profile.source,
    )


def _grade_rank(value: str) -> int:
    try:
        return TIER_RANKS[value.lower()]
    except KeyError as error:
        raise ProviderDelegationTransactionError(
            f"invalid model grade or legacy tier: {value}"
        ) from error


def _relation(parent_tier: str, child_tier: str) -> tuple[str, bool]:
    child_rank = _grade_rank(child_tier)
    if parent_tier == "unknown":
        return "unknown", child_rank > 0
    parent_rank = _grade_rank(parent_tier)
    delta = child_rank - parent_rank
    return (
        "stronger" if delta > 0 else ("same" if delta == 0 else "weaker"),
        delta > 0,
    )


def _grade_approved(values: set[str], child_tier: str) -> bool:
    child_rank = _grade_rank(child_tier)
    return any(
        value in TIER_RANKS and TIER_RANKS[value] == child_rank
        for value in values
    )


def _schema_v2_packet(packet: dict, provider_id: str, profile) -> dict:
    result = copy.deepcopy(packet)
    result["schema_version"] = 2
    result["runtime"] = {"provider": provider_id}
    result["requested_profile"] = {
        "schema_version": 2,
        "provider": provider_id,
        "agent": profile.role_id,
        "role_id": profile.role_id,
        "runtime_role": profile.runtime_role,
        "model": profile.model,
        "model_selector": profile.model,
        "tier": profile.tier,
        "model_grade": profile.tier,
        "reasoning_effort": profile.reasoning_effort,
        "sandbox_mode": profile.write_isolation,
        "write_isolation": profile.write_isolation,
        "source": str(profile.source),
    }
    return result


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
        raise ProviderDelegationTransactionError(
            "delegation decision must be required or optional"
        )
    allowed = {"readonly-exploration", "readonly-review"}
    if not scopes or any(scope not in allowed for scope in scopes):
        raise ProviderDelegationTransactionError(
            "delegation scopes must contain readonly-exploration and/or readonly-review"
        )
    parent_tier = str(parent_tier).lower()
    if parent_tier not in TIER_RANKS:
        raise ProviderDelegationTransactionError("invalid parent model grade or tier")
    if not evidence.strip():
        raise ProviderDelegationTransactionError(
            "delegation authorization evidence is required"
        )

    task_root, task_path, task = legacy._load_task(context, task_value)
    delegation = legacy._delegation(task)
    if delegation.get("planned") or delegation.get("completed") or delegation.get("failed"):
        raise ProviderDelegationTransactionError(
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
            "provider": orchestrator_provider(task),
        }
    )
    legacy._transaction(
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
    task_root, task_path, task = legacy._load_task(context, task_value)
    if task.get("status") == "completed":
        raise ProviderDelegationTransactionError(
            "cannot delegate from a completed task"
        )
    escalation = task.get("escalation") or {}
    if escalation.get("level") in {"stronger-model", "human-checkpoint", "blocked"}:
        raise ProviderDelegationTransactionError(
            "regular delegation is blocked during an active escalation"
        )
    delegation = legacy._delegation(task)
    authorization = delegation.get("authorization") or {}
    if authorization.get("status") != "granted":
        raise ProviderDelegationTransactionError(
            "delegation authorization is not granted"
        )

    provider_id, _, profile, policy = _provider_profile(context, task, role)
    if policy.authorization_scope not in (authorization.get("scopes") or []):
        raise ProviderDelegationTransactionError(
            f"{role} requires authorization scope {policy.authorization_scope}"
        )

    budget = delegation.get("model_budget") or {}
    parent_tier = str(budget.get("parent_tier", "unknown")).lower()
    relation, elevated = _relation(parent_tier, profile.tier)
    elevation_status = "not-required"
    if elevated:
        elevated_auth = budget.get("elevated_authorization") or {}
        approved = {
            str(value).lower()
            for value in elevated_auth.get("approved_tiers") or []
        }
        if (
            elevated_auth.get("status") != "granted"
            or not _grade_approved(approved, profile.tier)
        ):
            raise ProviderDelegationTransactionError(
                f"{role} requires elevated-model authorization for grade {profile.tier}"
            )
        elevation_status = "granted"

    delegation_id = legacy._next_id(task)
    directory = task_root / "delegations" / delegation_id
    packet_path = directory / "attempt-01.request.yaml"
    if directory.exists():
        raise ProviderDelegationTransactionError(
            f"delegation directory already exists: {delegation_id}"
        )

    try:
        base_packet = build_request_packet(
            context,
            task_root,
            task,
            delegation_id=delegation_id,
            attempt=1,
            profile=_context_profile(profile),
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
        packet = _schema_v2_packet(base_packet, provider_id, profile)
    except DelegationContextError as error:
        raise ProviderDelegationTransactionError(str(error)) from error

    entry = {
        "id": delegation_id,
        "provider": provider_id,
        "agent": profile.role_id,
        "runtime_role": profile.runtime_role,
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
    legacy._delegation(task_after).setdefault("planned", []).append(entry)
    task_after.setdefault("timeline", []).append(
        {
            "type": "delegation-requested",
            "at": now_iso(),
            "ref": delegation_id,
            "provider": provider_id,
            "agent": profile.role_id,
            "target": entry["target"],
        }
    )
    writes = {
        packet_path: yaml.safe_dump(packet, allow_unicode=True, sort_keys=False),
        task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False),
    }
    legacy._transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
        cleanup_dirs=[directory],
    )
    return packet_path


def _frozen_profile(packet: dict):
    data = packet.get("requested_profile") or {}
    return _ContextProfile(
        name=str(data.get("role_id") or data.get("agent") or ""),
        model=str(data.get("model_selector") or data.get("model") or ""),
        tier=str(data.get("model_grade") or data.get("tier") or ""),
        reasoning_effort=str(data.get("reasoning_effort") or ""),
        sandbox_mode=str(data.get("write_isolation") or data.get("sandbox_mode") or ""),
        source=Path(str(data.get("source") or "<frozen-request>")),
    )


def supplement_delegation_context(
    context: ProjectContext,
    task_value: str | Path,
    delegation_id: str,
    *,
    refs: list[str],
    reasons: list[str],
) -> Path:
    if not refs or len(refs) != len(reasons):
        raise ProviderDelegationTransactionError(
            "supplement refs and reasons must be non-empty and have matching counts"
        )
    task_root, task_path, task = legacy._load_task(context, task_value)
    provider_id = orchestrator_provider(task)
    planned = legacy._entry_by_id(task, valid_id(delegation_id, "delegation_id"))
    if str(planned.get("provider") or provider_id) != provider_id:
        raise ProviderDelegationTransactionError(
            "delegation Provider differs from Task orchestrator Provider"
        )
    if planned.get("status") != "need-context":
        raise ProviderDelegationTransactionError(
            "delegation must be in need-context state before supplementing"
        )
    current_request = context.project_root / str(
        (planned.get("context") or {}).get("request_ref")
    )
    previous = load_yaml(current_request)
    if str((previous.get("runtime") or {}).get("provider") or "codex") != provider_id:
        raise ProviderDelegationTransactionError(
            "supplemented request cannot change runtime Provider"
        )
    current_attempt = int((previous.get("delegation") or {}).get("attempt", 0))
    max_supplements = int(
        (previous.get("context_policy") or {}).get("max_context_supplements", 2)
    )
    if current_attempt - 1 >= max_supplements:
        raise ProviderDelegationTransactionError(
            "delegation context supplement limit exceeded"
        )

    supplements = [
        {"ref": ref, "reason": reason} for ref, reason in zip(refs, reasons)
    ]
    try:
        packet = build_supplemented_packet(
            context,
            task_root,
            task,
            previous,
            refs=supplements,
        )
    except DelegationContextError as error:
        raise ProviderDelegationTransactionError(str(error)) from error
    frozen = previous.get("requested_profile") or {}
    packet["schema_version"] = 2
    packet["runtime"] = {"provider": provider_id}
    packet["requested_profile"] = copy.deepcopy(frozen)
    attempt = int(packet["delegation"]["attempt"])
    packet_path = current_request.parent / f"attempt-{attempt:02d}.request.yaml"
    if packet_path.exists():
        raise ProviderDelegationTransactionError(
            f"supplemented request already exists: {packet_path}"
        )

    task_after = copy.deepcopy(task)
    planned_after = legacy._entry_by_id(task_after, delegation_id)
    planned_after["status"] = "requested"
    planned_after["context"]["attempt"] = attempt
    planned_after["context"]["request_ref"] = project_relative(
        context, packet_path
    )
    task_after.setdefault("timeline", []).append(
        {
            "type": "delegation-context-supplemented",
            "at": now_iso(),
            "ref": delegation_id,
            "provider": provider_id,
            "attempt": attempt,
            "supplements": supplements,
        }
    )
    writes = {
        packet_path: yaml.safe_dump(packet, allow_unicode=True, sort_keys=False),
        task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False),
    }
    legacy._transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
    )
    return packet_path


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
        raise ProviderDelegationTransactionError(
            "delegation outcome must be completed, need-context, or failed"
        )
    if not evidence_ref.strip():
        raise ProviderDelegationTransactionError(
            "delegation evidence_ref is required"
        )

    task_root, task_path, task = legacy._load_task(context, task_value)
    provider_id = orchestrator_provider(task)
    delegation_id = valid_id(delegation_id, "delegation_id")
    planned = legacy._entry_by_id(task, delegation_id)
    if str(planned.get("provider") or provider_id) != provider_id:
        raise ProviderDelegationTransactionError(
            "delegation Provider differs from Task orchestrator Provider"
        )
    context_data = planned.get("context") or {}
    packet_path = context.project_root / str(context_data.get("request_ref"))
    packet = load_yaml(packet_path)
    if str((packet.get("runtime") or {}).get("provider") or "codex") != provider_id:
        raise ProviderDelegationTransactionError(
            "delegation request Provider differs from Task"
        )
    attempt = int((packet.get("delegation") or {}).get("attempt", 0))
    directory = packet_path.parent
    result_path = directory / f"attempt-{attempt:02d}.result.md"
    record_path = directory / f"attempt-{attempt:02d}.record.yaml"

    artifact_path = legacy._safe_artifact(context, artifact, "delegation artifact")
    artifact_text = artifact_path.read_text(encoding="utf-8")
    if not artifact_text.strip():
        raise ProviderDelegationTransactionError("delegation artifact is empty")
    attestation_path = legacy._safe_artifact(
        context, attestation, "delegation attestation"
    )
    attestation_data = load_yaml(attestation_path)
    try:
        runtime_evidence = validate_provider_attestation(packet, attestation_data)
    except (ValueError, RuntimeError) as error:
        raise ProviderDelegationTransactionError(str(error)) from error
    execution = attestation_data.get("execution") or {}
    session_ref = str(execution.get("session_ref") or "")
    if not session_ref or evidence_ref != session_ref:
        raise ProviderDelegationTransactionError(
            "delegation evidence_ref must match the attested runtime session"
        )

    changed = verify_snapshot(context, packet)
    effective_outcome = "stale" if changed else outcome
    stable_record = {
        "schema_version": 2,
        "provider": provider_id,
        "delegation_id": delegation_id,
        "attempt": attempt,
        "outcome": effective_outcome,
        "requested_outcome": outcome,
        "evidence_ref": evidence_ref,
        "request_ref": project_relative(context, packet_path),
        "output_ref": project_relative(context, result_path),
        "attestation": attestation_data,
        "normalized_runtime_evidence": {
            "provider": runtime_evidence.provider,
            "role_id": runtime_evidence.role_id,
            "context_isolation": runtime_evidence.contract.context_isolation,
            "write_isolation": runtime_evidence.contract.write_isolation,
            "persistent_context": runtime_evidence.contract.persistent_context,
            "attestation_strength": runtime_evidence.contract.attestation_strength,
            "raw_evidence_ref": runtime_evidence.raw_evidence_ref,
        },
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
        raise ProviderDelegationTransactionError(
            f"conflicting delegation result already exists: {record_path}"
        )
    if result_path.exists():
        raise ProviderDelegationTransactionError(
            f"delegation output exists without matching record: {result_path}"
        )

    task_after = copy.deepcopy(task)
    planned_after = legacy._entry_by_id(task_after, delegation_id)
    planned_after["status"] = effective_outcome
    profile = packet.get("requested_profile") or {}
    completed_entry = {
        "id": delegation_id,
        "provider": provider_id,
        "agent": profile.get("role_id") or profile.get("agent"),
        "runtime_role": profile.get("runtime_role"),
        "model": profile.get("model_selector") or profile.get("model"),
        "tier": profile.get("model_grade") or profile.get("tier"),
        "reasoning_effort": profile.get("reasoning_effort"),
        "execution": str(execution.get("method") or ""),
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
    delegation_after = legacy._delegation(task_after)
    if effective_outcome == "completed":
        delegation_after.setdefault("completed", []).append(completed_entry)
    elif effective_outcome in {"failed", "stale"}:
        delegation_after.setdefault("failed", []).append(
            {
                "id": delegation_id,
                "provider": provider_id,
                "agent": completed_entry["agent"],
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
            "provider": provider_id,
            "attempt": attempt,
            "execution": completed_entry["execution"],
            "outcome": effective_outcome,
        }
    )
    record = {**stable_record, "recorded_at": now_iso()}
    writes = {
        result_path: artifact_text,
        record_path: yaml.safe_dump(record, allow_unicode=True, sort_keys=False),
        task_path: yaml.safe_dump(task_after, allow_unicode=True, sort_keys=False),
    }
    legacy._transaction(
        writes,
        validator=lambda: validate_delegation_state(
            context, task_root, load_yaml(task_path)
        ),
    )
    return result_path, effective_outcome, False
