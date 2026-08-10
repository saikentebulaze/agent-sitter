"""Real Claude Code capability probes for configured Sitter model grades."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
from pathlib import Path
from typing import Callable

import yaml

from core.provider_registry import get_provider
from project_context import ProjectContext
from providers.claude.managed_runtime import (
    ClaudeManagedRuntimeError,
    claude_version,
    execute_managed_read_only,
)


_GRADE_ROLES = {
    "low": "source_locator",
    "medium": "framework_scout",
    "high": "deep_reviewer",
}


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _request_packet(context: ProjectContext, role: str) -> dict:
    profile = get_provider("claude").load_role_profile(context, role)
    requested = {
        "schema_version": 2,
        "provider": "claude",
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
        "model_resolution_mode": profile.model_resolution_mode,
        "expected_resolved_model": profile.expected_resolved_model,
        "proxy_provider": profile.proxy_provider,
    }
    for key in (
        "profile_source_ref",
        "profile_source_sha256",
        "model_config_sha256",
        "agent_projection_ref",
        "agent_projection_sha256",
        "settings_projection_ref",
        "settings_projection_sha256",
        "hook_projection_ref",
        "hook_projection_sha256",
    ):
        requested[key] = getattr(profile, key)
    return {
        "schema_version": 2,
        "runtime": {"provider": "claude"},
        "requested_profile": requested,
    }


def _cache_fingerprint(
    context: ProjectContext,
    version: str,
    packets: dict[str, dict],
) -> str:
    return _canonical_sha256(
        {
            "provider": "claude",
            "version": version,
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "project": str(context.project_root.resolve()),
            "profiles": {
                grade: packet["requested_profile"]
                for grade, packet in sorted(packets.items())
            },
        }
    )


def probe_managed(
    context: ProjectContext,
    *,
    command_prefix: tuple[str, ...] | None = None,
    executor: Callable[..., tuple[str, dict, dict]] = execute_managed_read_only,
    version_provider: Callable[[tuple[str, ...] | None], str] = claude_version,
    environment: dict[str, str] | None = None,
) -> dict:
    """Run one actual managed probe for each configured model grade."""

    version = version_provider(command_prefix)
    packets = {
        grade: _request_packet(context, role)
        for grade, role in _GRADE_ROLES.items()
    }
    report = {
        "schema_version": 1,
        "provider": "claude",
        "runtime_version": version,
        "system": platform.system(),
        "machine": platform.machine(),
        "cache_fingerprint": _cache_fingerprint(context, version, packets),
        "managed": {},
        "native": {
            "status": "manual-required",
            "reason": (
                "native support requires an interactive parent Agent invocation, "
                "Hook lifecycle, and child transcript; managed success is not reused"
            ),
        },
    }
    for grade, role in _GRADE_ROLES.items():
        packet = packets[grade]
        nonce = secrets.token_hex(16)
        message = (
            "This is a Sitter runtime capability probe. Return the exact token "
            f"{nonce} in the final answer. Do not infer or replace it."
        )
        profile = packet["requested_profile"]
        try:
            output, attestation, evidence = executor(
                context,
                packet,
                message=message,
                command_prefix=command_prefix,
                environment=environment,
            )
            if nonce not in output:
                raise ClaudeManagedRuntimeError(
                    "capability probe output did not contain the random canary"
                )
            observed = attestation.get("observed") or {}
            report["managed"][grade] = {
                "status": "supported",
                "role_id": role,
                "model_selector": profile["model_selector"],
                "model_resolution_mode": profile["model_resolution_mode"],
                "expected_resolved_model": profile["expected_resolved_model"],
                "proxy_provider": profile["proxy_provider"],
                "resolved_model": observed.get("resolved_model"),
                "reasoning_effort": observed.get("reasoning_effort"),
                "session_ref": (attestation.get("execution") or {}).get(
                    "session_ref"
                ),
                "request_sha256": (attestation.get("evidence") or {}).get(
                    "request_sha256"
                ),
                "raw_evidence_sha256": _canonical_sha256(evidence),
            }
        except (ClaudeManagedRuntimeError, OSError, ValueError) as error:
            report["managed"][grade] = {
                "status": "unsupported",
                "role_id": role,
                "model_selector": profile["model_selector"],
                "model_resolution_mode": profile["model_resolution_mode"],
                "expected_resolved_model": profile["expected_resolved_model"],
                "proxy_provider": profile["proxy_provider"],
                "error": str(error),
            }
    return report


def cache_path(context: ProjectContext) -> Path:
    return (
        context.project_root
        / ".harness"
        / "sitter.capabilities.local.yaml"
    )


def write_report(context: ProjectContext, report: dict) -> Path:
    path = cache_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        yaml.safe_dump(report, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_current_report(
    context: ProjectContext,
    *,
    command_prefix: tuple[str, ...] | None = None,
    version_provider: Callable[[tuple[str, ...] | None], str] = claude_version,
) -> dict | None:
    path = cache_path(context)
    if not path.is_file():
        return None
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return None
    version = version_provider(command_prefix)
    packets = {
        grade: _request_packet(context, role)
        for grade, role in _GRADE_ROLES.items()
    }
    expected = _cache_fingerprint(context, version, packets)
    return value if value.get("cache_fingerprint") == expected else None
