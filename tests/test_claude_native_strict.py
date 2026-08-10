from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from claude_test_support import claude_packet, valid_claude_attestation  # noqa: E402
from core.provider_registry import get_provider  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from providers.claude import native_runtime_strict  # noqa: E402
from providers.claude.native_runtime import ClaudeNativeRuntimeError  # noqa: E402


class ClaudeNativeStrictTests(unittest.TestCase):
    def context(self):
        return ProjectContext(ROOT, ROOT, ROOT / "adapters" / "default")

    def packet_and_attestation(self):
        packet = claude_packet(
            get_provider("claude").load_role_profile(
                self.context(),
                "context_scout",
            )
        )
        attestation = valid_claude_attestation(
            packet,
            method="claude-native-subagent",
        )
        attestation["observed"]["cwd"] = str(ROOT)
        raw = {
            "agent_id": "agent-one",
            "invocation": {
                "requested_model": attestation["observed"]["model_selector"],
            },
            "hook_events": [
                {
                    "hook_event_name": "SubagentStart",
                    "agent_id": "agent-one",
                },
                {
                    "hook_event_name": "SubagentStop",
                    "agent_id": "agent-one",
                },
            ],
        }
        return packet, attestation, raw

    def collect(self, packet, attestation, raw):
        with mock.patch.object(
            native_runtime_strict,
            "collect_native_base",
            return_value=("output", attestation, raw),
        ):
            return native_runtime_strict.collect_native(
                self.context(),
                ROOT / "request.yaml",
                packet,
            )

    def test_valid_single_agent_project_cwd_is_accepted(self):
        packet, attestation, raw = self.packet_and_attestation()
        output, actual, actual_raw = self.collect(packet, attestation, raw)
        self.assertEqual(output, "output")
        self.assertIs(actual, attestation)
        self.assertIs(actual_raw, raw)

    def test_omitted_or_wrong_invocation_model_is_rejected(self):
        for value in ("", "opus"):
            with self.subTest(value=value):
                packet, attestation, raw = self.packet_and_attestation()
                raw["invocation"]["requested_model"] = value
                with self.assertRaisesRegex(
                    ClaudeNativeRuntimeError,
                    "explicitly request the frozen model selector",
                ):
                    self.collect(packet, attestation, raw)

    def test_wrong_cwd_is_rejected(self):
        packet, attestation, raw = self.packet_and_attestation()
        attestation["observed"]["cwd"] = str(ROOT.parent)
        with self.assertRaisesRegex(
            ClaudeNativeRuntimeError,
            "wrong working directory",
        ):
            self.collect(packet, attestation, raw)

    def test_second_subagent_start_is_rejected(self):
        packet, attestation, raw = self.packet_and_attestation()
        raw["hook_events"].insert(
            1,
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-two",
            },
        )
        with self.assertRaisesRegex(
            ClaudeNativeRuntimeError,
            "exactly one SubagentStart",
        ):
            self.collect(packet, attestation, raw)

    def test_another_agent_identity_is_rejected(self):
        packet, attestation, raw = self.packet_and_attestation()
        raw["hook_events"].append(
            {
                "hook_event_name": "PostToolUse",
                "agent_id": "agent-two",
                "tool_name": "Read",
            }
        )
        with self.assertRaisesRegex(
            ClaudeNativeRuntimeError,
            "another Agent identity",
        ):
            self.collect(packet, attestation, raw)


if __name__ == "__main__":
    unittest.main()
