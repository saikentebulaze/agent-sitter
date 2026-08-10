"""Additional invariants applied to collected native Claude evidence."""

from __future__ import annotations

from pathlib import Path

from core.provider_registry import get_provider
from project_context import ProjectContext
from providers.claude.native_runtime import (
    ClaudeNativeRuntimeError,
    collect_native as collect_native_base,
    prepare_native,
)


def _agent_id(event: dict) -> str:
    return str(event.get("agent_id") or event.get("agentId") or "")


def collect_native(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
) -> tuple[str, dict, dict]:
    """Collect native evidence and reject cross-agent or invocation leakage."""

    output, attestation, raw = collect_native_base(
        context,
        request_path,
        packet,
    )
    observed = attestation.get("observed") or {}
    actual_cwd = str(observed.get("cwd") or "")
    if not actual_cwd or Path(actual_cwd).resolve() != context.project_root.resolve():
        raise ClaudeNativeRuntimeError(
            "native Claude Agent used the wrong working directory"
        )

    invocation = raw.get("invocation") or {}
    requested_model = str(invocation.get("requested_model") or "")
    frozen_model = str(observed.get("model_selector") or "")
    if not frozen_model or requested_model != frozen_model:
        raise ClaudeNativeRuntimeError(
            "native parent invocation did not explicitly request the frozen model selector"
        )

    events = raw.get("hook_events") or []
    starts = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("hook_event_name") == "SubagentStart"
    ]
    if len(starts) != 1:
        raise ClaudeNativeRuntimeError(
            "native Hook evidence must contain exactly one SubagentStart"
        )
    primary_agent = str(raw.get("agent_id") or "")
    event_agents = {
        value
        for value in (
            _agent_id(event)
            for event in events
            if isinstance(event, dict)
        )
        if value
    }
    if not primary_agent or event_agents != {primary_agent}:
        raise ClaudeNativeRuntimeError(
            "native Hook evidence contains another Agent identity"
        )

    get_provider("claude").validate_attestation(packet, attestation)
    return output, attestation, raw


__all__ = [
    "ClaudeNativeRuntimeError",
    "collect_native",
    "prepare_native",
]
