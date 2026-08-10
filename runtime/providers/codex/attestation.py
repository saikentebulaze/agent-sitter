from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_profiles import MODEL_TIERS
from codex_app_server import (
    CodexAppServerClient,
    CodexAppServerError,
    find_codex_executable,
)
from project_context import ProjectContext


class CodexRuntimeAttestationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpawnEvidence:
    parent_rollout: Path
    spawn_line: int
    activity_line: int
    call_id: str
    child_thread_id: str
    task_name: str
    agent_type: str
    fork_turns: str


def _normalize_sandbox_type(value: object) -> str:
    mapping = {
        "readonly": "read-only",
        "read-only": "read-only",
        "workspacewrite": "workspace-write",
        "workspace-write": "workspace-write",
        "dangerfullaccess": "danger-full-access",
        "danger-full-access": "danger-full-access",
    }
    key = re.sub(r"[^a-z-]", "", str(value or "").lower())
    return mapping.get(key, str(value or ""))


def codex_version() -> str:
    executable = find_codex_executable()
    completed = subprocess.run(
        [executable, "--version"],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if completed.returncode != 0:
        raise CodexRuntimeAttestationError(
            "codex --version failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    value = completed.stdout.strip()
    if not value:
        raise CodexRuntimeAttestationError(
            "codex --version returned no version"
        )
    return value


def _iter_rollout_files(codex_home: Path) -> list[Path]:
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        raise CodexRuntimeAttestationError(
            f"Codex sessions directory is missing: {sessions}"
        )
    return sorted(
        sessions.rglob("*.jsonl"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )


def find_spawn_evidence(
    codex_home: Path,
    *,
    task_name: str,
) -> SpawnEvidence:
    spawn_matches: list[tuple[Path, int, str, str, str]] = []
    activity_by_call: dict[str, list[tuple[Path, int, str]]] = {}
    for path in _iter_rollout_files(codex_home):
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if task_name not in line and "sub_agent_activity" not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = record.get("payload") or {}
                    if (
                        record.get("type") == "response_item"
                        and payload.get("type") == "function_call"
                        and payload.get("name") == "spawn_agent"
                    ):
                        try:
                            arguments = json.loads(
                                payload.get("arguments") or "{}"
                            )
                        except json.JSONDecodeError:
                            continue
                        if arguments.get("task_name") != task_name:
                            continue
                        call_id = str(payload.get("call_id") or "")
                        agent_type = str(arguments.get("agent_type") or "")
                        fork_turns = str(arguments.get("fork_turns") or "")
                        if call_id:
                            spawn_matches.append(
                                (
                                    path,
                                    line_number,
                                    call_id,
                                    agent_type,
                                    fork_turns,
                                )
                            )
                    elif (
                        record.get("type") == "event_msg"
                        and payload.get("type") == "sub_agent_activity"
                        and payload.get("kind") == "started"
                    ):
                        call_id = str(
                            payload.get("event_id")
                            or payload.get("call_id")
                            or ""
                        )
                        child_id = str(payload.get("agent_thread_id") or "")
                        if call_id and child_id:
                            activity_by_call.setdefault(call_id, []).append(
                                (path, line_number, child_id)
                            )
        except (OSError, UnicodeError):
            continue

    if len(spawn_matches) != 1:
        raise CodexRuntimeAttestationError(
            f"expected exactly one persisted spawn_agent request for "
            f"{task_name}, found {len(spawn_matches)}"
        )
    parent_rollout, spawn_line, call_id, agent_type, fork_turns = (
        spawn_matches[0]
    )
    activities = activity_by_call.get(call_id) or []
    if len(activities) != 1:
        raise CodexRuntimeAttestationError(
            f"expected exactly one child-thread activity for spawn call "
            f"{call_id}, found {len(activities)}"
        )
    activity_rollout, activity_line, child_thread_id = activities[0]
    if activity_rollout != parent_rollout:
        raise CodexRuntimeAttestationError(
            "spawn request and child activity were persisted in different "
            "parent rollouts"
        )
    return SpawnEvidence(
        parent_rollout=parent_rollout,
        spawn_line=spawn_line,
        activity_line=activity_line,
        call_id=call_id,
        child_thread_id=child_thread_id,
        task_name=task_name,
        agent_type=agent_type,
        fork_turns=fork_turns,
    )


def _response_result(
    response: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, dict):
        raise CodexRuntimeAttestationError(
            f"{method} returned no result mapping"
        )
    return result


def collect_native_attestation(
    context: ProjectContext,
    packet: dict,
    *,
    client_factory: Callable[[], CodexAppServerClient] | None = None,
    version_provider: Callable[[], str] = codex_version,
) -> tuple[dict, dict]:
    runtime = packet.get("runtime") or {}
    task_name = str(runtime.get("task_name") or "")
    if not task_name:
        raise CodexRuntimeAttestationError(
            "delegation packet has no runtime.task_name"
        )
    expected = packet.get("requested_profile") or {}
    factory = client_factory or (
        lambda: CodexAppServerClient(
            client_name="sitter-harness-attestation"
        )
    )
    try:
        with factory() as client:
            codex_home = client.codex_home
            if codex_home is None:
                raise CodexRuntimeAttestationError(
                    "Codex App Server initialize response did not expose "
                    "codexHome"
                )
            spawn = find_spawn_evidence(
                codex_home,
                task_name=task_name,
            )
            read_response = client.request(
                "thread/read",
                {
                    "threadId": spawn.child_thread_id,
                    "includeTurns": False,
                },
            )
            resume_response = client.request(
                "thread/resume",
                {
                    "threadId": spawn.child_thread_id,
                    "excludeTurns": True,
                },
            )
            raw_messages = client.raw_messages
            app_stderr = client.stderr
    except (CodexAppServerError, OSError) as error:
        raise CodexRuntimeAttestationError(str(error)) from error

    read_result = _response_result(read_response, "thread/read")
    resume_result = _response_result(resume_response, "thread/resume")
    thread = resume_result.get("thread") or read_result.get("thread") or {}
    if not isinstance(thread, dict):
        raise CodexRuntimeAttestationError(
            "Codex thread metadata is missing"
        )
    sandbox = resume_result.get("sandbox") or {}
    if not isinstance(sandbox, dict):
        sandbox = {"type": sandbox}

    model = str(resume_result.get("model") or "")
    observed = {
        "agent": thread.get("agentRole"),
        "model": model,
        "tier": MODEL_TIERS.get(model),
        "reasoning_effort": resume_result.get("reasoningEffort"),
        "sandbox_mode": _normalize_sandbox_type(sandbox.get("type")),
        "sandbox": sandbox,
        "active_permission_profile": resume_result.get(
            "activePermissionProfile"
        ),
        "context_inheritance": (
            "none" if spawn.fork_turns == "none" else spawn.fork_turns
        ),
        "child_thread_id": spawn.child_thread_id,
        "parent_thread_id": thread.get("parentThreadId"),
        "agent_nickname": thread.get("agentNickname"),
        "cwd": resume_result.get("cwd") or thread.get("cwd"),
        "runtime_workspace_roots": (
            resume_result.get("runtimeWorkspaceRoots") or []
        ),
        "instruction_sources": resume_result.get("instructionSources") or [],
    }
    attestation = {
        "schema_version": 2,
        "execution": {
            "method": "native-subagent",
            "collector": "codex-rollout-app-server-v1",
            "codex_version": version_provider(),
            "task_name": task_name,
            "spawn_call_id": spawn.call_id,
            "session_ref": f"native-thread:{spawn.child_thread_id}",
        },
        "observed": observed,
        "evidence": {
            "source": "verified-combined",
            "parent_rollout": str(spawn.parent_rollout),
            "spawn_line": spawn.spawn_line,
            "activity_line": spawn.activity_line,
            "thread_read": f"thread/read:{spawn.child_thread_id}",
            "thread_resume": f"thread/resume:{spawn.child_thread_id}",
        },
    }
    evidence = {
        "schema_version": 1,
        "task_name": task_name,
        "spawn": {
            "call_id": spawn.call_id,
            "agent_type": spawn.agent_type,
            "fork_turns": spawn.fork_turns,
            "child_thread_id": spawn.child_thread_id,
            "parent_rollout": str(spawn.parent_rollout),
            "spawn_line": spawn.spawn_line,
            "activity_line": spawn.activity_line,
        },
        "thread_read": read_result,
        "thread_resume": resume_result,
        "app_server_raw": raw_messages,
        "app_server_stderr": app_stderr,
        "requested_profile": expected,
    }
    return attestation, evidence


def validate_runtime_attestation(
    packet: dict,
    attestation: dict,
) -> None:
    execution = attestation.get("execution") or {}
    observed = attestation.get("observed") or {}
    expected = packet.get("requested_profile") or {}
    runtime = packet.get("runtime") or {}
    mismatches: list[str] = []
    if execution.get("method") != "native-subagent":
        mismatches.append("execution.method")
    if execution.get("collector") != "codex-rollout-app-server-v1":
        mismatches.append("execution.collector")
    if execution.get("task_name") != runtime.get("task_name"):
        mismatches.append("runtime.task_name")
    if (attestation.get("evidence") or {}).get("source") != "verified-combined":
        mismatches.append("evidence.source")
    checks = {
        "agent": expected.get("agent"),
        "model": expected.get("model"),
        "tier": expected.get("tier"),
        "reasoning_effort": expected.get("reasoning_effort"),
        "sandbox_mode": expected.get("sandbox_mode"),
        "context_inheritance": "none",
    }
    for field, value in checks.items():
        if observed.get(field) != value:
            mismatches.append(field)
    child_thread_id = str(observed.get("child_thread_id") or "")
    parent_thread_id = str(observed.get("parent_thread_id") or "")
    if not child_thread_id:
        mismatches.append("child_thread_id")
    if not parent_thread_id:
        mismatches.append("parent_thread_id")
    expected_cwd = str(packet.get("project_root") or "")
    actual_cwd = str(observed.get("cwd") or "")
    if expected_cwd and (
        not actual_cwd
        or Path(actual_cwd).resolve() != Path(expected_cwd).resolve()
    ):
        mismatches.append("cwd")
    if mismatches:
        raise CodexRuntimeAttestationError(
            "runtime attestation mismatch: "
            + ", ".join(dict.fromkeys(mismatches))
        )
