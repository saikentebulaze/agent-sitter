from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "v6-runtime-smoke.py"
SPEC = importlib.util.spec_from_file_location("v6_runtime_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class V6RuntimeSmokeProtocolTests(unittest.TestCase):
    def test_offline_attestation_validation_uses_verified_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            request_ref = ".agent-work/task/delegations/dlg-001/attempt-01.request.yaml"
            record_ref = ".agent-work/task/delegations/dlg-001/attempt-01.record.yaml"
            request_path = project / request_ref
            record_path = project / record_ref
            request_path.parent.mkdir(parents=True)
            request_path.write_text(
                "requested_profile: {}\nproject_root: C:/untrusted-fixture-value\n",
                encoding="utf-8",
            )
            record_path.write_text("attestation:\n  schema_version: 2\n", encoding="utf-8")
            completed = {
                "context": {"request_ref": request_ref},
                "record_ref": record_ref,
                "output_ref": ".agent-work/task/delegations/dlg-001/attempt-01.result.md",
            }

            def validate(packet: dict, attestation: dict) -> SimpleNamespace:
                self.assertEqual(packet["project_root"], str(project))
                return SimpleNamespace(
                    provider="codex",
                    role_id="context_scout",
                    contract=SimpleNamespace(
                        context_isolation="fresh",
                        write_isolation="os-readonly",
                        attestation_strength="runtime-observed",
                    ),
                )

            runtime = ROOT / "runtime"
            if str(runtime) not in sys.path:
                sys.path.insert(0, str(runtime))
            with mock.patch(
                "provider_attestation.validate_provider_attestation",
                side_effect=validate,
            ):
                evidence = SMOKE._validate_completed_attestation(project, completed)
            self.assertEqual(evidence["provider"], "codex")

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

    def test_only_matching_fresh_parent_startup_event_counts_as_session_proof(self) -> None:
        task_id = "v6-runtime-smoke"
        canary = "sitter-v6-secret"
        base = {
            "active_task_ids": [task_id],
            "additional_context": f"active Task {task_id} title contains {canary}",
            "history_scanned": False,
            "durable_memory_loaded": False,
        }
        startup = {**base, "source": "startup"}
        later_child = {**base, "source": "resume"}
        wrong_task = {**startup, "active_task_ids": ["another-task"]}
        eager_memory = {**startup, "durable_memory_loaded": True}

        self.assertTrue(SMOKE._session_event_matches(startup, task_id, canary))
        self.assertFalse(SMOKE._session_event_matches(later_child, task_id, canary))
        self.assertFalse(SMOKE._session_event_matches(wrong_task, task_id, canary))
        self.assertFalse(SMOKE._session_event_matches(eager_memory, task_id, canary))


if __name__ == "__main__":
    unittest.main()
