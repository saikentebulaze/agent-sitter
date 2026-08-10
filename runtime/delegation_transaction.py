"""Provider-aware delegation transaction facade.

The V5-A Codex transaction remains authoritative for legacy Codex Tasks. V5-B
routes other Task Providers through schema-v2 transactions while preserving the
existing public CLI and Python import paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import _delegation_transaction_impl as _impl
from _delegation_transaction_impl import *  # noqa: F401,F403

import provider_delegation_transaction as _provider_impl
from core.task_runtime import orchestrator_provider
from provider_attestation import validate_provider_attestation
from work_graph import load_yaml, valid_id


DelegationTransactionError = _impl.DelegationTransactionError


def _validate_attestation(packet: dict, attestation: dict):
    try:
        return validate_provider_attestation(packet, attestation)
    except (ValueError, RuntimeError) as error:
        raise DelegationTransactionError(str(error)) from error


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _schema_v2_packet(packet: dict, provider_id: str, profile) -> dict:
    result = copy.deepcopy(packet)
    result["schema_version"] = 2
    result["runtime"] = {"provider": provider_id}
    requested = {
        "schema_version": 2, "provider": provider_id, "agent": profile.role_id,
        "role_id": profile.role_id, "runtime_role": profile.runtime_role,
        "model": profile.model, "model_selector": profile.model,
        "tier": profile.tier, "model_grade": profile.tier,
        "model_resolution_mode": getattr(profile, "model_resolution_mode", "native"),
        "expected_resolved_model": getattr(profile, "expected_resolved_model", ""),
        "proxy_provider": getattr(profile, "proxy_provider", ""),
        "reasoning_effort": profile.reasoning_effort,
        "sandbox_mode": profile.write_isolation, "write_isolation": profile.write_isolation,
    }
    for key in (
        "profile_source_ref", "profile_source_sha256", "model_config_sha256",
        "agent_projection_ref", "agent_projection_sha256", "settings_projection_ref",
        "settings_projection_sha256", "hook_projection_ref", "hook_projection_sha256",
    ):
        value = getattr(profile, key, "")
        if value: requested[key] = value
    result["requested_profile"] = requested
    return result


def _provider_for_task(context, task_value) -> str:
    _, _, task = _impl._load_task(context, task_value)
    return orchestrator_provider(task)


def _verify_non_codex_request_hash(context, task_value, delegation_id, attestation_value) -> None:
    task_root, _, task = _impl._load_task(context, task_value)
    delegation_id = valid_id(str(delegation_id), "delegation_id")
    planned = _impl._entry_by_id(task, delegation_id)
    request_ref = str((planned.get("context") or {}).get("request_ref") or "")
    request_path = (context.project_root / request_ref).resolve()
    try: request_path.relative_to(task_root.resolve())
    except ValueError as error: raise DelegationTransactionError("delegation request is outside the task directory") from error
    packet = load_yaml(request_path)
    raw = Path(attestation_value)
    attestation_path = raw.resolve() if raw.is_absolute() else (context.project_root / raw).resolve()
    try: attestation_path.relative_to(context.project_root.resolve())
    except ValueError as error: raise DelegationTransactionError("delegation attestation is outside the project") from error
    attestation = load_yaml(attestation_path)
    actual = str((attestation.get("evidence") or {}).get("request_sha256") or "")
    expected = _canonical_sha256(packet)
    if actual != expected: raise DelegationTransactionError("runtime attestation request_sha256 does not match the frozen request")


_impl._validate_attestation = _validate_attestation
_provider_impl._schema_v2_packet = _schema_v2_packet


def authorize_delegation(context, task_value, **kwargs):
    if _provider_for_task(context, task_value) == "codex": return _impl.authorize_delegation(context, task_value, **kwargs)
    _provider_impl._schema_v2_packet = _schema_v2_packet
    try: return _provider_impl.authorize_delegation(context, task_value, **kwargs)
    except _provider_impl.ProviderDelegationTransactionError as error: raise DelegationTransactionError(str(error)) from error


def request_delegation(context, task_value, **kwargs):
    if _provider_for_task(context, task_value) == "codex": return _impl.request_delegation(context, task_value, **kwargs)
    _provider_impl._schema_v2_packet = _schema_v2_packet
    try: return _provider_impl.request_delegation(context, task_value, **kwargs)
    except _provider_impl.ProviderDelegationTransactionError as error: raise DelegationTransactionError(str(error)) from error


def supplement_delegation_context(context, task_value, delegation_id, **kwargs):
    if _provider_for_task(context, task_value) == "codex": return _impl.supplement_delegation_context(context, task_value, delegation_id, **kwargs)
    try: return _provider_impl.supplement_delegation_context(context, task_value, delegation_id, **kwargs)
    except _provider_impl.ProviderDelegationTransactionError as error: raise DelegationTransactionError(str(error)) from error


def record_delegation_result(context, task_value, delegation_id, **kwargs):
    if _provider_for_task(context, task_value) == "codex":
        _impl._validate_attestation = _validate_attestation
        return _impl.record_delegation_result(context, task_value, delegation_id, **kwargs)
    attestation = kwargs.get("attestation")
    if attestation is None: raise DelegationTransactionError("delegation attestation is required")
    _verify_non_codex_request_hash(context, task_value, delegation_id, attestation)
    try: return _provider_impl.record_delegation_result(context, task_value, delegation_id, **kwargs)
    except _provider_impl.ProviderDelegationTransactionError as error: raise DelegationTransactionError(str(error)) from error


__all__ = ["DelegationTransactionError", "_canonical_sha256", "_validate_attestation", "authorize_delegation", "close_delegation", "delegation_status", "record_delegation_result", "request_delegation", "supplement_delegation_context"]
