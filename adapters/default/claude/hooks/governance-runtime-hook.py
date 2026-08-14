"""Scoped Claude Code hook for governed Agent attempts and bounded SessionStart continuity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path


_ALLOWED_CHILD_TOOLS = {"Read", "Grep", "Glob"}
_BLOCKED_EVENTS = {"PreCompact", "WorktreeCreate"}
_SCOPE_REQUIRED_ENV = "SITTER_CLAUDE_SCOPE_REQUIRED"
_SCOPE_POLICY_ENV = "SITTER_CLAUDE_SCOPE_POLICY"
_SCOPE_POLICY_SHA_ENV = "SITTER_CLAUDE_SCOPE_POLICY_SHA256"


def _sanitize(value: object) -> object:
    """Replace lone surrogates that crash strict UTF-8 serialization."""
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _evidence_target() -> tuple[Path, str, str] | None:
    directory = os.environ.get("SITTER_CLAUDE_EVIDENCE_DIR", "").strip()
    nonce = os.environ.get("SITTER_CLAUDE_ATTEMPT_NONCE", "").strip()
    mode = os.environ.get("SITTER_CLAUDE_EXECUTION_MODE", "").strip()
    if not directory or not nonce or mode not in {"managed", "native"}:
        return None
    return Path(directory), nonce, mode


def _write_event(payload: dict) -> None:
    target = _evidence_target()
    if target is None:
        return
    directory, nonce, mode = target
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema_version": 2,
        "attempt_nonce": nonce,
        "execution_mode": mode,
        "recorded_at_ns": time.time_ns(),
        "pid": os.getpid(),
        "event": payload,
    }
    path = directory / f"{envelope['recorded_at_ns']}-{uuid.uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            json.dump(envelope, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _deny(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _load_scope_policy() -> tuple[dict | None, str, str]:
    if os.environ.get(_SCOPE_REQUIRED_ENV, "").strip() != "1":
        return None, "", "scope-not-required"

    raw_path = os.environ.get(_SCOPE_POLICY_ENV, "").strip()
    expected_sha = os.environ.get(_SCOPE_POLICY_SHA_ENV, "").strip()
    if not raw_path or not expected_sha:
        return None, expected_sha, "scope-policy-environment-missing"

    path = Path(raw_path).expanduser().resolve(strict=False)
    if not path.is_file() or path.is_symlink():
        return None, expected_sha, "scope-policy-missing-or-unsafe"
    try:
        actual_sha = _file_sha256(path)
    except OSError:
        return None, expected_sha, "scope-policy-unreadable"
    if actual_sha != expected_sha:
        return None, expected_sha, "scope-policy-hash-mismatch"
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, expected_sha, "scope-policy-invalid-json"
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        return None, expected_sha, "scope-policy-invalid-schema"
    root = Path(str(policy.get("project_root") or "")).resolve(strict=False)
    if not root.is_absolute():
        return None, expected_sha, "scope-policy-invalid-project-root"
    return policy, expected_sha, ""


def _entry_path(project_root: Path, entry: dict) -> Path | None:
    ref = str(entry.get("ref") or "").strip()
    if not ref:
        return None
    candidate = (project_root / ref).resolve(strict=False)
    if not _within(candidate, project_root):
        return None
    return candidate


def _matches_entry(candidate: Path, entry_path: Path, kind: str) -> bool:
    candidate_key = os.path.normcase(str(candidate))
    entry_key = os.path.normcase(str(entry_path))
    if kind == "file":
        return candidate_key == entry_key
    try:
        return os.path.commonpath([candidate_key, entry_key]) == entry_key
    except ValueError:
        return False


def _unsafe_pattern(value: str) -> bool:
    pattern = value.replace("\\", "/").strip()
    if not pattern:
        return False
    if (
        pattern.startswith("/")
        or pattern.startswith("//")
        or pattern.startswith("~")
        or re.match(r"^[A-Za-z]:", pattern)
    ):
        return True
    return ".." in [part for part in pattern.split("/") if part]


def _scope_decision(payload: dict) -> dict:
    policy, digest, error = _load_scope_policy()
    if policy is None:
        return {
            "scope_policy_sha256": digest,
            "scope_decision": "denied",
            "scope_reason": error,
            "scope_resolved_target": "",
        }

    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return {
            "scope_policy_sha256": digest,
            "scope_decision": "denied",
            "scope_reason": "tool-input-not-a-mapping",
            "scope_resolved_target": "",
        }

    raw_target = ""
    if tool == "Read":
        raw_target = str(tool_input.get("file_path") or "")
    elif tool in {"Grep", "Glob"}:
        raw_target = str(tool_input.get("path") or "")
        if not raw_target:
            return {
                "scope_policy_sha256": digest,
                "scope_decision": "denied",
                "scope_reason": f"{tool.lower()}-path-required",
                "scope_resolved_target": "",
            }
        pattern_key = "glob" if tool == "Grep" else "pattern"
        pattern = str(tool_input.get(pattern_key) or "")
        if _unsafe_pattern(pattern):
            return {
                "scope_policy_sha256": digest,
                "scope_decision": "denied",
                "scope_reason": f"{tool.lower()}-pattern-escapes-scope",
                "scope_resolved_target": "",
            }

    if not raw_target:
        return {
            "scope_policy_sha256": digest,
            "scope_decision": "denied",
            "scope_reason": f"{tool.lower()}-target-missing",
            "scope_resolved_target": "",
        }

    project_root = Path(str(policy["project_root"])).resolve(strict=False)
    raw_path = Path(raw_target).expanduser()
    cwd = Path(str(payload.get("cwd") or project_root))
    candidate = (
        raw_path if raw_path.is_absolute() else cwd / raw_path
    ).resolve(strict=False)

    if not _within(candidate, project_root):
        return {
            "scope_policy_sha256": digest,
            "scope_decision": "denied",
            "scope_reason": "target-outside-project",
            "scope_resolved_target": str(candidate),
        }

    for entry in policy.get("excluded") or []:
        if not isinstance(entry, dict):
            continue
        path = _entry_path(project_root, entry)
        if path is None:
            continue
        if _matches_entry(candidate, path, str(entry.get("kind") or "")):
            return {
                "scope_policy_sha256": digest,
                "scope_decision": "denied",
                "scope_reason": "target-in-excluded-scope",
                "scope_resolved_target": str(candidate),
            }

    for entry in policy.get("allowed") or []:
        if not isinstance(entry, dict):
            continue
        path = _entry_path(project_root, entry)
        if path is None:
            continue
        if _matches_entry(candidate, path, str(entry.get("kind") or "")):
            return {
                "scope_policy_sha256": digest,
                "scope_decision": "allowed",
                "scope_reason": "target-in-allowed-scope",
                "scope_resolved_target": str(candidate),
            }

    return {
        "scope_policy_sha256": digest,
        "scope_decision": "denied",
        "scope_reason": "target-outside-allowed-scope",
        "scope_resolved_target": str(candidate),
    }


def _session_start_output(payload: dict) -> dict | None:
    if str(payload.get("hook_event_name") or "") != "SessionStart":
        return None
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if not project_dir:
        project_dir = str(payload.get("cwd") or "").strip()
    if not project_dir:
        return None
    runtime = Path(project_dir).resolve() / ".harness" / "sitter" / "runtime"
    if not runtime.is_dir():
        return None
    runtime_text = str(runtime)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    try:
        from session_start_hook import build_hook_output

        return build_hook_output(payload, project_root=Path(project_dir))
    except (ImportError, OSError, ValueError) as error:
        print(f"Sitter Claude SessionStart continuity unavailable: {error}", file=sys.stderr)
        return None


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        return _deny(f"Sitter Claude hook received invalid JSON: {error}")
    if not isinstance(payload, dict):
        return _deny("Sitter Claude hook input must be a JSON object")

    event = str(payload.get("hook_event_name") or "")
    mode = os.environ.get("SITTER_CLAUDE_EXECUTION_MODE", "").strip()
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or "").strip()
    deny_message = ""

    if event == "PreToolUse":
        tool = str(payload.get("tool_name") or "")
        if mode == "native" and not agent_id:
            if tool != "Agent":
                deny_message = f"Sitter governed parent denied tool: {tool or '<missing>'}"
        elif tool not in _ALLOWED_CHILD_TOOLS:
            deny_message = f"Sitter governed Agent denied tool: {tool or '<missing>'}"
        elif os.environ.get(_SCOPE_REQUIRED_ENV, "").strip() == "1":
            payload.update(_scope_decision(payload))
            if payload.get("scope_decision") != "allowed":
                deny_message = (
                    "Sitter governed Agent denied filesystem scope: "
                    f"{payload.get('scope_reason') or 'unknown'}"
                )

    if event in _BLOCKED_EVENTS:
        deny_message = f"Sitter governed Agent denied lifecycle event: {event}"

    try:
        _write_event(_sanitize(payload))
    except OSError as error:
        return _deny(f"Sitter Claude hook could not persist evidence: {error}")

    if deny_message:
        return _deny(deny_message)

    output = _session_start_output(payload)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
