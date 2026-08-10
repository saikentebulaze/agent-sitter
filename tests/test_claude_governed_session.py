from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from providers.claude.governed_session import (  # noqa: E402
    ClaudeGovernedSessionError,
    build_native_parent_command,
)
from providers.claude.native_runtime import (  # noqa: E402
    native_message,
    native_parent_instruction,
)


class ClaudeGovernedSessionTests(unittest.TestCase):
    def test_child_prompt_and_parent_instruction_are_separate(self) -> None:
        context = ProjectContext(ROOT, ROOT, ROOT / "adapters" / "default")
        request = ROOT / ".agent-work" / "test" / "request.yaml"
        child = native_message(context, request, "nonce-one")
        parent = native_parent_instruction(
            runtime_role="context-scout",
            model_selector="haiku",
            child_prompt=child,
        )
        self.assertIn("Sitter_ATTEMPT_NONCE=nonce-one", child)
        self.assertNotIn("Execute exactly one Agent", child)
        self.assertIn("Execute exactly one Agent", parent)
        self.assertIn("Set run_in_background exactly to false", parent)
        self.assertIn(child, parent)

    def test_parent_command_runs_frozen_instruction_noninteractively_and_keeps_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            settings = project / ".harness" / "pkg" / "governed-settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text("{}\n", encoding="utf-8")
            mcp = project / "empty-mcp.json"
            mcp.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
            contract = {
                "parent_session_id": "session-one",
                "parent_instruction": "Invoke the frozen Agent.",
                "governed_settings_ref": ".harness/pkg/governed-settings.json",
            }
            command = build_native_parent_command(
                context,
                contract,
                command_prefix=("claude-test",),
                mcp_config=mcp,
            )
            self.assertEqual(command[0], "claude-test")
            self.assertEqual(command[command.index("-p") + 1], contract["parent_instruction"])
            tools = command[command.index("--tools") + 1]
            self.assertEqual(
                tools,
                "Agent,Read,Grep,Glob",
                "the governed parent must advertise the child's read-only tools "
                "so subagent spawn tool resolution succeeds",
            )
            disallowed = command[command.index("--disallowedTools") + 1]
            self.assertNotIn("Read", disallowed.split(","))
            self.assertNotIn("Grep", disallowed.split(","))
            self.assertNotIn("Glob", disallowed.split(","))
            self.assertIn("--output-format", command)
            self.assertIn("stream-json", command)
            self.assertNotIn("--no-session-persistence", command)

    def test_parent_command_requires_frozen_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            settings = project / "governed-settings.json"
            settings.write_text("{}\n", encoding="utf-8")
            context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
            with self.assertRaisesRegex(
                ClaudeGovernedSessionError,
                "no frozen parent instruction",
            ):
                build_native_parent_command(
                    context,
                    {
                        "parent_session_id": "session-one",
                        "governed_settings_ref": "governed-settings.json",
                    },
                    command_prefix=("claude-test",),
                    mcp_config=project / "empty-mcp.json",
                )


if __name__ == "__main__":
    unittest.main()
