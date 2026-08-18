from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.provider_registry import get_provider
from core.task_runtime import orchestrator_provider
from project_context import ProjectContext
from provider_attestation import validate_provider_attestation
from reference_resolver import resolve_task_ref
from work_graph import load_yaml


class ProviderRoleRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoleRunResult:
    provider: str
    role_id: str
    output: str
    packet: dict
    attestation: dict
    evidence: dict
    session_ref: str


def _requested_profile(profile) -> dict:
    if profile.provider == "codex":
        return {
            "agent": profile.role_id,
            "role_id": profile.role_id,
            "runtime_role": profile.runtime_role,
            "model": profile.model,
            "model_selector": profile.model,
            "tier": profile.tier,
            "model_grade": profile.tier,
            "reasoning_effort": profile.reasoning_effort,
            "sandbox_mode": "read-only",
            "write_isolation": profile.write_isolation,
            "source": str(profile.source),
        }
    if profile.provider == "claude":
        return {
            "provider": profile.provider,
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
            "profile_source_ref": profile.profile_source_ref,
            "profile_source_sha256": profile.profile_source_sha256,
            "model_config_sha256": profile.model_config_sha256,
            "model_resolution_mode": profile.model_resolution_mode,
            "expected_resolved_model": profile.expected_resolved_model,
            "proxy_provider": profile.proxy_provider,
            "agent_projection_ref": profile.agent_projection_ref,
            "agent_projection_sha256": profile.agent_projection_sha256,
            "settings_projection_ref": profile.settings_projection_ref,
            "settings_projection_sha256": profile.settings_projection_sha256,
            "hook_projection_ref": profile.hook_projection_ref,
            "hook_projection_sha256": profile.hook_projection_sha256,
        }
    raise ProviderRoleRunnerError(
        f"managed read-only role is unsupported for provider: {profile.provider}"
    )


def build_role_packet(
    context: ProjectContext,
    task_value: str | Path,
    *,
    role: str,
) -> tuple[dict, dict]:
    task_ref = resolve_task_ref(context, task_value)
    task = load_yaml(task_ref.yaml_path)
    provider_id = orchestrator_provider(task)
    provider = get_provider(provider_id)
    try:
        profile = provider.load_role_profile(context, role)
    except ValueError as error:
        raise ProviderRoleRunnerError(str(error)) from error
    packet = {
        "schema_version": 2,
        "project_root": str(context.project_root.resolve()),
        "task_id": task.get("id") or task_ref.id,
        "runtime": {"provider": provider_id},
        "requested_profile": _requested_profile(profile),
    }
    return packet, task


def _default_executor(provider_id: str):
    if provider_id == "codex":
        from providers.codex.managed_runtime import execute_managed_read_only

        return execute_managed_read_only
    if provider_id == "claude":
        from providers.claude.managed_runtime import execute_managed_read_only

        return execute_managed_read_only
    raise ProviderRoleRunnerError(
        f"managed read-only role is unsupported for provider: {provider_id}"
    )


def run_readonly_packet(
    context: ProjectContext,
    packet: dict,
    *,
    message: str,
    executor_factory: Callable[[str], Callable] | None = None,
) -> RoleRunResult:
    if not message.strip():
        raise ProviderRoleRunnerError("read-only role message must not be empty")
    provider_id = str((packet.get("runtime") or {}).get("provider") or "")
    if not provider_id:
        raise ProviderRoleRunnerError("frozen role packet has no runtime Provider")
    requested = packet.get("requested_profile") or {}
    role_id = str(requested.get("role_id") or requested.get("agent") or "")
    if not role_id:
        raise ProviderRoleRunnerError("frozen role packet has no requested role")
    executor = (executor_factory or _default_executor)(provider_id)
    try:
        output, attestation, evidence = executor(
            context,
            packet,
            message=message,
        )
        normalized = validate_provider_attestation(packet, attestation)
    except (ValueError, RuntimeError, OSError) as error:
        raise ProviderRoleRunnerError(str(error)) from error
    if normalized.provider != provider_id or normalized.role_id != role_id:
        raise ProviderRoleRunnerError(
            "normalized runtime evidence does not match the frozen Provider role"
        )
    execution = attestation.get("execution") or {}
    session_ref = str(execution.get("session_ref") or normalized.raw_evidence_ref or "")
    if not session_ref:
        raise ProviderRoleRunnerError("managed read-only role returned no attested session reference")
    return RoleRunResult(
        provider=provider_id,
        role_id=role_id,
        output=output,
        packet=packet,
        attestation=attestation,
        evidence=evidence,
        session_ref=session_ref,
    )


def run_readonly_role(
    context: ProjectContext,
    task_value: str | Path,
    *,
    role: str,
    message: str,
    executor_factory: Callable[[str], Callable] | None = None,
) -> RoleRunResult:
    packet, _ = build_role_packet(context, task_value, role=role)
    return run_readonly_packet(
        context,
        packet,
        message=message,
        executor_factory=executor_factory,
    )
