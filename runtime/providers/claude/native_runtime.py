"""Prepare and attest native Claude subagents from invocation and transcript evidence."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Iterable

import yaml

from core.provider_registry import get_provider
from project_context import ProjectContext
from providers.claude.managed_runtime import (
    _assert_frozen_profile,
    model_binding_matches,
)
from work_graph import project_relative


class ClaudeNativeRuntimeError(RuntimeError):
    pass


_ALLOWED_TOOLS = {"Read", "Grep", "Glob"}
_INVALID_EVENTS = {"PreCompact", "PostCompact", "WorktreeCreate"}


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attempt(packet: dict) -> int:
    value = int((packet.get("delegation") or {}).get("attempt") or 0)
    if value <= 0:
        raise ClaudeNativeRuntimeError(
            "delegation request has an invalid attempt"
        )
    return value


def contract_path(request_path: Path, packet: dict) -> Path:
    return request_path.parent / f"attempt-{_attempt(packet):02d}.native-contract.yaml"


def evidence_directory(request_path: Path, packet: dict) -> Path:
    return request_path.parent / f"attempt-{_attempt(packet):02d}.native-events"


def native_message(
    context: ProjectContext,
    request_path: Path,
    nonce: str,
) -> str:
    """Return the exact prompt that the governed parent must give the child."""

    return (
        f"Sitter_ATTEMPT_NONCE={nonce}\n\n"
        "Read and follow the frozen Sitter delegation request at:\n\n"
        f"{project_relative(context, request_path)}\n\n"
        "Do not use parent conversation history. Use only the role, tools, "
        "scope, and authority references frozen in that request. Return the "
        "required output or a structured NEED_CONTEXT response."
    )


def native_parent_instruction(
    *,
    runtime_role: str,
    model_selector: str,
    child_prompt: str,
) -> str:
    """Return a deterministic parent instruction for exactly one Agent call."""

    return (
        "Execute exactly one Agent tool call now and do not call any other tool.\n"
        f"Set subagent_type exactly to: {runtime_role}\n"
        f"Set model exactly to: {model_selector}\n"
        "Set run_in_background exactly to false.\n"
        "Pass the child prompt below byte-for-byte without adding, removing, "
        "summarizing, or rephrasing anything. After the Agent completes, "
        "return its final output and end.\n\n"
        "----- Sitter CHILD PROMPT BEGIN -----\n"
        f"{child_prompt}\n"
        "----- Sitter CHILD PROMPT END -----"
    )


def prepare_native(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
) -> tuple[Path, dict]:
    profile, paths = _assert_frozen_profile(context, packet)
    request_path = request_path.resolve()
    try:
        request_path.relative_to(context.project_root.resolve())
    except ValueError as error:
        raise ClaudeNativeRuntimeError(
            "native request is outside the project"
        ) from error

    nonce = uuid.uuid4().hex
    events = evidence_directory(request_path, packet).resolve()
    child_prompt = native_message(context, request_path, nonce)
    contract = {
        "schema_version": 2,
        "provider": "claude",
        "collector": "claude-invocation-hooks-transcript-v2",
        "created_at_ns": time.time_ns(),
        "attempt_nonce": nonce,
        "parent_session_id": str(uuid.uuid4()),
        "evidence_dir": str(events),
        "request_ref": project_relative(context, request_path),
        "request_sha256": _canonical_sha256(packet),
        "role_id": profile.role_id,
        "runtime_role": profile.runtime_role,
        "model_grade": profile.tier,
        "model_selector": profile.model,
        "model_resolution_mode": profile.model_resolution_mode,
        "expected_resolved_model": profile.expected_resolved_model,
        "proxy_provider": profile.proxy_provider,
        "reasoning_effort": profile.reasoning_effort,
        "governed_settings_ref": project_relative(
            context,
            paths["settings_projection_sha256"],
        ),
        "message": child_prompt,
        "parent_instruction": native_parent_instruction(
            runtime_role=profile.runtime_role,
            model_selector=profile.model,
            child_prompt=child_prompt,
        ),
    }

    path = contract_path(request_path, packet)
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        stable_existing = dict(existing or {})
        stable_contract = dict(contract)
        dynamic = (
            "created_at_ns",
            "attempt_nonce",
            "parent_session_id",
            "evidence_dir",
            "message",
            "parent_instruction",
        )
        for value in (stable_existing, stable_contract):
            for key in dynamic:
                value.pop(key, None)
        if stable_existing == stable_contract:
            return path, existing
        raise ClaudeNativeRuntimeError(
            f"conflicting native contract already exists: {path}"
        )

    events.mkdir(parents=True, exist_ok=False)
    path.write_text(
        yaml.safe_dump(contract, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path, contract


def _event_envelopes(directory: Path, contract: dict) -> list[dict]:
    if not directory.is_dir():
        raise ClaudeNativeRuntimeError(
            f"native evidence directory is missing: {directory}"
        )
    values: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ClaudeNativeRuntimeError(
                f"invalid native Hook event: {path}"
            ) from error
        if not isinstance(envelope, dict):
            raise ClaudeNativeRuntimeError(
                f"native Hook event is not a mapping: {path}"
            )
        if envelope.get("attempt_nonce") != contract.get("attempt_nonce"):
            raise ClaudeNativeRuntimeError(
                f"native Hook event has the wrong attempt nonce: {path}"
            )
        if envelope.get("execution_mode") != "native":
            raise ClaudeNativeRuntimeError(
                f"native Hook event has the wrong execution mode: {path}"
            )
        if int(envelope.get("recorded_at_ns") or 0) < int(
            contract.get("created_at_ns") or 0
        ):
            raise ClaudeNativeRuntimeError(
                f"native Hook event predates the contract: {path}"
            )
        event = envelope.get("event")
        if not isinstance(event, dict):
            raise ClaudeNativeRuntimeError(
                f"native Hook event has no event mapping: {path}"
            )
        values.append(event)
    if not values:
        raise ClaudeNativeRuntimeError(
            "native execution produced no Hook evidence"
        )
    return values


def _event_values(
    events: list[dict],
    name: str,
    *,
    tool: str | None = None,
) -> list[dict]:
    return [
        event
        for event in events
        if event.get("hook_event_name") == name
        and (tool is None or event.get("tool_name") == tool)
    ]


def _single(values: list[dict], label: str) -> dict:
    if len(values) != 1:
        raise ClaudeNativeRuntimeError(
            f"expected exactly one {label}, found {len(values)}"
        )
    return values[0]


_PROMPT_BEGIN = "----- Sitter CHILD PROMPT BEGIN -----\n"
_PROMPT_END = "\n----- Sitter CHILD PROMPT END -----"


def _model_identity(value: str) -> str:
    """Normalize proxy model reporting forms into one identity.

    The DeepSeek proxy reports the same model as "deepseek-v4-flash" in the
    child transcript and "deepseek-v4-flash[1m]" / "deepseek-v4-flash[1M]"
    in parent results depending on the event source; the bracketed context
    window suffix is a reporting annotation, not a different model.
    """
    return re.sub(r"\[[^\]]*\]", "", value).strip().lower()


def _strip_prompt_markers(value: str) -> str:
    """Remove the harness markers embedded in the parent instruction.

    The frozen parent instruction wraps the child prompt in BEGIN/END
    markers so the governed parent can identify its exact boundaries and
    passes that wrapped text byte-for-byte as the Agent prompt. The marker
    text is harness-injected scaffolding, not part of the frozen message,
    so the binder strips it before comparing to the contract message.
    """
    if value.startswith(_PROMPT_BEGIN) and value.endswith(_PROMPT_END):
        return value[len(_PROMPT_BEGIN) : -len(_PROMPT_END)]
    return value


def _bind_invocation(
    events: list[dict],
    contract: dict,
) -> tuple[dict, dict, dict, dict]:
    expected_prompt = str(contract.get("message") or "")
    expected_role = str(contract.get("runtime_role") or "")
    pres = [
        event
        for event in _event_values(events, "PreToolUse", tool="Agent")
        if _strip_prompt_markers(
            str((event.get("tool_input") or {}).get("prompt") or "")
        )
        == expected_prompt
        and str(
            (event.get("tool_input") or {}).get("subagent_type") or ""
        )
        == expected_role
    ]
    pre = _single(pres, "matching parent PreToolUse(Agent)")
    tool_use_id = str(pre.get("tool_use_id") or "")
    if not tool_use_id:
        raise ClaudeNativeRuntimeError(
            "parent Agent invocation has no tool_use_id"
        )

    tool_input = pre.get("tool_input") or {}
    requested_model = str(tool_input.get("model") or "")
    if requested_model and requested_model != str(
        contract.get("model_selector") or ""
    ):
        raise ClaudeNativeRuntimeError(
            "parent Agent invocation overrides the frozen model selector"
        )
    # Claude Code defaults an omitted run_in_background to foreground; only an
    # explicit truthy background value violates the contract. Foregroundness is
    # additionally proven by SubagentStop firing and PostToolUse status.
    if tool_input.get("run_in_background") not in (None, False, "false", 0):
        raise ClaudeNativeRuntimeError(
            "parent Agent invocation is not explicitly foreground"
        )

    posts = [
        event
        for event in _event_values(events, "PostToolUse", tool="Agent")
        if str(event.get("tool_use_id") or "") == tool_use_id
    ]
    post = _single(posts, "matching parent PostToolUse(Agent)")
    response = post.get("tool_response") or {}
    if not isinstance(response, dict) or response.get("status") != "completed":
        raise ClaudeNativeRuntimeError(
            "native Agent was not completed in the foreground"
        )
    agent_id = str(response.get("agentId") or "")
    if not agent_id:
        raise ClaudeNativeRuntimeError(
            "parent Agent result has no agentId"
        )
    models_used = [
        str(value)
        for value in response.get("modelsUsed") or []
        if str(value)
    ]
    if len(set(models_used)) > 1:
        raise ClaudeNativeRuntimeError(
            "native Agent changed models during execution"
        )

    starts = [
        event
        for event in _event_values(events, "SubagentStart")
        if str(event.get("agent_id") or event.get("agentId") or "")
        == agent_id
        and str(event.get("agent_type") or event.get("agentType") or "")
        == expected_role
    ]
    start = _single(starts, "matching SubagentStart")
    stops = [
        event
        for event in _event_values(events, "SubagentStop")
        if str(event.get("agent_id") or event.get("agentId") or "")
        == agent_id
        and str(event.get("agent_type") or event.get("agentType") or "")
        == expected_role
    ]
    stop = _single(stops, "matching SubagentStop")
    if [
        event
        for event in _event_values(events, "SubagentStart")
        if event is not start
    ]:
        raise ClaudeNativeRuntimeError(
            "native attempt spawned an additional or nested Agent"
        )
    return pre, post, start, stop


def _safe_transcript(path_value: object, label: str) -> Path:
    path = Path(str(path_value or "")).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise ClaudeNativeRuntimeError(
            f"{label} is missing or unsafe: {path}"
        )
    return path


def _transcript_records(path: Path) -> list[dict]:
    values: list[dict] = []
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ClaudeNativeRuntimeError(
                    f"native transcript has invalid JSON at line {number}"
                ) from error
            if not isinstance(value, dict):
                raise ClaudeNativeRuntimeError(
                    f"native transcript line {number} is not a mapping"
                )
            values.append(value)
    if not values:
        raise ClaudeNativeRuntimeError("native transcript is empty")
    return values


def _walk(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _child_observation(records: list[dict]) -> dict:
    session_ids: set[str] = set()
    agent_ids: set[str] = set()
    cwd_values: set[str] = set()
    models: list[str] = []
    tools: list[str] = []
    texts: list[str] = []

    for record in records:
        if record.get("sessionId"):
            session_ids.add(str(record["sessionId"]))
        if record.get("agentId"):
            agent_ids.add(str(record["agentId"]))
        if record.get("cwd"):
            cwd_values.add(str(Path(str(record["cwd"])).resolve()))
        message = record.get("message")
        if isinstance(message, dict) and message.get("model"):
            models.append(str(message["model"]))
        if record.get("type") == "assistant" and isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") in {"tool_use", "tool_call"}:
                        name = str(
                            item.get("name")
                            or item.get("tool_name")
                            or ""
                        )
                        if name:
                            tools.append(name)
                    if (
                        item.get("type") == "text"
                        and str(item.get("text") or "").strip()
                    ):
                        texts.append(str(item["text"]).strip())

    if any(
        str(record.get("subtype") or "")
        in {"compact", "compact_boundary"}
        for record in records
    ):
        raise ClaudeNativeRuntimeError(
            "child transcript contains a compaction boundary"
        )
    if len(session_ids) != 1:
        raise ClaudeNativeRuntimeError(
            "child transcript must share one session ID, "
            f"found {len(session_ids)}"
        )
    if len(cwd_values) != 1:
        raise ClaudeNativeRuntimeError(
            f"child transcript must share one cwd, found {len(cwd_values)}"
        )
    unique_models = list(dict.fromkeys(models))
    if len(unique_models) != 1:
        raise ClaudeNativeRuntimeError(
            "child transcript must share one model, "
            f"found {len(unique_models)}"
        )
    if not texts:
        raise ClaudeNativeRuntimeError(
            "child transcript has no final assistant message"
        )
    return {
        "session_id": next(iter(session_ids)),
        "agent_ids": agent_ids,
        "cwd": next(iter(cwd_values)),
        "model": unique_models[0],
        "tools_used": list(dict.fromkeys(tools)),
        "final": texts[-1],
    }


def _configured_agent(
    context: ProjectContext,
    profile,
) -> tuple[set[str], list]:
    path = context.project_root / str(profile.agent_projection_ref)
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ClaudeNativeRuntimeError(
            "governed Agent projection has no YAML frontmatter"
        )
    closing = text.find("\n---\n", 4)
    data = yaml.safe_load(text[4:closing]) if closing >= 0 else None
    if not isinstance(data, dict):
        raise ClaudeNativeRuntimeError(
            "governed Agent projection frontmatter is invalid"
        )
    tools = {
        value.strip()
        for value in str(data.get("tools") or "").split(",")
        if value.strip()
    }
    mcp = data.get("mcpServers")
    configured_mcp = (
        list(mcp)
        if isinstance(mcp, list)
        else ([] if mcp in (None, {}) else [mcp])
    )
    return tools, configured_mcp


def collect_native(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
) -> tuple[str, dict, dict]:
    profile, _ = _assert_frozen_profile(context, packet)
    path = contract_path(request_path, packet)
    if not path.is_file():
        raise ClaudeNativeRuntimeError(
            "native execution contract is missing; run prepare first"
        )
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("schema_version") != 2:
        raise ClaudeNativeRuntimeError(
            "native execution contract is invalid"
        )
    if contract.get("request_sha256") != _canonical_sha256(packet):
        raise ClaudeNativeRuntimeError(
            "native contract request hash differs from the frozen request"
        )

    events = _event_envelopes(
        Path(str(contract["evidence_dir"])),
        contract,
    )
    pre, post, start, stop = _bind_invocation(events, contract)
    response = post["tool_response"]
    agent_id = str(response["agentId"])

    parent_paths = {
        str(value)
        for value in (
            pre.get("transcript_path"),
            post.get("transcript_path"),
            start.get("transcript_path"),
            stop.get("transcript_path"),
        )
        if value
    }
    if len(parent_paths) != 1:
        raise ClaudeNativeRuntimeError(
            "native lifecycle does not share one parent transcript"
        )
    parent_transcript = _safe_transcript(
        next(iter(parent_paths)),
        "parent transcript",
    )
    child_transcript = _safe_transcript(
        stop.get("agent_transcript_path")
        or stop.get("agentTranscriptPath"),
        "child transcript",
    )
    if parent_transcript == child_transcript:
        raise ClaudeNativeRuntimeError(
            "parent and child transcript paths must differ"
        )

    child_records = _transcript_records(child_transcript)
    child = _child_observation(child_records)
    if child["agent_ids"] and child["agent_ids"] != {agent_id}:
        raise ClaudeNativeRuntimeError(
            "child transcript contains another Agent identity"
        )

    parent_session_ids = {
        str(value)
        for value in (
            pre.get("session_id"),
            post.get("session_id"),
            start.get("session_id"),
            stop.get("session_id"),
        )
        if value
    }
    frozen_parent_session = str(contract.get("parent_session_id"))
    if parent_session_ids != {frozen_parent_session}:
        raise ClaudeNativeRuntimeError(
            "native lifecycle does not match the frozen parent session"
        )
    if child["session_id"] != frozen_parent_session:
        raise ClaudeNativeRuntimeError(
            "child transcript does not match the frozen parent session"
        )
    if Path(child["cwd"]).resolve() != context.project_root.resolve():
        raise ClaudeNativeRuntimeError(
            "native Claude Agent used the wrong working directory"
        )

    resolved_model = str(response.get("resolvedModel") or child["model"])
    if (
        str(response.get("resolvedModel") or "")
        and _model_identity(str(response["resolvedModel"]))
        != _model_identity(child["model"])
    ):
        raise ClaudeNativeRuntimeError(
            "parent result and child transcript disagree on resolved model"
        )
    model_ok, mapping_source = model_binding_matches(
        profile.model,
        resolved_model,
        resolution_mode=profile.model_resolution_mode,
        expected_resolved_model=profile.expected_resolved_model,
        proxy_provider=profile.proxy_provider,
    )
    if not model_ok:
        raise ClaudeNativeRuntimeError(
            "native resolved model differs from the frozen resolution policy: "
            f"{profile.model} -> {resolved_model}"
        )

    configured_tools, configured_mcp = _configured_agent(context, profile)
    if configured_tools != _ALLOWED_TOOLS or configured_mcp:
        raise ClaudeNativeRuntimeError(
            "governed Agent configuration is broader than the read-only contract"
        )
    tools_used = child["tools_used"]
    forbidden = set(tools_used) - _ALLOWED_TOOLS
    if forbidden:
        raise ClaudeNativeRuntimeError(
            "native Claude Agent used forbidden tools: "
            + ", ".join(sorted(forbidden))
        )
    if "Agent" in tools_used:
        raise ClaudeNativeRuntimeError(
            "native Claude Agent spawned a nested Agent"
        )

    for event in events:
        name = str(event.get("hook_event_name") or "")
        event_agent = str(
            event.get("agent_id") or event.get("agentId") or ""
        )
        if name in _INVALID_EVENTS and event_agent == agent_id:
            raise ClaudeNativeRuntimeError(
                f"native Claude Agent violated lifecycle contract: {name}"
            )
        if name == "PreToolUse" and event_agent == agent_id:
            tool = str(event.get("tool_name") or "")
            if tool not in _ALLOWED_TOOLS:
                raise ClaudeNativeRuntimeError(
                    f"native child Hook observed forbidden tool: {tool}"
                )

    final = child["final"]
    stop_message = str(
        stop.get("last_assistant_message")
        or stop.get("lastAssistantMessage")
        or ""
    ).strip()
    if not stop_message or stop_message != final:
        raise ClaudeNativeRuntimeError(
            "SubagentStop final message differs from the child transcript"
        )

    requested = packet["requested_profile"]
    invocation = {
        "attempt_nonce": contract["attempt_nonce"],
        "tool_use_id": pre["tool_use_id"],
        "agent_id": agent_id,
        "prompt": (pre.get("tool_input") or {}).get("prompt"),
        "subagent_type": (pre.get("tool_input") or {}).get(
            "subagent_type"
        ),
        "requested_model": (pre.get("tool_input") or {}).get("model"),
        "status": response.get("status"),
        "resolved_model": response.get("resolvedModel"),
    }
    evidence = {
        "source": "verified-claude-native-v2",
        "profile_source_sha256": requested["profile_source_sha256"],
        "model_config_sha256": requested["model_config_sha256"],
        "agent_projection_sha256": requested["agent_projection_sha256"],
        "settings_projection_sha256": requested[
            "settings_projection_sha256"
        ],
        "hook_projection_sha256": requested["hook_projection_sha256"],
        "request_sha256": _canonical_sha256(packet),
        "invocation_sha256": _canonical_sha256(invocation),
        "parent_transcript_sha256": _file_sha256(parent_transcript),
        "transcript_sha256": _file_sha256(child_transcript),
        "hook_events_sha256": _canonical_sha256(events),
    }
    session_id = frozen_parent_session
    attestation = {
        "schema_version": 2,
        "execution": {
            "method": "claude-native-subagent",
            "collector": "claude-invocation-hooks-transcript-v2",
            "session_id": session_id,
            "session_ref": f"claude-session:{session_id}",
            "agent_id": agent_id,
            "tool_use_id": str(pre["tool_use_id"]),
        },
        "observed": {
            "role_id": profile.role_id,
            "runtime_role": profile.runtime_role,
            "model_grade": profile.tier,
            "model_selector": profile.model,
            "model_resolution_mode": profile.model_resolution_mode,
            "expected_resolved_model": profile.expected_resolved_model,
            "proxy_provider": profile.proxy_provider,
            "resolved_model": resolved_model,
            "model_mapping_source": mapping_source,
            "reasoning_effort": profile.reasoning_effort,
            "reasoning_effort_binding": (
                "verified-profile-contract-and-invocation"
            ),
            "context_inheritance": "none",
            "write_isolation": "tool-restricted",
            "persistent_context": "disabled",
            "tools_configured": sorted(configured_tools),
            "tools_used": tools_used,
            "mcp_configuration": "frozen-agent-empty",
            "continuity_events": [],
            "cwd": child["cwd"],
        },
        "evidence": evidence,
    }
    raw = {
        "schema_version": 2,
        "agent_id": agent_id,
        "contract": contract,
        "invocation": invocation,
        "hook_events": events,
        "parent_transcript_ref": str(parent_transcript),
        "child_transcript_ref": str(child_transcript),
        "child_transcript": child_records,
    }
    get_provider("claude").validate_attestation(packet, attestation)
    return final, attestation, raw
