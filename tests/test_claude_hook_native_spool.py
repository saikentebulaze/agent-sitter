from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "adapters" / "default" / "claude" / "hooks" / "governance-runtime-hook.py"


class ClaudeHookNativeEvidenceTests(unittest.TestCase):
    def run_hook(self, directory: Path, payload: dict) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update({
            "SITTER_CLAUDE_EVIDENCE_DIR": str(directory),
            "SITTER_CLAUDE_ATTEMPT_NONCE": "native-attempt",
            "SITTER_CLAUDE_EXECUTION_MODE": "native",
        })
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
        )

    def envelope(self, directory: Path) -> dict:
        files = list(directory.glob("*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_parent_agent_invocation_is_recorded_and_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, {
                "hook_event_name": "PreToolUse",
                "tool_name": "Agent",
                "tool_use_id": "toolu-one",
                "tool_input": {"subagent_type": "context-scout"},
            })
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = self.envelope(root)
            self.assertEqual(envelope["attempt_nonce"], "native-attempt")
            self.assertEqual(envelope["execution_mode"], "native")
            self.assertEqual(envelope["event"]["tool_name"], "Agent")

    def test_parent_non_agent_tool_is_recorded_then_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Read"})
            self.assertEqual(result.returncode, 2)
            self.assertIn("governed parent denied tool", result.stderr)
            self.assertEqual(self.envelope(root)["event"]["tool_name"], "Read")

    def test_child_allowed_tool_is_recorded_and_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Read", "agent_id": "agent-one"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.envelope(root)["event"]["agent_id"], "agent-one")

    def test_child_forbidden_tool_is_recorded_then_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_id": "agent-one"})
            self.assertEqual(result.returncode, 2)
            self.assertIn("governed Agent denied tool", result.stderr)
            self.assertEqual(self.envelope(root)["event"]["tool_name"], "Bash")


if __name__ == "__main__":
    unittest.main()
