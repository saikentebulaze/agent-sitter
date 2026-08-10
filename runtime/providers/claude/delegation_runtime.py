"""File-backed delegation operations for the Claude Provider."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import yaml

from delegation_transaction import record_delegation_result
from project_context import ProjectContext
from providers.claude.managed_runtime import execute_managed_read_only
from work_graph import load_yaml, project_relative, resolve_task_root, valid_id


class ClaudeDelegationRuntimeError(RuntimeError):
    pass


_SCOPE_TOOLS = {"Read", "Grep", "Glob"}
_SCOPE_REQUIRED_ENV = "SITTER_CLAUDE_SCOPE_REQUIRED"
_SCOPE_POLICY_ENV = "SITTER_CLAUDE_SCOPE_POLICY"
_SCOPE_POLICY_SHA_ENV = "SITTER_CLAUDE_SCOPE_POLICY_SHA256"


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


def _safe_project_path(
    context: ProjectContext,
    value: str | Path,
    *,
    require_exists: bool,
) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    raw = Path(text).expanduser()
    candidate = raw if raw.is_absolute() else context.project_root / raw
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(context.project_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    if require_exists and not resolved.exists():
        return None
    return resolved


def _scope_entry(context: ProjectContext, path: Path) -> dict:
    kind = "directory" if path.is_dir() else "file"
    return {
        "ref": project_relative(context, path),
        "kind": kind,
    }


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (str(entry.get("ref") or ""), str(entry.get("kind") or ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def scope_policy_path(request_path: Path, packet: dict) -> Path:
    attempt = int((packet.get("delegation") or {}).get("attempt") or 0)
    if attempt <= 0:
        raise ClaudeDelegationRuntimeError(
            "delegation request has an invalid attempt"
        )
    return request_path.parent / f"attempt-{attempt:02d}.scope-policy.json"


def build_scope_policy(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
) -> dict:
    allowed: list[dict] = []
    excluded: list[dict] = []

    request = _safe_project_path(
        context,
        request_path,
        require_exists=True,
    )
    if request is None:
        raise ClaudeDelegationRuntimeError(
            "delegation request is outside the project or missing"
        )
    allowed.append(_scope_entry(context, request))

    scope = packet.get("scope") or {}
    for value in scope.get("include") or []:
        path = _safe_project_path(context, str(value), require_exists=True)
        if path is not None:
            allowed.append(_scope_entry(context, path))

    for item in packet.get("start_here") or []:
        path = _safe_project_path(
            context,
            str((item or {}).get("ref") or ""),
            require_exists=True,
        )
        if path is not None:
            allowed.append(_scope_entry(context, path))

    projection = packet.get("projection") or {}
    for item in projection.get("authority_refs") or []:
        path = _safe_project_path(
            context,
            str((item or {}).get("ref") or ""),
            require_exists=True,
        )
        if path is not None:
            allowed.append(_scope_entry(context, path))

    for item in packet.get("context_supplements") or []:
        path = _safe_project_path(
            context,
            str((item or {}).get("ref") or ""),
            require_exists=True,
        )
        if path is not None:
            allowed.append(_scope_entry(context, path))

    for value in scope.get("exclude") or []:
        path = _safe_project_path(context, str(value), require_exists=False)
        if path is not None:
            excluded.append(
                {
                    "ref": project_relative(context, path),
                    "kind": "directory" if path.is_dir() else "file",
                }
            )

    allowed = _dedupe_entries(allowed)
    excluded = _dedupe_entries(excluded)
    if not allowed:
        raise ClaudeDelegationRuntimeError(
            "delegation has no filesystem paths that can be mechanically scoped"
        )

    return {
        "schema_version": 1,
        "provider": "claude",
        "project_root": str(context.project_root.resolve()),
        "request_ref": project_relative(context, request),
        "request_sha256": _canonical_sha256(packet),
        "allowed": allowed,
        "excluded": excluded,
    }


def ensure_scope_policy(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
) -> tuple[Path, str, dict]:
    path = scope_policy_path(request_path, packet)
    policy = build_scope_policy(context, request_path, packet)
    content = json.dumps(
        policy,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ClaudeDelegationRuntimeError(
                f"invalid existing scope policy: {path}"
            ) from error
        if existing != policy:
            raise ClaudeDelegationRuntimeError(
                f"conflicting scope policy already exists: {path}"
            )
    else:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.staging")
        temporary.write_text(content, encoding="utf-8", newline="")
        temporary.replace(path)

    return path, _file_sha256(path), policy


def scope_environment(
    context: ProjectContext,
    request_path: Path,
    packet: dict,
    environment: dict[str, str] | None = None,
) -> tuple[dict[str, str], Path, str, dict]:
    policy_path, digest, policy = ensure_scope_policy(
        context,
        request_path,
        packet,
    )
    env = dict(os.environ if environment is None else environment)
    env.update(
        {
            _SCOPE_REQUIRED_ENV: "1",
            _SCOPE_POLICY_ENV: str(policy_path.resolve()),
            _SCOPE_POLICY_SHA_ENV: digest,
        }
    )
    return env, policy_path, digest, policy


def _scope_checked_events(events: list[dict], digest: str) -> list[dict]:
    """Normalize scope decisions and prove denied calls never reached PostToolUse."""

    post_tool_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("hook_event_name") != "PostToolUse":
            continue
        if str(event.get("tool_name") or "") not in _SCOPE_TOOLS:
            continue
        tool_use_id = str(event.get("tool_use_id") or "").strip()
        if tool_use_id:
            post_tool_ids.add(tool_use_id)

    checked: list[dict] = []
    denied_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("hook_event_name") != "PreToolUse":
            continue
        tool = str(event.get("tool_name") or "")
        if tool not in _SCOPE_TOOLS:
            continue
        if event.get("scope_policy_sha256") != digest:
            raise ClaudeDelegationRuntimeError(
                "Claude scope event has the wrong policy hash"
            )
        decision = str(event.get("scope_decision") or "")
        if decision not in {"allowed", "denied"}:
            raise ClaudeDelegationRuntimeError(
                "Claude scope event has an invalid decision"
            )
        reason = str(event.get("scope_reason") or "").strip()
        if not reason:
            raise ClaudeDelegationRuntimeError(
                "Claude scope event has no decision reason"
            )
        tool_use_id = str(event.get("tool_use_id") or "").strip()
        if not tool_use_id:
            raise ClaudeDelegationRuntimeError(
                "Claude scope event has no tool_use_id"
            )
        target = str(event.get("scope_resolved_target") or "")
        if decision == "allowed" and not target:
            raise ClaudeDelegationRuntimeError(
                "allowed Claude scope event has no resolved target"
            )
        if decision == "denied":
            denied_ids.add(tool_use_id)
        checked.append(
            {
                "tool": tool,
                "tool_use_id": tool_use_id,
                "decision": decision,
                "reason": reason,
                "resolved_target": target,
            }
        )

    executed_denied = denied_ids & post_tool_ids
    if executed_denied:
        raise ClaudeDelegationRuntimeError(
            "a scope-denied Claude tool call reached PostToolUse: "
            + ", ".join(sorted(executed_denied))
        )
    return checked


def bind_scope_evidence(
    context: ProjectContext,
    packet: dict,
    *,
    policy_path: Path,
    policy_sha256: str,
    policy: dict,
    attestation: dict,
    evidence: dict,
) -> None:
    if _file_sha256(policy_path) != policy_sha256:
        raise ClaudeDelegationRuntimeError(
            "Claude scope policy changed after execution"
        )
    if policy.get("request_sha256") != _canonical_sha256(packet):
        raise ClaudeDelegationRuntimeError(
            "Claude scope policy does not match the frozen request"
        )
    events = evidence.get("hook_events") or []
    if not isinstance(events, list):
        raise ClaudeDelegationRuntimeError(
            "Claude runtime evidence has no Hook event list"
        )
    checked = _scope_checked_events(events, policy_sha256)
    allowed_count = sum(
        item.get("decision") == "allowed" for item in checked
    )
    denied_count = sum(
        item.get("decision") == "denied" for item in checked
    )
    scope_events_sha256 = _canonical_sha256(checked)
    ref = project_relative(context, policy_path)

    observed = attestation.setdefault("observed", {})
    observed.update(
        {
            "filesystem_scope": "mechanically-enforced",
            "scope_policy_ref": ref,
            "scope_policy_sha256": policy_sha256,
            "scope_checked_tool_calls": len(checked),
            "scope_allowed_tool_calls": allowed_count,
            "scope_denied_tool_calls": denied_count,
        }
    )
    attestation_evidence = attestation.setdefault("evidence", {})
    attestation_evidence.update(
        {
            "scope_policy_sha256": policy_sha256,
            "scope_events_sha256": scope_events_sha256,
        }
    )
    evidence.update(
        {
            "scope_policy_ref": ref,
            "scope_policy_sha256": policy_sha256,
            "scope_policy": policy,
            "scope_checked_events": checked,
            "scope_events_sha256": scope_events_sha256,
        }
    )


def validate_scope_artifacts(
    context: ProjectContext,
    packet: dict,
    attestation: dict,
    evidence: dict,
) -> None:
    observed = attestation.get("observed") or {}
    attestation_evidence = attestation.get("evidence") or {}
    if observed.get("filesystem_scope") != "mechanically-enforced":
        raise ClaudeDelegationRuntimeError(
            "runtime attestation has no mechanical filesystem scope proof"
        )
    ref = str(observed.get("scope_policy_ref") or "")
    digest = str(observed.get("scope_policy_sha256") or "")
    if not ref or len(digest) != 64:
        raise ClaudeDelegationRuntimeError(
            "runtime attestation has an invalid scope policy binding"
        )
    policy_path = (context.project_root / ref).resolve()
    try:
        policy_path.relative_to(context.project_root.resolve())
    except ValueError as error:
        raise ClaudeDelegationRuntimeError(
            "scope policy is outside the project"
        ) from error
    if not policy_path.is_file() or policy_path.is_symlink():
        raise ClaudeDelegationRuntimeError(
            "scope policy is missing or unsafe"
        )
    if _file_sha256(policy_path) != digest:
        raise ClaudeDelegationRuntimeError(
            "scope policy hash does not match the attestation"
        )
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClaudeDelegationRuntimeError(
            "scope policy is invalid"
        ) from error
    if policy.get("request_sha256") != _canonical_sha256(packet):
        raise ClaudeDelegationRuntimeError(
            "scope policy does not match the frozen request"
        )
    if evidence.get("scope_policy") != policy:
        raise ClaudeDelegationRuntimeError(
            "raw evidence scope policy differs from the persisted policy"
        )
    if evidence.get("scope_policy_sha256") != digest:
        raise ClaudeDelegationRuntimeError(
            "raw evidence has the wrong scope policy hash"
        )
    events = evidence.get("hook_events") or []
    checked = _scope_checked_events(events, digest)
    expected_events_hash = _canonical_sha256(checked)
    if evidence.get("scope_checked_events") != checked:
        raise ClaudeDelegationRuntimeError(
            "raw evidence normalized scope events are invalid"
        )
    if evidence.get("scope_events_sha256") != expected_events_hash:
        raise ClaudeDelegationRuntimeError(
            "raw evidence scope event hash is invalid"
        )
    allowed_count = sum(
        item.get("decision") == "allowed" for item in checked
    )
    denied_count = sum(
        item.get("decision") == "denied" for item in checked
    )
    if observed.get("scope_checked_tool_calls") != len(checked):
        raise ClaudeDelegationRuntimeError(
            "runtime attestation scope call count is invalid"
        )
    if observed.get("scope_allowed_tool_calls") != allowed_count:
        raise ClaudeDelegationRuntimeError(
            "runtime attestation allowed scope count is invalid"
        )
    if observed.get("scope_denied_tool_calls") != denied_count:
        raise ClaudeDelegationRuntimeError(
            "runtime attestation denied scope count is invalid"
        )
    if attestation_evidence.get("scope_policy_sha256") != digest:
        raise ClaudeDelegationRuntimeError(
            "attestation evidence has the wrong scope policy hash"
        )
    if (
        attestation_evidence.get("scope_events_sha256")
        != expected_events_hash
    ):
        raise ClaudeDelegationRuntimeError(
            "attestation evidence has the wrong scope event hash"
        )


def load_attempt(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
) -> tuple[Path, Path, dict]:
    task_root = resolve_task_root(context, task_value)
    task = load_yaml(task_root / "task.yaml")
    if (
        ((task.get("execution") or {}).get("orchestrator_provider") or "codex")
        != "claude"
    ):
        raise ClaudeDelegationRuntimeError(
            "Claude runtime cannot execute a non-Claude Task"
        )
    delegation_id = valid_id(delegation_id, "delegation_id")
    planned = next(
        (
            item
            for item in ((task.get("delegation") or {}).get("planned") or [])
            if item.get("id") == delegation_id
        ),
        None,
    )
    if planned is None:
        raise ClaudeDelegationRuntimeError(
            f"delegation not found: {delegation_id}"
        )
    if str(planned.get("provider") or "") != "claude":
        raise ClaudeDelegationRuntimeError(
            "delegation is not bound to the Claude Provider"
        )
    request_ref = str((planned.get("context") or {}).get("request_ref") or "")
    request_path = (context.project_root / request_ref).resolve()
    try:
        request_path.relative_to(task_root.resolve())
    except ValueError as error:
        raise ClaudeDelegationRuntimeError(
            "delegation request is outside the task directory"
        ) from error
    packet = load_yaml(request_path)
    if str((packet.get("runtime") or {}).get("provider") or "") != "claude":
        raise ClaudeDelegationRuntimeError(
            "delegation request is not bound to Claude"
        )
    return task_root, request_path, packet


def delegation_message(context: ProjectContext, request_path: Path) -> str:
    return (
        "Read and follow the frozen Sitter delegation request at:\n\n"
        f"{project_relative(context, request_path)}\n\n"
        "Use only its role, context, tools, filesystem scope, and authority "
        "references. Do not rely on parent conversation history. Return the "
        "required output or a structured NEED_CONTEXT response."
    )


def artifact_paths(
    request_path: Path,
    packet: dict,
) -> tuple[Path, Path, Path]:
    attempt = int((packet.get("delegation") or {}).get("attempt") or 0)
    if attempt <= 0:
        raise ClaudeDelegationRuntimeError(
            "delegation request has an invalid attempt"
        )
    directory = request_path.parent
    return (
        directory / f"attempt-{attempt:02d}.result-candidate.md",
        directory / f"attempt-{attempt:02d}.runtime-attestation.yaml",
        directory / f"attempt-{attempt:02d}.runtime-evidence.json",
    )


def _stage(path: Path, content: str) -> Path:
    staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}.staging")
    with staging.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return staging


def _write_runtime_artifacts(
    request_path: Path,
    packet: dict,
    *,
    output: str,
    attestation: dict,
    evidence: dict,
) -> tuple[Path, Path, Path]:
    targets = artifact_paths(request_path, packet)
    for path in targets:
        if path.exists():
            raise ClaudeDelegationRuntimeError(
                f"runtime artifact already exists: {path}"
            )
    contents = (
        output.rstrip() + "\n",
        yaml.safe_dump(attestation, allow_unicode=True, sort_keys=False),
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
    )
    staging: list[Path] = []
    published: list[Path] = []
    try:
        staging = [
            _stage(path, content)
            for path, content in zip(targets, contents)
        ]
        for temporary, target in zip(staging, targets):
            temporary.replace(target)
            published.append(target)
    except BaseException:
        for path in staging:
            path.unlink(missing_ok=True)
        for path in published:
            path.unlink(missing_ok=True)
        raise
    return targets


def run_isolated(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    command_prefix: tuple[str, ...] | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[Path, Path, Path]:
    _, request_path, packet = load_attempt(
        context,
        task_value,
        delegation_id,
    )
    env, policy_path, digest, policy = scope_environment(
        context,
        request_path,
        packet,
        environment,
    )
    output, attestation, evidence = execute_managed_read_only(
        context,
        packet,
        message=delegation_message(context, request_path),
        command_prefix=command_prefix,
        environment=env,
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


def _record(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    outcome: str,
    method: str,
) -> tuple[Path, str, bool]:
    _, request_path, packet = load_attempt(
        context,
        task_value,
        delegation_id,
    )
    output_path, attestation_path, evidence_path = artifact_paths(
        request_path,
        packet,
    )
    for path in (output_path, attestation_path, evidence_path):
        if not path.is_file():
            raise ClaudeDelegationRuntimeError(
                f"runtime artifact is missing: {path}"
            )
    attestation = load_yaml(attestation_path)
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClaudeDelegationRuntimeError(
            f"runtime evidence is invalid: {evidence_path}"
        ) from error
    validate_scope_artifacts(context, packet, attestation, evidence)
    execution = attestation.get("execution") or {}
    if execution.get("method") != method:
        raise ClaudeDelegationRuntimeError(
            f"runtime artifacts do not describe {method}"
        )
    session_ref = str(execution.get("session_ref") or "")
    if not session_ref:
        raise ClaudeDelegationRuntimeError(
            "runtime attestation has no session_ref"
        )
    return record_delegation_result(
        context,
        task_value,
        delegation_id,
        artifact=output_path,
        outcome=outcome,
        evidence_ref=session_ref,
        attestation=attestation_path,
    )


def record_isolated_result(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    outcome: str,
) -> tuple[Path, str, bool]:
    return _record(
        context,
        task_value,
        delegation_id,
        outcome=outcome,
        method="claude-managed-agent",
    )


def record_native_result(
    context: ProjectContext,
    task_value: str,
    delegation_id: str,
    *,
    outcome: str,
) -> tuple[Path, str, bool]:
    return _record(
        context,
        task_value,
        delegation_id,
        outcome=outcome,
        method="claude-native-subagent",
    )
