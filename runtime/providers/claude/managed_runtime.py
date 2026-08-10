"""Attested managed read-only execution through the Claude Code CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core.provider_registry import get_provider
from project_context import ProjectContext


class ClaudeManagedRuntimeError(RuntimeError):
    pass


_ALLOWED_TOOLS = ("Read", "Grep", "Glob")
_DISALLOWED_TOOLS = (
    "Write", "Edit", "NotebookEdit", "Bash", "PowerShell", "Agent", "Skill",
    "WebFetch", "WebSearch", "EnterWorktree", "SendMessage", "mcp__*",
)
_INVALID_SESSION_SOURCES = {"resume", "clear", "compact", "fork"}
_FROZEN_HASH_FIELDS = (
    "profile_source_sha256", "model_config_sha256", "agent_projection_sha256",
    "settings_projection_sha256", "hook_projection_sha256",
)
_MIN_SUPPORTED_VERSION = (2, 1, 217)
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class ClaudeExecutableIdentity:
    path: str
    version: str
    sha256: str
    resolution_method: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _text_sha256(value: str) -> str:
    return hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_supported_version(version: str) -> None:
    match = _VERSION_PATTERN.search(version)
    if not match:
        raise ClaudeManagedRuntimeError(f"unrecognized Claude Code version: {version!r}")
    resolved = tuple(int(part) for part in match.groups())
    if resolved < _MIN_SUPPORTED_VERSION:
        minimum = ".".join(str(part) for part in _MIN_SUPPORTED_VERSION)
        raise ClaudeManagedRuntimeError(
            f"Claude Code {version} is older than the supported minimum {minimum}; upgrade the CLI"
        )


def _cmd_executable_candidates(path: Path) -> list[Path]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ClaudeManagedRuntimeError(f"cannot read Claude command shim: {path}") from error
    values: list[Path] = []
    replacement = str(path.parent) + os.sep
    for raw in re.findall(r'"([^"]+\.exe)"', text, flags=re.IGNORECASE):
        expanded = re.sub(
            r"%~?dp0%?",
            lambda _match: replacement,
            raw,
            flags=re.IGNORECASE,
        )
        candidate = Path(expanded).resolve()
        if candidate.is_file() and candidate.name.lower().startswith("claude"):
            values.append(candidate)
    return list(dict.fromkeys(values))


def resolve_claude_executable(path: Path) -> tuple[Path, str]:
    path = path.resolve()
    if path.suffix.lower() not in {".cmd", ".bat"}:
        if not path.is_file():
            raise ClaudeManagedRuntimeError(f"Claude Code executable does not exist: {path}")
        return path, "direct"
    candidates = _cmd_executable_candidates(path)
    if len(candidates) != 1:
        raise ClaudeManagedRuntimeError(
            "Claude command shim must resolve to exactly one claude*.exe, "
            f"found {len(candidates)}: {path}"
        )
    return candidates[0], "windows-shim-resolved"


def find_claude_executable() -> str:
    configured = os.environ.get("SITTER_CLAUDE_EXECUTABLE", "").strip()
    if configured:
        resolved, _ = resolve_claude_executable(Path(configured))
        return str(resolved)
    value = shutil.which("claude")
    if not value:
        raise ClaudeManagedRuntimeError("Claude Code executable was not found")
    resolved, _ = resolve_claude_executable(Path(value))
    return str(resolved)


def _run_version(
    prefix: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        [*prefix, "--version"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=environment,
    )
    if completed.returncode:
        raise ClaudeManagedRuntimeError(
            "claude --version failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    value = completed.stdout.strip()
    if not value:
        raise ClaudeManagedRuntimeError("claude --version returned no version")
    require_supported_version(value)
    return value


def executable_identity(
    command_prefix: tuple[str, ...] | None = None,
    *,
    environment: dict[str, str] | None = None,
) -> ClaudeExecutableIdentity:
    if command_prefix is not None:
        path = Path(command_prefix[0]).resolve()
        method = "explicit-command-prefix"
        prefix = command_prefix
    else:
        configured = os.environ.get("SITTER_CLAUDE_EXECUTABLE", "").strip()
        raw = Path(configured) if configured else Path(shutil.which("claude") or "")
        if not str(raw):
            raise ClaudeManagedRuntimeError("Claude Code executable was not found")
        path, method = resolve_claude_executable(raw)
        prefix = (str(path),)
    version = _run_version(prefix, environment=environment)
    digest = _file_sha256(path) if path.is_file() else _sha256(list(prefix))
    return ClaudeExecutableIdentity(str(path), version, digest, method)


def claude_version(
    command_prefix: tuple[str, ...] | None = None,
    *,
    environment: dict[str, str] | None = None,
) -> str:
    return executable_identity(command_prefix, environment=environment).version


def _requested_profile(packet: dict) -> dict:
    value = packet.get("requested_profile")
    if not isinstance(value, dict):
        raise ClaudeManagedRuntimeError("delegation request has no requested_profile mapping")
    return value


def _installed_path(project: Path, ref: str) -> Path:
    path = (project / ref).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as error:
        raise ClaudeManagedRuntimeError(f"frozen Claude asset escapes the project: {ref}") from error
    return path


def _assert_frozen_profile(context: ProjectContext, packet: dict):
    runtime = packet.get("runtime") or {}
    if runtime.get("provider") != "claude":
        raise ClaudeManagedRuntimeError("managed Claude execution requires runtime.provider: claude")
    expected = _requested_profile(packet)
    role = str(expected.get("role_id") or expected.get("agent") or "")
    if not role:
        raise ClaudeManagedRuntimeError("delegation request has no Claude role")
    profile = get_provider("claude").load_role_profile(context, role)
    checks = {
        "runtime_role": profile.runtime_role,
        "model_selector": profile.model,
        "model_grade": profile.tier,
        "reasoning_effort": profile.reasoning_effort,
        "write_isolation": profile.write_isolation,
        "model_resolution_mode": profile.model_resolution_mode,
        "expected_resolved_model": profile.expected_resolved_model,
        "proxy_provider": profile.proxy_provider,
    }
    mismatches = [
        key
        for key, value in checks.items()
        if str(expected.get(key) or ("native" if key == "model_resolution_mode" else ""))
        != str(value)
    ]
    for key in _FROZEN_HASH_FIELDS:
        if str(expected.get(key) or "") != str(getattr(profile, key, "")):
            mismatches.append(key)
    if mismatches:
        raise ClaudeManagedRuntimeError(
            "current Claude profile differs from the frozen request: "
            + ", ".join(dict.fromkeys(mismatches))
        )
    paths = {
        key: _installed_path(context.project_root, str(ref))
        for key, ref in (
            ("agent_projection_sha256", profile.agent_projection_ref),
            ("settings_projection_sha256", profile.settings_projection_ref),
            ("hook_projection_sha256", profile.hook_projection_ref),
        )
    }
    for hash_field, path in paths.items():
        if not path.is_file():
            raise ClaudeManagedRuntimeError(f"installed Claude asset is missing: {path}")
        actual = _text_sha256(path.read_text(encoding="utf-8"))
        if actual != str(expected.get(hash_field) or ""):
            raise ClaudeManagedRuntimeError(
                f"installed Claude asset differs from the frozen request: {path}"
            )
    return profile, paths


def _empty_mcp_config(directory: Path) -> Path:
    path = directory / "empty-mcp.json"
    path.write_text('{"mcpServers":{}}\n', encoding="utf-8", newline="")
    return path


def build_managed_command(
    context: ProjectContext,
    packet: dict,
    *,
    message: str,
    session_id: str,
    command_prefix: tuple[str, ...] | None = None,
    mcp_config: Path,
) -> tuple[str, ...]:
    profile, paths = _assert_frozen_profile(context, packet)
    prefix = command_prefix or (find_claude_executable(),)
    return (
        *prefix,
        "-p",
        message,
        "--agent",
        profile.runtime_role,
        "--model",
        profile.model,
        "--effort",
        profile.reasoning_effort,
        "--permission-mode",
        "dontAsk",
        "--tools",
        ",".join(_ALLOWED_TOOLS),
        "--disallowedTools",
        ",".join(_DISALLOWED_TOOLS),
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-chrome",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
        "--session-id",
        session_id,
        "--no-session-persistence",
        "--settings",
        str(paths["settings_projection_sha256"]),
        "--setting-sources",
        "user,project,local",
    )


def _stream_records(stdout: str) -> list[dict]:
    records: list[dict] = []
    for number, line in enumerate(stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ClaudeManagedRuntimeError(
                f"Claude stream contains invalid JSON at line {number}"
            ) from error
        if not isinstance(value, dict):
            raise ClaudeManagedRuntimeError(
                f"Claude stream line {number} is not a JSON object"
            )
        records.append(value)
    if not records:
        raise ClaudeManagedRuntimeError("Claude stream returned no JSON messages")
    return records


def _walk(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _tool_names(records: list[dict]) -> list[str]:
    names: list[str] = []
    for record in records:
        for item in _walk(record):
            if str(item.get("type") or "") in {"tool_use", "tool_call"}:
                name = str(item.get("name") or item.get("tool_name") or "")
                if name:
                    names.append(name)
    return list(dict.fromkeys(names))


def _load_hook_events(directory: Path, nonce: str, mode: str) -> list[dict]:
    events: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ClaudeManagedRuntimeError(f"invalid Claude hook evidence: {path}") from error
        if envelope.get("attempt_nonce") != nonce or envelope.get("execution_mode") != mode:
            raise ClaudeManagedRuntimeError(
                f"Claude hook evidence has the wrong attempt binding: {path}"
            )
        event = envelope.get("event")
        if not isinstance(event, dict):
            raise ClaudeManagedRuntimeError(
                f"Claude hook evidence has no event mapping: {path}"
            )
        events.append(event)
    if not events:
        raise ClaudeManagedRuntimeError("Claude execution produced no hook evidence")
    return events


def _exact_record(
    records: list[dict],
    record_type: str,
    subtype: str | None = None,
) -> dict:
    values = [
        item
        for item in records
        if item.get("type") == record_type
        and (subtype is None or item.get("subtype") == subtype)
    ]
    if len(values) != 1:
        suffix = f"/{subtype}" if subtype else ""
        raise ClaudeManagedRuntimeError(
            f"expected exactly one Claude {record_type}{suffix} message, found {len(values)}"
        )
    return values[0]


def _advertised_tools(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    result: set[str] = set()
    for item in value:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("tool_name") or "")
            if name:
                result.add(name)
    return result


def model_binding_matches(
    selector: str,
    resolved: str,
    *,
    resolution_mode: str = "native",
    expected_resolved_model: str = "",
    proxy_provider: str = "",
) -> tuple[bool, str]:
    selector = selector.strip().lower()
    resolved = resolved.strip().lower()
    if not selector or not resolved:
        return False, ""
    if resolution_mode == "explicit-proxy":
        expected = expected_resolved_model.strip().lower()
        matches = resolved == expected and bool(expected)
        return (
            matches,
            f"explicit-proxy:{proxy_provider}" if matches else "",
        )
    if resolution_mode != "native":
        return False, ""
    if selector in {"haiku", "sonnet", "opus"}:
        return selector in resolved, "native-family"
    return selector == resolved, "native-exact"


def execute_managed_read_only(
    context: ProjectContext,
    packet: dict,
    *,
    message: str,
    command_prefix: tuple[str, ...] | None = None,
    timeout: float = 900.0,
    environment: dict[str, str] | None = None,
) -> tuple[str, dict, dict]:
    base_environment = dict(os.environ if environment is None else environment)
    identity = executable_identity(command_prefix, environment=base_environment)
    profile, projection_paths = _assert_frozen_profile(context, packet)
    expected = _requested_profile(packet)
    session_id = str(uuid.uuid4())
    nonce = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="sitter-claude-managed-") as raw:
        temporary = Path(raw)
        evidence_dir = temporary / "hook-events"
        evidence_dir.mkdir()
        command = build_managed_command(
            context,
            packet,
            message=message,
            session_id=session_id,
            command_prefix=command_prefix,
            mcp_config=_empty_mcp_config(temporary),
        )
        env = dict(base_environment)
        for key in ("ANTHROPIC_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            env.pop(key, None)
        env.update(
            {
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                "CLAUDE_CODE_FORK_SUBAGENT": "0",
                "SITTER_CLAUDE_EVIDENCE_DIR": str(evidence_dir),
                "SITTER_CLAUDE_ATTEMPT_NONCE": nonce,
                "SITTER_CLAUDE_EXECUTION_MODE": "managed",
            }
        )
        completed = subprocess.run(
            list(command),
            cwd=context.project_root,
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
        )
        if completed.returncode:
            raise ClaudeManagedRuntimeError(
                "Claude managed execution failed: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )
        records = _stream_records(completed.stdout)
        hooks = _load_hook_events(evidence_dir, nonce, "managed")
    init = _exact_record(records, "system", "init")
    result = _exact_record(records, "result")
    if bool(result.get("is_error")):
        raise ClaudeManagedRuntimeError("Claude managed execution reported an error result")
    output = str(result.get("result") or "").strip()
    if not output:
        raise ClaudeManagedRuntimeError("Claude result message contains no final output")
    actual_session = str(result.get("session_id") or init.get("session_id") or "")
    if actual_session != session_id:
        raise ClaudeManagedRuntimeError(
            "Claude managed execution returned a different session ID"
        )
    resolved_model = str(result.get("model") or init.get("model") or "")
    model_ok, mapping_source = model_binding_matches(
        profile.model,
        resolved_model,
        resolution_mode=profile.model_resolution_mode,
        expected_resolved_model=profile.expected_resolved_model,
        proxy_provider=profile.proxy_provider,
    )
    if not model_ok:
        raise ClaudeManagedRuntimeError(
            "Claude resolved model does not match the frozen resolution policy: "
            f"{profile.model} -> {resolved_model or '<missing>'}"
        )
    tools_configured = _advertised_tools(init.get("tools"))
    if tools_configured != set(_ALLOWED_TOOLS):
        raise ClaudeManagedRuntimeError(
            "Claude system/init tools differ from the governed allowlist"
        )
    if init.get("mcp_servers") or init.get("mcpServers"):
        raise ClaudeManagedRuntimeError(
            "Claude managed execution initialized one or more MCP servers"
        )
    actual_cwd = str(init.get("cwd") or result.get("cwd") or "")
    if not actual_cwd or Path(actual_cwd).resolve() != context.project_root.resolve():
        raise ClaudeManagedRuntimeError(
            "Claude managed execution used the wrong working directory"
        )
    tools_used = list(
        dict.fromkeys(
            _tool_names(records)
            + [
                str(event.get("tool_name"))
                for event in hooks
                if event.get("hook_event_name") in {"PreToolUse", "PostToolUse"}
                and event.get("tool_name")
            ]
        )
    )
    forbidden = set(tools_used) - set(_ALLOWED_TOOLS)
    if forbidden:
        raise ClaudeManagedRuntimeError(
            "Claude managed execution used forbidden tools: "
            + ", ".join(sorted(forbidden))
        )
    invalid: list[str] = []
    for event in hooks:
        name = str(event.get("hook_event_name") or "")
        if name in {"PreCompact", "PostCompact"}:
            invalid.append("compact")
        elif name == "WorktreeCreate":
            invalid.append("worktree")
        elif (
            name == "SessionStart"
            and str(event.get("source") or "") in _INVALID_SESSION_SOURCES
        ):
            invalid.append(str(event.get("source")))
    if invalid:
        raise ClaudeManagedRuntimeError(
            "Claude managed execution violated context continuity: "
            + ", ".join(dict.fromkeys(invalid))
        )
    hook_names = {str(event.get("hook_event_name") or "") for event in hooks}
    if not {"SessionStart", "InstructionsLoaded", "SessionEnd"}.issubset(hook_names):
        raise ClaudeManagedRuntimeError(
            "Claude managed execution is missing required lifecycle hook evidence"
        )
    projection_hashes = {
        key: _text_sha256(path.read_text(encoding="utf-8"))
        for key, path in projection_paths.items()
    }
    evidence = {
        "source": "verified-claude-managed-v2",
        "profile_source_sha256": str(expected["profile_source_sha256"]),
        "model_config_sha256": str(expected["model_config_sha256"]),
        "agent_projection_sha256": projection_hashes["agent_projection_sha256"],
        "settings_projection_sha256": projection_hashes["settings_projection_sha256"],
        "hook_projection_sha256": projection_hashes["hook_projection_sha256"],
        "request_sha256": _sha256(packet),
        "command_sha256": _sha256(command),
        "stream_sha256": _text_sha256(completed.stdout),
        "hook_events_sha256": _sha256(hooks),
    }
    attestation = {
        "schema_version": 2,
        "execution": {
            "method": "claude-managed-agent",
            "collector": "claude-stream-hooks-transcript-v2",
            "claude_version": identity.version,
            "executable_path": identity.path,
            "executable_sha256": identity.sha256,
            "executable_resolution": identity.resolution_method,
            "session_ref": f"claude-session:{session_id}",
            "session_id": session_id,
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
            "reasoning_effort_binding": "verified-command",
            "context_inheritance": "none",
            "write_isolation": "tool-restricted",
            "persistent_context": "disabled",
            "tools_configured": sorted(tools_configured),
            "tools_used": tools_used,
            "mcp_configuration": "strict-empty-config",
            "continuity_events": [],
            "cwd": actual_cwd,
        },
        "evidence": evidence,
    }
    raw_evidence = {
        "schema_version": 2,
        "execution": "claude-managed-agent",
        "executable": identity.__dict__,
        "command": list(command),
        "sanitized_environment": {
            key: env[key]
            for key in (
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
                "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
                "CLAUDE_CODE_FORK_SUBAGENT",
                "SITTER_CLAUDE_ATTEMPT_NONCE",
                "SITTER_CLAUDE_EXECUTION_MODE",
            )
        },
        "requested_profile": expected,
        "stream": records,
        "hook_events": hooks,
        "stderr": completed.stderr,
    }
    get_provider("claude").validate_attestation(packet, attestation)
    return output, attestation, raw_evidence
