from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from active_task_index import session_start_payload
from project_context import resolve_project_context


_SMOKE_EVIDENCE_ENV = "SITTER_SESSION_START_EVIDENCE_DIR"


def _project_root(cwd: str | Path) -> Path:
    path = Path(cwd).expanduser().resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".harness" / "sitter" / "manifest-lock.yaml").is_file():
            return candidate
    raise ValueError(f"cannot resolve Sitter project root from {path}")


def continuity_text(payload: dict) -> str:
    tasks = payload.get("active_tasks") or []
    if not tasks:
        return ""
    lines = [
        "Sitter session continuity state:",
        f"- Active governed Task count: {len(tasks)}.",
    ]
    for task in tasks:
        lines.append(
            f"- Active Task `{task['id']}`: {task['title']} "
            f"(orchestrator provider: {task['provider']})."
        )
    resume = payload.get("resume_hint")
    if resume:
        lines.append(
            f"- The bounded Active Task Index has exactly one Task, so an explicit request "
            f"to continue the prior governed work can recover `{resume}` rather than create a new Task."
        )
    else:
        lines.append(
            "- More than one active Task exists; a continuation must match the user's subject "
            "to one of these Task IDs before resuming it."
        )
    lines.extend(
        [
            "- This context came only from `.agent-work/_context/active-tasks.yaml`.",
            "- Archived Task history was not scanned and durable Project Knowledge/Memory was not loaded.",
            "- Durable Memory remains progressive-disclosure context and is retrieved only when the current work needs it.",
        ]
    )
    return "\n".join(lines)


def _optional_evidence_dir(root: Path) -> Path | None:
    raw = os.environ.get(_SMOKE_EVIDENCE_ENV, "").strip()
    if not raw:
        return None
    value = Path(raw).expanduser()
    path = value.resolve() if value.is_absolute() else (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"{_SMOKE_EVIDENCE_ENV} must remain inside the project root"
        ) from error
    return path


def _record_optional_evidence(
    root: Path,
    event: dict,
    payload: dict,
    additional_context: str,
) -> None:
    directory = _optional_evidence_dir(root)
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "hook_event_name": "SessionStart",
        "source": str(event.get("source") or ""),
        "session_id": str(event.get("session_id") or event.get("sessionId") or ""),
        "cwd": str(event.get("cwd") or root),
        "active_task_count": int(payload.get("active_task_count") or 0),
        "active_task_ids": [
            str(item.get("id"))
            for item in (payload.get("active_tasks") or [])
            if isinstance(item, dict) and item.get("id")
        ],
        "history_scanned": bool(payload.get("history_scanned", False)),
        "durable_memory_loaded": bool(payload.get("durable_memory_loaded", False)),
        "additional_context": additional_context,
    }
    path = directory / f"session-start-{time.time_ns()}-{uuid.uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            json.dump(record, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def build_hook_output(event: dict, *, project_root: Path | None = None) -> dict | None:
    if str(event.get("hook_event_name") or "") != "SessionStart":
        return None
    cwd = str(event.get("cwd") or "").strip()
    if not cwd and project_root is None:
        return None
    root = project_root.resolve() if project_root is not None else _project_root(cwd)
    context = resolve_project_context(root)
    payload = session_start_payload(context)
    text = continuity_text(payload)
    if not text:
        return None
    _record_optional_evidence(root, event, payload, text)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        print(f"Sitter SessionStart hook received invalid JSON: {error}", file=sys.stderr)
        return 1
    if not isinstance(event, dict):
        print("Sitter SessionStart hook input must be a JSON object", file=sys.stderr)
        return 1
    try:
        output = build_hook_output(event)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Continuity context is advisory recovery state. A hook failure must not
        # make the host session unusable; emit a diagnostic only.
        print(f"Sitter SessionStart continuity unavailable: {error}", file=sys.stderr)
        return 0
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())