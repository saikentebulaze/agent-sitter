from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import install


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"


def create_git_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    return project


def create_task(project: Path, task_id: str = "resume-task") -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNTIME / "create_task.py"),
            task_id,
            "--title",
            "Resume the bounded task",
            "--entry",
            "investigation",
            "--signature",
            task_id,
            "--project",
            str(project),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)


class V6SessionStartTests(unittest.TestCase):
    def test_codex_projection_adds_parseable_cross_platform_session_start_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_git_project(Path(directory))
            install.install(project, dry_run=False, provider_ids=("codex",), trust_project=True)
            config_path = project / ".codex" / "config.toml"
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            session = config["hooks"]["SessionStart"]
            self.assertEqual(len(session), 1)
            self.assertEqual(session[0]["matcher"], "^(startup|resume|clear|compact)$")
            handler = session[0]["hooks"][0]
            self.assertEqual(handler["type"], "command")
            self.assertIn("session_start_hook.py", handler["command"])
            self.assertIn("session_start_hook.py", handler["command_windows"])
            self.assertGreater(handler["additionalContextLimit"], 0)

    def test_shared_session_start_hook_reads_only_active_index_and_emits_resume_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_git_project(Path(directory))
            install.install(project, dry_run=False, provider_ids=("codex",), trust_project=True)
            create_task(project)
            hook = project / ".harness" / "sitter" / "runtime" / "session_start_hook.py"
            event = {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "cwd": str(project),
                "session_id": "fixture-session",
            }
            result = subprocess.run(
                [sys.executable, str(hook)],
                cwd=project,
                input=json.dumps(event),
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("resume-task", context)
            self.assertIn("Active Task Index", context)
            self.assertIn("Archived Task history was not scanned", context)
            self.assertIn("durable Project Knowledge/Memory was not loaded", context)

    def test_zero_active_tasks_emit_no_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_git_project(Path(directory))
            install.install(project, dry_run=False, provider_ids=("codex",), trust_project=True)
            hook = project / ".harness" / "sitter" / "runtime" / "session_start_hook.py"
            result = subprocess.run(
                [sys.executable, str(hook)],
                cwd=project,
                input=json.dumps(
                    {
                        "hook_event_name": "SessionStart",
                        "source": "startup",
                        "cwd": str(project),
                    }
                ),
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "")

    def test_claude_project_hook_emits_same_bounded_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_git_project(Path(directory))
            install.install(project, dry_run=False, provider_ids=("claude",))
            create_task(project)
            hook = project / ".claude" / "hooks" / "governance-runtime-hook.py"
            env = os.environ.copy()
            env["CLAUDE_PROJECT_DIR"] = str(project)
            result = subprocess.run(
                [sys.executable, str(hook)],
                cwd=project,
                input=json.dumps(
                    {
                        "hook_event_name": "SessionStart",
                        "source": "startup",
                        "cwd": str(project),
                        "session_id": "claude-session",
                    }
                ),
                text=True,
                encoding="utf-8",
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("resume-task", context)
            self.assertIn("Archived Task history was not scanned", context)


if __name__ == "__main__":
    unittest.main()
