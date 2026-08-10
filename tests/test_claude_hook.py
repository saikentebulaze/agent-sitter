from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "adapters" / "default" / "claude" / "hooks" / "governance-runtime-hook.py"


class ClaudeHookTests(unittest.TestCase):
    def run_hook(
        self,
        directory: Path,
        payload: dict | str,
        *,
        nonce: str = "attempt-test",
        mode: str = "managed",
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["SITTER_CLAUDE_EVIDENCE_DIR"] = str(directory)
        env["SITTER_CLAUDE_ATTEMPT_NONCE"] = nonce
        env["SITTER_CLAUDE_EXECUTION_MODE"] = mode
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=stdin,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
        )

    def events(self, directory: Path) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]

    def test_allowed_read_tool_is_recorded_and_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Read", "session_id": "session-one"})
            self.assertEqual(result.returncode, 0, result.stderr)
            events = self.events(root)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["schema_version"], 2)
            self.assertEqual(events[0]["attempt_nonce"], "attempt-test")
            self.assertEqual(events[0]["execution_mode"], "managed")
            self.assertEqual(events[0]["event"]["tool_name"], "Read")

    def test_forbidden_bash_tool_is_recorded_then_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "session-one"})
            self.assertEqual(result.returncode, 2)
            self.assertIn("denied tool", result.stderr)
            self.assertEqual(self.events(root)[0]["event"]["tool_name"], "Bash")

    def test_compaction_and_worktree_are_recorded_then_blocked(self) -> None:
        for event in ("PreCompact", "WorktreeCreate"):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = self.run_hook(root, {"hook_event_name": event, "session_id": "session-one"})
                self.assertEqual(result.returncode, 2)
                self.assertIn("denied lifecycle event", result.stderr)
                self.assertEqual(self.events(root)[0]["event"]["hook_event_name"], event)

    def test_lone_surrogate_in_event_payload_is_recorded_without_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-one",
                "last_assistant_message": "final \udc94 result",
                "session_id": "session-one",
            }
            result = self.run_hook(root, payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = self.events(root)
            self.assertEqual(len(events), 1)
            recorded = events[0]["event"]["last_assistant_message"]
            self.assertNotIn("\udc94", recorded)
            self.assertIn("result", recorded)

    def test_invalid_json_fails_without_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, "not-json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid JSON", result.stderr)
            self.assertEqual(list(root.glob("*.json")), [])

    def test_missing_complete_evidence_environment_does_not_create_files(self) -> None:
        for missing in ("SITTER_CLAUDE_EVIDENCE_DIR", "SITTER_CLAUDE_ATTEMPT_NONCE", "SITTER_CLAUDE_EXECUTION_MODE"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                env = os.environ.copy()
                env.update({
                    "SITTER_CLAUDE_EVIDENCE_DIR": str(root),
                    "SITTER_CLAUDE_ATTEMPT_NONCE": "nonce",
                    "SITTER_CLAUDE_EXECUTION_MODE": "managed",
                })
                env.pop(missing, None)
                result = subprocess.run(
                    [sys.executable, str(HOOK)],
                    input=json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Read"}),
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(list(root.glob("*.json")), [])

    def test_concurrent_events_never_overwrite_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def invoke(index: int) -> subprocess.CompletedProcess[str]:
                return self.run_hook(root, {"hook_event_name": "PostToolUse", "tool_name": "Read", "session_id": "session-one", "sequence": index})
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(invoke, range(20)))
            self.assertTrue(all(item.returncode == 0 for item in results))
            events = self.events(root)
            self.assertEqual(len(events), 20)
            self.assertEqual({item["event"]["sequence"] for item in events}, set(range(20)))


if __name__ == "__main__":
    unittest.main()
