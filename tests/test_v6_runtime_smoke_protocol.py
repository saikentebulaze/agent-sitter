from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-runtime-smoke.py"
SPEC = importlib.util.spec_from_file_location("v6_runtime_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class V6RuntimeSmokeProtocolTests(unittest.TestCase):
    def test_prepare_cannot_fake_a_real_runtime_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "codex-smoke"
            prepared = SMOKE.prepare(project, "codex", False)
            self.assertEqual(prepared["status"], "PREPARED_NOT_RUN")
            self.assertEqual(prepared["provider"], "codex")
            self.assertFalse((project / ".agent-work" / "_runtime-smoke" / "session-start").exists())

            manifest = json.loads(
                (project / ".agent-work" / "_runtime-smoke" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            prompt = (project / ".agent-work" / "_runtime-smoke" / "PROMPT.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(manifest["session_start_canary"], prompt)
            self.assertNotIn(manifest["task_id"], prompt)
            self.assertEqual(
                manifest["session_start_evidence_env"],
                "SITTER_SESSION_START_EVIDENCE_DIR",
            )

            verified = SMOKE.verify(project)
            self.assertEqual(verified["status"], "FAIL")
            self.assertFalse(verified["checks"]["session_start_evidence_present"])
            self.assertFalse(verified["checks"]["agent_receipt_present"])
            self.assertTrue(verified["l3_black_box"])

    def test_codex_and_claude_prepare_the_same_provider_neutral_parent_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / "codex"
            claude = root / "claude"
            SMOKE.prepare(codex, "codex", False)
            SMOKE.prepare(claude, "claude", False)
            codex_prompt = (
                codex / ".agent-work" / "_runtime-smoke" / "PROMPT.md"
            ).read_bytes()
            claude_prompt = (
                claude / ".agent-work" / "_runtime-smoke" / "PROMPT.md"
            ).read_bytes()
            self.assertEqual(codex_prompt, claude_prompt)

            codex_manifest = json.loads(
                (codex / ".agent-work" / "_runtime-smoke" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            claude_manifest = json.loads(
                (claude / ".agent-work" / "_runtime-smoke" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(codex_manifest["provider"], "codex")
            self.assertEqual(claude_manifest["provider"], "claude")
            self.assertEqual(
                codex_manifest["commands"]["context_scout"][3:],
                claude_manifest["commands"]["context_scout"][3:],
            )


if __name__ == "__main__":
    unittest.main()
