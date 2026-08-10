"""Strict validation and normalization for Claude runtime evidence."""

from __future__ import annotations

import re

from core.provider_contract import RuntimeContract, RuntimeEvidence


_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_TOOLS = {"Read", "Grep", "Glob"}
_INVALID_CONTINUITY = {
    "resume",
    "clear",
    "compact",
    "fork",
    "worktree",
    "nested-agent",
    "background",
}


def _model_matches(selector: str, resolved: str) -> bool:
    selector = selector.strip().lower()
    resolved = resolved.strip().lower()
    if selector in {"haiku", "sonnet", "opus"}:
        return bool(selector and selector in resolved)
    return bool(selector and selector == resolved)


def validate_claude_attestation(
    packet: dict,
    attestation: dict,
) -> RuntimeEvidence:
    if attestation.get("schema_version") != 1:
        raise ValueError("Claude runtime attestation schema_version must be 1")
    execution = attestation.get("execution") or {}
    observed = attestation.get("observed") or {}
    expected = packet.get("requested_profile") or {}
    evidence = attestation.get("evidence") or {}

    method = str(execution.get("method") or "")
    contracts = {
        "claude-managed-agent": {
            "collector": "claude-stream-hooks-transcript-v1",
            "source": "verified-claude-managed",
            "runtime_hashes": (
                "request_sha256",
                "command_sha256",
                "stream_sha256",
                "hook_events_sha256",
            ),
            "effort_binding": "verified-command",
            "needs_agent_id": False,
        },
        "claude-native-subagent": {
            "collector": "claude-hooks-transcript-v1",
            "source": "verified-claude-native",
            "runtime_hashes": (
                "request_sha256",
                "invocation_sha256",
                "transcript_sha256",
                "hook_events_sha256",
            ),
            "effort_binding": "verified-profile-and-contract",
            "needs_agent_id": True,
        },
    }
    contract = contracts.get(method)
    if contract is None:
        raise ValueError("Claude attestation has an unsupported execution method")
    if execution.get("collector") != contract["collector"]:
        raise ValueError("Claude attestation collector does not match execution method")
    if evidence.get("source") != contract["source"]:
        raise ValueError("Claude attestation evidence source does not match execution method")

    session_id = str(execution.get("session_id") or "")
    session_ref = str(execution.get("session_ref") or "")
    if not session_id or session_ref != f"claude-session:{session_id}":
        raise ValueError("Claude attestation has an invalid session binding")
    if contract["needs_agent_id"] and not str(execution.get("agent_id") or ""):
        raise ValueError("Claude native attestation is missing agent_id")

    checks = {
        "role_id": expected.get("role_id") or expected.get("agent"),
        "runtime_role": expected.get("runtime_role"),
        "model_grade": expected.get("model_grade") or expected.get("tier"),
        "model_selector": expected.get("model_selector") or expected.get("model"),
        "reasoning_effort": expected.get("reasoning_effort"),
    }
    mismatches = [
        key for key, value in checks.items() if observed.get(key) != value
    ]
    selector = str(checks["model_selector"] or "")
    resolved_model = str(observed.get("resolved_model") or "")
    if not _model_matches(selector, resolved_model):
        mismatches.append("resolved_model")
    if observed.get("reasoning_effort_binding") != contract["effort_binding"]:
        mismatches.append("reasoning_effort_binding")
    if observed.get("context_inheritance") != "none":
        mismatches.append("context_inheritance")
    if observed.get("write_isolation") != "tool-restricted":
        mismatches.append("write_isolation")
    if observed.get("persistent_context") != "disabled":
        mismatches.append("persistent_context")
    if set(observed.get("tools_advertised") or []) != _ALLOWED_TOOLS:
        mismatches.append("tools_advertised")
    if set(observed.get("tools_used") or []) - _ALLOWED_TOOLS:
        mismatches.append("tools_used")
    if observed.get("mcp_servers") not in ([], None):
        mismatches.append("mcp_servers")
    if set(observed.get("continuity_events") or []) & _INVALID_CONTINUITY:
        mismatches.append("continuity_events")
    if not str(observed.get("cwd") or ""):
        mismatches.append("cwd")

    frozen_hashes = (
        "profile_source_sha256",
        "model_config_sha256",
        "agent_projection_sha256",
        "settings_projection_sha256",
        "hook_projection_sha256",
    )
    for key in frozen_hashes:
        expected_hash = str(expected.get(key) or "")
        actual_hash = str(evidence.get(key) or "")
        if not _HEX_SHA256.fullmatch(expected_hash) or actual_hash != expected_hash:
            mismatches.append(key)
    for key in contract["runtime_hashes"]:
        if not _HEX_SHA256.fullmatch(str(evidence.get(key) or "")):
            mismatches.append(key)

    if mismatches:
        raise ValueError(
            "Claude runtime attestation mismatch: "
            + ", ".join(dict.fromkeys(mismatches))
        )
    return RuntimeEvidence(
        provider="claude",
        role_id=str(observed.get("role_id") or ""),
        contract=RuntimeContract(
            context_isolation="fresh",
            write_isolation="tool-restricted",
            persistent_context="disabled",
            attestation_strength="runtime-observed",
        ),
        raw_evidence_ref=session_ref,
    )
