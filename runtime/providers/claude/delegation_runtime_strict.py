"""Strict native Claude delegation operations."""

from __future__ import annotations

from pathlib import Path

from project_context import ProjectContext
from providers.claude.delegation_runtime import (
    _write_runtime_artifacts,
    bind_scope_evidence,
    ensure_scope_policy,
    load_attempt,
    record_native_result,
)
from providers.claude.governed_session import launch_native_parent
from providers.claude.native_runtime_strict import collect_native, prepare_native
from work_graph import project_relative


def _contract_with_scope(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
    contract: dict,
) -> tuple[dict, Path, str, dict]:
    policy_path, digest, policy = ensure_scope_policy(
        context,
        request_path,
        packet,
    )
    scoped = dict(contract)
    scoped.update(
        {
            "scope_policy_ref": project_relative(context, policy_path),
            "scope_policy_path": str(policy_path.resolve()),
            "scope_policy_sha256": digest,
        }
    )
    return scoped, policy_path, digest, policy


def prepare_native_attempt(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, dict]:
    _, request_path, packet = load_attempt(
        context,
        task_value,
        delegation_id,
    )
    contract_path, contract = prepare_native(context, request_path, packet)
    scoped, _, _, _ = _contract_with_scope(
        context,
        request_path,
        packet,
        contract,
    )
    return contract_path, scoped


def launch_native_attempt(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> int:
    _, contract = prepare_native_attempt(
        context,
        task_value,
        delegation_id,
    )
    return launch_native_parent(context, contract)


def collect_native_attempt(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, Path, Path]:
    _, request_path, packet = load_attempt(
        context,
        task_value,
        delegation_id,
    )
    _, base_contract = prepare_native(context, request_path, packet)
    _, policy_path, digest, policy = _contract_with_scope(
        context,
        request_path,
        packet,
        base_contract,
    )
    output, attestation, evidence = collect_native(
        context,
        request_path,
        packet,
    )
    bind_scope_evidence(
        context,
        packet,
        policy_path=policy_path,
        policy_sha256=digest,
        policy=policy,
        attestation=attestation,
        evidence=evidence,
    )
    return _write_runtime_artifacts(
        request_path,
        packet,
        output=output,
        attestation=attestation,
        evidence=evidence,
    )


__all__ = [
    "collect_native_attempt",
    "launch_native_attempt",
    "prepare_native_attempt",
    "record_native_result",
]
