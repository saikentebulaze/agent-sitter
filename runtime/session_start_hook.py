from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from active_task_index import session_start_payload
from project_context import resolve_project_context


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
