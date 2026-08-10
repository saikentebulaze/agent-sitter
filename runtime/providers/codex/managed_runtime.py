from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, Callable

from agent_profiles import AgentProfile, MODEL_TIERS, load_agent_profile
from artifact_consistency import file_sha256
from codex_app_server import CodexAppServerClient, CodexAppServerError
from codex_runtime_attestation import (
    CodexRuntimeAttestationError,
    _normalize_sandbox_type,
    codex_version,
)
from project_context import ProjectContext


class CodexManagedRuntimeError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _profile_instructions(profile: AgentProfile) -> str:
    if not profile.source.is_file():
        raise CodexManagedRuntimeError(
            f"agent profile is missing: {profile.source}"
        )
    with profile.source.open("rb") as stream:
        data = tomllib.load(stream)
    instructions = str(data.get("developer_instructions") or "").strip()
    if not instructions:
        raise CodexManagedRuntimeError(
            f"agent profile has no developer instructions: {profile.name}"
        )
    return instructions


def _assert_requested_profile(packet: dict, profile: AgentProfile) -> None:
    expected = packet.get("requested_profile") or {}
    checks = {
        "agent": profile.name,
        "model": profile.model,
        "tier": profile.tier,
        "reasoning_effort": profile.reasoning_effort,
        "sandbox_mode": profile.sandbox_mode,
    }
    mismatches = [
        key for key, value in checks.items() if expected.get(key) != value
    ]
    if mismatches:
        raise CodexManagedRuntimeError(
            "current Agent TOML differs from the frozen request: "
            + ", ".join(mismatches)
        )


def _result_mapping(response: dict[str, Any], method: str) -> dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, dict):
        raise CodexManagedRuntimeError(
            f"Codex App Server {method} returned no result mapping"
        )
    return result


def _sandbox_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"type": value}


def _turn_agent_text(turn: dict[str, Any]) -> str:
    values: list[str] = []
    for item in turn.get("items") or []:
        if not isinstance(item, dict) or item.get("type") != "agentMessage":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            values.append(text)
    return "\n\n".join(values).strip()


def _find_turn(thread: dict[str, Any], turn_id: str) -> dict[str, Any] | None:
    for turn in thread.get("turns") or []:
        if isinstance(turn, dict) and turn.get("id") == turn_id:
            return turn
    return None


def _validate_start_and_resume(
    *,
    context: ProjectContext,
    profile: AgentProfile,
    thread_start: dict[str, Any],
    thread_resume: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    start_thread = thread_start.get("thread") or {}
    resume_thread = thread_resume.get("thread") or {}
    if not isinstance(start_thread, dict) or not isinstance(resume_thread, dict):
        raise CodexManagedRuntimeError("managed thread metadata is missing")
    start_id = str(start_thread.get("id") or "")
    resume_id = str(resume_thread.get("id") or "")
    if not start_id or start_id != resume_id:
        raise CodexManagedRuntimeError(
            "thread/start and thread/resume returned different thread IDs"
        )

    expected_cwd = context.project_root.resolve()
    mismatches: list[str] = []
    if str(thread_start.get("model") or "") != profile.model:
        mismatches.append("thread/start model")
    if str(thread_resume.get("model") or "") != profile.model:
        mismatches.append("thread/resume model")
    if str(thread_resume.get("reasoningEffort") or "") != profile.reasoning_effort:
        mismatches.append("reasoning effort")
    start_sandbox = _sandbox_mapping(thread_start.get("sandbox"))
    resume_sandbox = _sandbox_mapping(thread_resume.get("sandbox"))
    if _normalize_sandbox_type(start_sandbox.get("type")) != "read-only":
        mismatches.append("thread/start sandbox")
    if _normalize_sandbox_type(resume_sandbox.get("type")) != "read-only":
        mismatches.append("thread/resume sandbox")
    for label, value in (
        ("thread/start cwd", thread_start.get("cwd")),
        ("thread/resume cwd", thread_resume.get("cwd")),
    ):
        if not value or Path(str(value)).resolve() != expected_cwd:
            mismatches.append(label)
    if start_thread.get("parentThreadId") is not None:
        mismatches.append("parentThreadId")
    if start_thread.get("forkedFromId") is not None:
        mismatches.append("forkedFromId")
    if mismatches:
        raise CodexManagedRuntimeError(
            "managed read-only runtime mismatch: "
            + ", ".join(mismatches)
        )
    return start_sandbox, resume_sandbox


def execute_managed_read_only(
    context: ProjectContext,
    packet: dict,
    *,
    message: str,
    client_factory: Callable[[], CodexAppServerClient] | None = None,
    version_provider: Callable[[], str] = codex_version,
    timeout: float = 900.0,
) -> tuple[str, dict, dict]:
    requested = packet.get("requested_profile") or {}
    role = str(requested.get("agent") or "")
    if not role:
        raise CodexManagedRuntimeError("delegation request has no Agent role")
    profile = load_agent_profile(context, role)
    _assert_requested_profile(packet, profile)
    if profile.sandbox_mode != "read-only":
        raise CodexManagedRuntimeError(
            "managed execution only supports read-only Agent profiles"
        )
    instructions = _profile_instructions(profile)
    project_root = str(context.project_root.resolve())

    thread_start_params = {
        "model": profile.model,
        "cwd": project_root,
        "developerInstructions": instructions,
        "sandbox": "read-only",
        "approvalPolicy": "never",
        "runtimeWorkspaceRoots": [project_root],
        "ephemeral": False,
        "historyMode": "paginated",
        "threadSource": "sitter-harness-delegation",
    }
    turn_start_template = {
        "input": [{"type": "text", "text": message}],
        "model": profile.model,
        "effort": profile.reasoning_effort,
        "cwd": project_root,
        "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        "approvalPolicy": "never",
        "runtimeWorkspaceRoots": [project_root],
    }
    factory = client_factory or (
        lambda: CodexAppServerClient(
            client_name="sitter-harness-managed-delegation",
            timeout=60.0,
        )
    )
    try:
        with factory() as client:
            thread_start_response = client.request(
                "thread/start",
                thread_start_params,
                timeout=60.0,
            )
            thread_start = _result_mapping(
                thread_start_response,
                "thread/start",
            )
            thread = thread_start.get("thread") or {}
            thread_id = str(thread.get("id") or "")
            if not thread_id:
                raise CodexManagedRuntimeError(
                    "thread/start returned no thread ID"
                )
            turn_start_params = {
                "threadId": thread_id,
                **turn_start_template,
            }
            turn_start_response = client.request(
                "turn/start",
                turn_start_params,
                timeout=60.0,
            )
            turn_start = _result_mapping(
                turn_start_response,
                "turn/start",
            )
            turn_id = str((turn_start.get("turn") or {}).get("id") or "")
            if not turn_id:
                raise CodexManagedRuntimeError(
                    "turn/start returned no turn ID"
                )
            completed_notification = client.wait_for_notification(
                "turn/completed",
                predicate=lambda params: (
                    params.get("threadId") == thread_id
                    and (params.get("turn") or {}).get("id") == turn_id
                ),
                timeout=timeout,
            )
            completed_params = completed_notification.get("params") or {}
            completed_turn = completed_params.get("turn") or {}
            if completed_turn.get("status") != "completed":
                raise CodexManagedRuntimeError(
                    "managed Codex turn did not complete successfully: "
                    + json.dumps(completed_turn.get("error"), ensure_ascii=False)
                )
            output = _turn_agent_text(completed_turn)
            if not output:
                read_response = client.request(
                    "thread/read",
                    {"threadId": thread_id, "includeTurns": True},
                    timeout=60.0,
                )
                read_result = _result_mapping(read_response, "thread/read")
                loaded_turn = _find_turn(
                    read_result.get("thread") or {},
                    turn_id,
                )
                if loaded_turn is not None:
                    output = _turn_agent_text(loaded_turn)
            if not output:
                raise CodexManagedRuntimeError(
                    "managed Codex turn returned no final Agent message"
                )
            resume_response = client.request(
                "thread/resume",
                {"threadId": thread_id, "excludeTurns": True},
                timeout=60.0,
            )
            thread_resume = _result_mapping(
                resume_response,
                "thread/resume",
            )
            raw_messages = client.raw_messages
            app_stderr = client.stderr
    except (CodexAppServerError, OSError) as error:
        raise CodexManagedRuntimeError(str(error)) from error

    start_sandbox, resume_sandbox = _validate_start_and_resume(
        context=context,
        profile=profile,
        thread_start=thread_start,
        thread_resume=thread_resume,
    )
    resumed_thread = thread_resume.get("thread") or {}
    profile_ref = profile.source.relative_to(context.package_root).as_posix()
    profile_hash = file_sha256(profile.source)
    instructions_hash = _text_sha256(instructions)
    observed = {
        "agent": profile.name,
        "agent_binding": "verified-thread-start-profile",
        "model": str(thread_resume.get("model") or ""),
        "tier": MODEL_TIERS.get(str(thread_resume.get("model") or "")),
        "reasoning_effort": thread_resume.get("reasoningEffort"),
        "sandbox_mode": _normalize_sandbox_type(resume_sandbox.get("type")),
        "sandbox": resume_sandbox,
        "thread_start_sandbox": start_sandbox,
        "active_permission_profile": thread_resume.get(
            "activePermissionProfile"
        ),
        "context_inheritance": "none",
        "child_thread_id": str(resumed_thread.get("id") or ""),
        "parent_thread_id": resumed_thread.get("parentThreadId"),
        "forked_from_id": resumed_thread.get("forkedFromId"),
        "cwd": thread_resume.get("cwd") or resumed_thread.get("cwd"),
        "runtime_workspace_roots": (
            thread_resume.get("runtimeWorkspaceRoots") or []
        ),
        "instruction_sources": thread_resume.get("instructionSources") or [],
    }
    attestation = {
        "schema_version": 2,
        "execution": {
            "method": "app-server-isolated-agent",
            "collector": "codex-app-server-managed-v1",
            "codex_version": version_provider(),
            "session_ref": f"app-server-thread:{observed['child_thread_id']}",
            "thread_id": observed["child_thread_id"],
            "turn_id": turn_id,
        },
        "observed": observed,
        "evidence": {
            "source": "verified-app-server-managed",
            "agent_profile_ref": profile_ref,
            "agent_profile_sha256": profile_hash,
            "developer_instructions_sha256": instructions_hash,
            "thread_start_request_sha256": _canonical_sha256(
                thread_start_params
            ),
            "turn_start_request_sha256": _canonical_sha256(
                turn_start_params
            ),
        },
    }
    evidence = {
        "schema_version": 1,
        "execution": "app-server-isolated-agent",
        "agent_profile": {
            "ref": profile_ref,
            "sha256": profile_hash,
            "developer_instructions_sha256": instructions_hash,
        },
        "thread_start_params": thread_start_params,
        "thread_start_response": thread_start,
        "turn_start_params": turn_start_params,
        "turn_start_response": turn_start,
        "turn_completed": completed_params,
        "thread_resume_response": thread_resume,
        "app_server_raw": raw_messages,
        "app_server_stderr": app_stderr,
        "requested_profile": requested,
    }
    validate_managed_attestation(context, packet, attestation)
    return output, attestation, evidence


def validate_managed_attestation(
    context: ProjectContext,
    packet: dict,
    attestation: dict,
) -> None:
    execution = attestation.get("execution") or {}
    observed = attestation.get("observed") or {}
    evidence = attestation.get("evidence") or {}
    expected = packet.get("requested_profile") or {}
    mismatches: list[str] = []
    if attestation.get("schema_version") != 2:
        mismatches.append("schema_version")
    if execution.get("method") != "app-server-isolated-agent":
        mismatches.append("execution.method")
    if execution.get("collector") != "codex-app-server-managed-v1":
        mismatches.append("execution.collector")
    if evidence.get("source") != "verified-app-server-managed":
        mismatches.append("evidence.source")
    checks = {
        "agent": expected.get("agent"),
        "model": expected.get("model"),
        "tier": expected.get("tier"),
        "reasoning_effort": expected.get("reasoning_effort"),
        "sandbox_mode": expected.get("sandbox_mode"),
        "context_inheritance": "none",
        "agent_binding": "verified-thread-start-profile",
    }
    for field, value in checks.items():
        if observed.get(field) != value:
            mismatches.append(field)
    if not observed.get("child_thread_id"):
        mismatches.append("child_thread_id")
    if observed.get("parent_thread_id") is not None:
        mismatches.append("parent_thread_id")
    if observed.get("forked_from_id") is not None:
        mismatches.append("forked_from_id")
    actual_cwd = str(observed.get("cwd") or "")
    if not actual_cwd or Path(actual_cwd).resolve() != context.project_root.resolve():
        mismatches.append("cwd")
    profile_ref = str(evidence.get("agent_profile_ref") or "")
    profile_hash = str(evidence.get("agent_profile_sha256") or "")
    if not profile_ref or not profile_hash:
        mismatches.append("agent_profile_evidence")
    else:
        profile_path = (context.package_root / profile_ref).resolve()
        try:
            profile_path.relative_to(context.package_root.resolve())
        except ValueError:
            mismatches.append("agent_profile_ref")
        else:
            if not profile_path.is_file() or file_sha256(profile_path) != profile_hash:
                mismatches.append("agent_profile_sha256")
    for key in (
        "developer_instructions_sha256",
        "thread_start_request_sha256",
        "turn_start_request_sha256",
    ):
        if not evidence.get(key):
            mismatches.append(key)
    if mismatches:
        raise CodexManagedRuntimeError(
            "managed runtime attestation mismatch: "
            + ", ".join(dict.fromkeys(mismatches))
        )
