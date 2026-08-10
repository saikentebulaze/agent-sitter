from __future__ import annotations


def requested_profile(profile) -> dict:
    value = {
        "role_id": profile.role_id,
        "runtime_role": profile.runtime_role,
        "model_grade": profile.tier,
        "model_selector": profile.model,
        "model_resolution_mode": getattr(profile, "model_resolution_mode", "native"),
        "expected_resolved_model": getattr(profile, "expected_resolved_model", ""),
        "proxy_provider": getattr(profile, "proxy_provider", ""),
        "reasoning_effort": profile.reasoning_effort,
    }
    for key in (
        "profile_source_sha256",
        "model_config_sha256",
        "agent_projection_sha256",
        "settings_projection_sha256",
        "hook_projection_sha256",
    ):
        value[key] = getattr(profile, key)
    return value


def claude_packet(profile, *, request_hash_context: bool = False) -> dict:
    packet = {
        "schema_version": 2,
        "runtime": {"provider": "claude"},
        "requested_profile": requested_profile(profile),
    }
    if request_hash_context:
        packet["project_root"] = "/test/project"
    return packet


def valid_claude_attestation(
    packet: dict,
    *,
    method: str = "claude-managed-agent",
    request_hash: str = "1" * 64,
    session_id: str = "session-test",
) -> dict:
    requested = packet["requested_profile"]
    managed = method == "claude-managed-agent"
    if not managed and method != "claude-native-subagent":
        raise ValueError(method)
    evidence = {
        "source": "verified-claude-managed-v2" if managed else "verified-claude-native-v2",
        "request_sha256": request_hash,
        "hook_events_sha256": "4" * 64,
    }
    if managed:
        evidence.update({"command_sha256": "2" * 64, "stream_sha256": "3" * 64})
    else:
        evidence.update({
            "invocation_sha256": "2" * 64,
            "parent_transcript_sha256": "3" * 64,
            "transcript_sha256": "5" * 64,
        })
    for key in (
        "profile_source_sha256",
        "model_config_sha256",
        "agent_projection_sha256",
        "settings_projection_sha256",
        "hook_projection_sha256",
    ):
        evidence[key] = requested[key]
    resolved = requested.get("expected_resolved_model") or requested["model_selector"]
    return {
        "schema_version": 2,
        "execution": {
            "method": method,
            "collector": (
                "claude-stream-hooks-transcript-v2"
                if managed
                else "claude-invocation-hooks-transcript-v2"
            ),
            "session_id": session_id,
            "session_ref": f"claude-session:{session_id}",
            **({} if managed else {"agent_id": "agent-one", "tool_use_id": "toolu-one"}),
        },
        "observed": {
            "role_id": requested["role_id"],
            "runtime_role": requested["runtime_role"],
            "model_grade": requested["model_grade"],
            "model_selector": requested["model_selector"],
            "model_resolution_mode": requested.get("model_resolution_mode") or "native",
            "expected_resolved_model": requested.get("expected_resolved_model") or "",
            "proxy_provider": requested.get("proxy_provider") or "",
            "resolved_model": resolved,
            "reasoning_effort": requested["reasoning_effort"],
            "reasoning_effort_binding": (
                "verified-command" if managed else "verified-profile-contract-and-invocation"
            ),
            "context_inheritance": "none",
            "write_isolation": "tool-restricted",
            "persistent_context": "disabled",
            "tools_configured": ["Read", "Grep", "Glob"],
            "tools_used": ["Read"],
            "mcp_configuration": "strict-empty-config" if managed else "frozen-agent-empty",
            "continuity_events": [],
            "cwd": "/test/project",
        },
        "evidence": evidence,
    }
