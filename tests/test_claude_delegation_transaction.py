from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from claude_test_support import valid_claude_attestation  # noqa: E402
from delegation_transaction import DelegationTransactionError, _canonical_sha256, authorize_delegation, record_delegation_result, request_delegation, supplement_delegation_context  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from work_graph import load_yaml  # noqa: E402


class ClaudeDelegationTransactionTests(unittest.TestCase):
    def prepare(self, project: Path):
        context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
        source = project / "src" / "anchor.cpp"; source.parent.mkdir(); source.write_text("// bounded anchor\n", encoding="utf-8")
        task_root = initialize_provider_task(context, task_id="claude-delegation", title="Claude delegation", entry="investigation", provider_id="claude", signature="claude-delegation")
        authorize_delegation(context, "claude-delegation", decision="required", scopes=["readonly-exploration"], evidence="user-authorized", parent_model="sonnet", parent_tier="low")
        return context, task_root

    def request(self, context):
        return request_delegation(context, "claude-delegation", role="context_scout", target_type="investigation", target_ref="inv-001", purpose="trace", question="Which file owns it?", decision_supported="Decide context.", include=["src/anchor.cpp"], exclude=["unrelated"], start_refs=["src/anchor.cpp"], confirmed_facts=["The anchor exists."])

    def attestation(self, project, packet_path, *, provider_schema="claude", request_hash=None):
        packet = load_yaml(packet_path); canonical = request_hash or _canonical_sha256(packet); path = project / "runtime-attestation.yaml"
        if provider_schema == "codex":
            data = {"schema_version": 2, "execution": {"method": "native-subagent", "collector": "codex-rollout-app-server-v1", "spawn_call_id": "call-1", "session_ref": "native-thread:wrong-provider"}, "observed": {}, "evidence": {"source": "verified-combined", "request_sha256": canonical}}
        else:
            data = valid_claude_attestation(packet, request_hash=canonical, session_id="dlg-001-attempt-01")
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"); return path

    def test_request_freezes_claude_provider_native_profile_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory); context,task_root=self.prepare(project); packet=load_yaml(self.request(context)); requested=packet["requested_profile"]
            self.assertEqual(packet["schema_version"],2); self.assertEqual(packet["runtime"]["provider"],"claude"); self.assertEqual(requested["model_resolution_mode"],"native")
            for key in ("profile_source_sha256","model_config_sha256","agent_projection_sha256","settings_projection_sha256","hook_projection_sha256"): self.assertEqual(len(requested[key]),64)
            planned=load_yaml(task_root/"task.yaml")["delegation"]["planned"][0]; self.assertEqual((planned["provider"],planned["tier"],planned["model"]),("claude","low","haiku"))

    def test_completed_result_preserves_claude_execution_method(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory); context,task_root=self.prepare(project); packet_path=self.request(context); artifact=project/"result.md"
            artifact.write_text("# Key conclusions\n\nBounded.\n\n# Evidence index\n\n- src/anchor.cpp\n\n# Unresolved questions\n\nNone.\n",encoding="utf-8")
            output,outcome,repeated=record_delegation_result(context,"claude-delegation","dlg-001",artifact=artifact,outcome="completed",evidence_ref="claude-session:dlg-001-attempt-01",attestation=self.attestation(project,packet_path))
            self.assertEqual(outcome,"completed"); self.assertFalse(repeated); self.assertTrue(output.is_file())
            completed=load_yaml(task_root/"task.yaml")["delegation"]["completed"][0]; self.assertEqual((completed["provider"],completed["execution"]),("claude","claude-managed-agent"))

    def test_attestation_for_another_request_is_rejected_before_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory); context,task_root=self.prepare(project); packet_path=self.request(context); artifact=project/"result.md"; artifact.write_text("x\n")
            with self.assertRaisesRegex(DelegationTransactionError,"request_sha256 does not match"):
                record_delegation_result(context,"claude-delegation","dlg-001",artifact=artifact,outcome="completed",evidence_ref="claude-session:x",attestation=self.attestation(project,packet_path,request_hash="f"*64))
            self.assertFalse(load_yaml(task_root/"task.yaml")["delegation"]["completed"])

    def test_codex_attestation_cannot_complete_claude_request(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory); context,task_root=self.prepare(project); packet_path=self.request(context); artifact=project/"result.md"; artifact.write_text("x\n")
            with self.assertRaisesRegex(DelegationTransactionError,"unsupported execution method"):
                record_delegation_result(context,"claude-delegation","dlg-001",artifact=artifact,outcome="completed",evidence_ref="native-thread:wrong",attestation=self.attestation(project,packet_path,provider_schema="codex"))
            self.assertFalse(load_yaml(task_root/"task.yaml")["delegation"]["completed"])

    def test_need_context_creates_provider_stable_second_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory); context,task_root=self.prepare(project); first=self.request(context); artifact=project/"need.md"; artifact.write_text("NEED_CONTEXT: src/additional.cpp\n")
            record_delegation_result(context,"claude-delegation","dlg-001",artifact=artifact,outcome="need-context",evidence_ref="claude-session:dlg-001-attempt-01",attestation=self.attestation(project,first))
            (project/"src"/"additional.cpp").write_text("// supplement\n")
            second=supplement_delegation_context(context,"claude-delegation","dlg-001",refs=["src/additional.cpp"],reasons=["requested"])
            first_packet=load_yaml(first); second_packet=load_yaml(second); self.assertEqual(second_packet["requested_profile"],first_packet["requested_profile"]); self.assertEqual(second_packet["runtime"]["provider"],"claude")
            self.assertEqual(load_yaml(task_root/"task.yaml")["delegation"]["planned"][0]["context"]["attempt"],2)


if __name__ == "__main__": unittest.main()
