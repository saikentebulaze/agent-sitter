from __future__ import annotations

from pathlib import Path

from core.provider_registry import get_provider
from core.task_runtime import orchestrator_provider
from delegation_policy import DelegationPolicyError, policy_for_role
from project_context import ProjectContext
from work_graph import WorkGraphError, load_yaml


DELEGATION_DECISIONS = {"required", "optional", "not-needed"}
AUTH_STATUSES = {"not-required", "pending", "granted", "denied"}
ENTRY_STATUSES = {"requested", "need-context", "completed", "failed", "cancelled", "stale"}
TIER_RANKS = {
    "low": 0,
    "luna": 0,
    "medium": 1,
    "terra": 1,
    "high": 2,
    "sol": 2,
    "unknown": -1,
}
EFFORTS = {"none": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}
COMPLETED_EXECUTIONS = {
    "native-subagent",
    "app-server-isolated-agent",
    "claude-native-subagent",
    "claude-managed-agent",
}


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkGraphError(f"{label} must be a non-empty string")
    return value.strip()


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise WorkGraphError(f"{label} must be a mapping")
    return value


def _list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise WorkGraphError(f"{label} must be a list")
    return value


def _inside_task(task_root: Path, value: str, label: str) -> Path:
    project_root = task_root.parent.parent
    path = (project_root / value).resolve()
    try:
        path.relative_to(task_root.resolve())
    except ValueError as error:
        raise WorkGraphError(
            f"{label} must remain inside the task directory: {value}"
        ) from error
    return path


def _entries(values: object, label: str) -> list[dict]:
    items = _list(values or [], label)
    result: list[dict] = []
    ids: set[str] = set()
    for index, item in enumerate(items):
        entry = _mapping(item, f"{label}[{index}]")
        delegation_id = _non_empty(entry.get("id"), f"{label}[{index}].id")
        if delegation_id in ids:
            raise WorkGraphError(f"duplicate delegation id in {label}: {delegation_id}")
        ids.add(delegation_id)
        result.append(entry)
    return result


def _tier(value: object, label: str, *, allow_unknown: bool = False) -> str:
    tier = _non_empty(value, label).lower()
    if tier not in TIER_RANKS or (tier == "unknown" and not allow_unknown):
        raise WorkGraphError(f"{label} is invalid: {tier}")
    return tier


def _same_grade(left: str, right: str) -> bool:
    return TIER_RANKS.get(left) == TIER_RANKS.get(right) and left != "unknown" and right != "unknown"


def _approved_grade(values: set[str], tier: str) -> bool:
    return any(_same_grade(value, tier) for value in values if value in TIER_RANKS)


def validate_delegation_state(
    context: ProjectContext,
    task_root: Path,
    task: dict,
    *,
    require_resolved: bool | None = None,
) -> None:
    provider_id = orchestrator_provider(task)
    provider = get_provider(provider_id)
    delegation = _mapping(task.get("delegation") or {}, "task.delegation")
    if delegation.get("protocol_version", 1) != 1:
        raise WorkGraphError("delegation.protocol_version must be 1")
    decision = str(delegation.get("decision", "not-needed"))
    if decision not in DELEGATION_DECISIONS:
        raise WorkGraphError(f"invalid delegation decision: {decision}")

    authorization = _mapping(
        delegation.get("authorization") or {}, "delegation.authorization"
    )
    auth_status = str(authorization.get("status", "not-required"))
    if auth_status not in AUTH_STATUSES:
        raise WorkGraphError(f"invalid delegation authorization status: {auth_status}")
    scopes = _list(
        authorization.get("scopes") or [], "delegation.authorization.scopes"
    )
    allowed_scopes = {
        "readonly-exploration",
        "readonly-review",
        "bounded-implementation",
    }
    if any(scope not in allowed_scopes for scope in scopes):
        raise WorkGraphError("delegation authorization contains an invalid scope")

    raw_planned = _list(delegation.get("planned") or [], "delegation.planned")
    if raw_planned and auth_status != "granted":
        raise WorkGraphError("planned delegation requires granted authorization")
    planned = _entries(raw_planned, "delegation.planned")
    completed = _entries(delegation.get("completed") or [], "delegation.completed")
    failed = _entries(delegation.get("failed") or [], "delegation.failed")
    planned_by_id = {str(item["id"]): item for item in planned}
    completed_by_id = {str(item["id"]): item for item in completed}
    failed_by_id = {str(item["id"]): item for item in failed}

    resolved_required = require_resolved
    if resolved_required is None:
        resolved_required = task.get("status") == "completed"

    overlap = set(completed_by_id) & set(failed_by_id)
    if overlap:
        raise WorkGraphError(
            "delegation cannot be both completed and failed: "
            + ", ".join(sorted(overlap))
        )
    unexpected = (set(completed_by_id) | set(failed_by_id)) - set(planned_by_id)
    if unexpected:
        raise WorkGraphError(
            "delegation disposition is not planned: "
            + ", ".join(sorted(unexpected))
        )

    if decision == "not-needed":
        if planned or completed or failed:
            raise WorkGraphError(
                "not-needed delegation cannot contain planned/completed/failed entries"
            )
        if auth_status not in {"not-required", "denied"}:
            raise WorkGraphError(
                "not-needed delegation authorization must be not-required or denied"
            )
        return
    if resolved_required and decision == "required" and not planned:
        raise WorkGraphError("required delegation has no planned entries")

    budget = _mapping(
        delegation.get("model_budget") or {}, "delegation.model_budget"
    )
    parent_tier = _tier(
        budget.get("parent_tier", "unknown"),
        "delegation.model_budget.parent_tier",
        allow_unknown=True,
    )
    elevated = _mapping(
        budget.get("elevated_authorization") or {},
        "delegation.model_budget.elevated_authorization",
    )
    approved_tiers = {
        str(value).lower() for value in elevated.get("approved_tiers") or []
    }
    reasoning = _mapping(
        budget.get("reasoning_authorization") or {},
        "delegation.model_budget.reasoning_authorization",
    )
    approved_efforts = {
        str(value).lower() for value in reasoning.get("approved_efforts") or []
    }

    packets: dict[str, dict] = {}
    for entry in planned:
        delegation_id = str(entry["id"])
        entry_provider = str(entry.get("provider") or provider_id)
        if entry_provider != provider_id:
            raise WorkGraphError(
                f"{delegation_id} provider differs from Task orchestrator provider"
            )
        agent = _non_empty(entry.get("agent"), f"{delegation_id}.agent")
        model = _non_empty(entry.get("model"), f"{delegation_id}.model")
        tier = _tier(entry.get("tier"), f"{delegation_id}.tier")
        effort = _non_empty(
            entry.get("reasoning_effort"), f"{delegation_id}.reasoning_effort"
        ).lower()
        default_effort = _non_empty(
            entry.get("default_reasoning_effort"),
            f"{delegation_id}.default_reasoning_effort",
        ).lower()
        if effort not in EFFORTS or default_effort not in EFFORTS:
            raise WorkGraphError(f"{delegation_id} has invalid reasoning effort")
        try:
            profile = provider.load_role_profile(context, agent)
            policy = policy_for_role(agent)
        except (ValueError, DelegationPolicyError) as error:
            raise WorkGraphError(str(error)) from error
        if model != profile.model or not _same_grade(tier, profile.tier):
            raise WorkGraphError(
                f"{delegation_id} profile differs from {provider_id} provider configuration"
            )
        if policy.authorization_scope not in scopes:
            raise WorkGraphError(
                f"{delegation_id} requires authorization scope "
                f"{policy.authorization_scope}"
            )
        if effort != profile.reasoning_effort:
            delta = EFFORTS[effort] - EFFORTS[profile.reasoning_effort]
            escalation = str(entry.get("effort_escalation", "not-required"))
            if effort in {"xhigh", "max"} or delta >= 2:
                if (
                    escalation != "granted"
                    or str(reasoning.get("status")) != "granted"
                    or effort not in approved_efforts
                ):
                    raise WorkGraphError(
                        f"{delegation_id} lacks exceptional reasoning authorization"
                    )
            elif delta == 1 and escalation != "recorded":
                raise WorkGraphError(
                    f"{delegation_id} one-step reasoning increase must be recorded"
                )

        relation = str(entry.get("relation_to_parent", "unknown"))
        if parent_tier == "unknown":
            expected_relation = "unknown"
            needs_elevation = TIER_RANKS[tier] > 0
        else:
            delta = TIER_RANKS[tier] - TIER_RANKS[parent_tier]
            expected_relation = (
                "stronger" if delta > 0 else ("same" if delta == 0 else "weaker")
            )
            needs_elevation = delta > 0
        if relation != expected_relation:
            raise WorkGraphError(
                f"{delegation_id} relation_to_parent must be {expected_relation}"
            )
        elevation = str(entry.get("elevation_authorization", "not-required"))
        if needs_elevation:
            if (
                elevation != "granted"
                or str(elevated.get("status")) != "granted"
                or not _approved_grade(approved_tiers, tier)
            ):
                raise WorkGraphError(
                    f"{delegation_id} lacks elevated-model authorization"
                )
        elif elevation != "not-required":
            raise WorkGraphError(
                f"{delegation_id} does not require elevated-model authorization"
            )

        status = str(entry.get("status", "requested"))
        if status not in ENTRY_STATUSES:
            raise WorkGraphError(f"{delegation_id} has invalid status: {status}")
        context_data = _mapping(
            entry.get("context") or {}, f"{delegation_id}.context"
        )
        if context_data.get("inheritance") != "none":
            raise WorkGraphError(f"{delegation_id} must use independent context")
        request_ref = _non_empty(
            context_data.get("request_ref"), f"{delegation_id}.context.request_ref"
        )
        request_path = _inside_task(task_root, request_ref, "delegation request")
        if not request_path.is_file():
            raise WorkGraphError(f"delegation request is missing: {request_ref}")
        packet = load_yaml(request_path)
        packets[delegation_id] = packet
        packet_delegation = packet.get("delegation") or {}
        if packet_delegation.get("id") != delegation_id:
            raise WorkGraphError(f"{delegation_id} request packet id mismatch")
        packet_runtime = packet.get("runtime") or {}
        packet_provider = str(packet_runtime.get("provider") or "codex")
        if packet_provider != provider_id:
            raise WorkGraphError(
                f"{delegation_id} request provider differs from Task orchestrator provider"
            )
        if (packet.get("context_policy") or {}).get("inheritance") != "none":
            raise WorkGraphError(
                f"{delegation_id} request permits inherited context"
            )

    for delegation_id, entry in completed_by_id.items():
        planned_entry = planned_by_id[delegation_id]
        for key in ("agent", "model", "reasoning_effort"):
            if str(entry.get(key)) != str(planned_entry.get(key)):
                raise WorkGraphError(
                    f"completed delegation {delegation_id} {key} differs from plan"
                )
        completed_tier = _tier(
            entry.get("tier"), f"completed delegation {delegation_id}.tier"
        )
        planned_tier = _tier(
            planned_entry.get("tier"), f"planned delegation {delegation_id}.tier"
        )
        if not _same_grade(completed_tier, planned_tier):
            raise WorkGraphError(
                f"completed delegation {delegation_id} tier differs from plan"
            )
        completed_provider = str(entry.get("provider") or provider_id)
        if completed_provider != provider_id:
            raise WorkGraphError(
                f"completed delegation {delegation_id} provider differs from Task"
            )
        execution = str(entry.get("execution") or "")
        if execution not in COMPLETED_EXECUTIONS:
            raise WorkGraphError(
                f"completed delegation {delegation_id} has invalid execution: "
                f"{execution}"
            )
        context_data = _mapping(
            entry.get("context") or {}, f"completed {delegation_id}.context"
        )
        if context_data.get("inheritance") != "none":
            raise WorkGraphError(
                f"completed delegation {delegation_id} inherited parent context"
            )
        for key in ("output_ref", "record_ref", "evidence_ref"):
            value = _non_empty(entry.get(key), f"completed {delegation_id}.{key}")
            if key != "evidence_ref":
                path = _inside_task(
                    task_root, value, f"completed {delegation_id}.{key}"
                )
                if not path.is_file():
                    raise WorkGraphError(
                        f"completed delegation artifact is missing: {value}"
                    )

    for delegation_id, entry in failed_by_id.items():
        _non_empty(entry.get("reason"), f"failed {delegation_id}.reason")

    if resolved_required and decision == "required":
        unresolved = [
            delegation_id
            for delegation_id, entry in planned_by_id.items()
            if delegation_id not in completed_by_id
            and delegation_id not in failed_by_id
            and str(entry.get("status")) != "cancelled"
        ]
        if unresolved:
            raise WorkGraphError(
                "required delegation remains unresolved: "
                + ", ".join(sorted(unresolved))
            )
        if failed_by_id and not bool(delegation.get("user_override", False)):
            raise WorkGraphError(
                "required delegation failed without explicit user override"
            )
