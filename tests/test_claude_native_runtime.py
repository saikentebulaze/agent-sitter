from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

import install

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from delegation_transaction import authorize_delegation, request_delegation  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from providers.claude.native_runtime import ClaudeNativeRuntimeError, collect_native, prepare_native  # noqa: E402
from work_graph import load_yaml  # noqa: E402


class ClaudeNativeRuntimeTests(unittest.TestCase):
    def prepare(self, directory: str):
        project = Path(directory) / "project"; project.mkdir()
        subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
        install.install(project, dry_run=False, provider_ids=("claude",))
        package = project / ".harness" / "sitter"
        context = ProjectContext(package, project, package / "adapters" / "default")
        anchor = project / "src" / "anchor.cpp"; anchor.parent.mkdir(); anchor.write_text("// anchor\n", encoding="utf-8")
        initialize_provider_task(context, task_id="native-runtime", title="Native runtime", entry="investigation", provider_id="claude", signature="native-runtime")
        authorize_delegation(context, "native-runtime", decision="required", scopes=["readonly-exploration"], evidence="authorized", parent_model="haiku", parent_tier="low")
        request_path = request_delegation(context, "native-runtime", role="context_scout", target_type="investigation", target_ref="inv-001", purpose="native fixture", question="What owns the anchor?", decision_supported="Decide whether context is sufficient.", include=["src/anchor.cpp"], exclude=[], start_refs=["src/anchor.cpp"], confirmed_facts=["The anchor exists."])
        packet = load_yaml(request_path); contract_path, contract = prepare_native(context, request_path, packet)
        return project, context, request_path, packet, contract_path, contract

    def parent_transcript(self, project, contract):
        path = project / ".agent-work" / "parent.jsonl"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type":"user","sessionId":contract["parent_session_id"],"cwd":str(project),"message":{"role":"user","content":contract["message"]}})+"\n", encoding="utf-8")
        return path

    def child_transcript(self, project, contract, agent_id="agent-one", model="haiku", final="Native bounded result.", tool="Read", second_cwd=None, second_model=None, malformed=False):
        path = project / ".agent-work" / f"{agent_id}.child.jsonl"
        rows=[{"type":"user","agentId":agent_id,"cwd":str(project),"sessionId":contract["parent_session_id"],"message":{"role":"user","content":contract["message"]}},
              {"type":"assistant","agentId":agent_id,"cwd":second_cwd or str(project),"sessionId":contract["parent_session_id"],"message":{"id":"m1","role":"assistant","model":model,"content":[{"type":"tool_use","name":tool},{"type":"text","text":final}]}}]
        if second_model: rows.append({"type":"assistant","agentId":agent_id,"cwd":str(project),"sessionId":contract["parent_session_id"],"message":{"id":"m2","role":"assistant","model":second_model,"content":[{"type":"text","text":final}]}})
        text="\n".join(json.dumps(row) for row in rows)+"\n"; text += "not-json\n" if malformed else ""; path.write_text(text,encoding="utf-8"); return path

    def event(self, contract, index, event):
        directory=Path(contract["evidence_dir"]); directory.mkdir(parents=True,exist_ok=True)
        envelope={"schema_version":2,"attempt_nonce":contract["attempt_nonce"],"execution_mode":"native","recorded_at_ns":int(contract["created_at_ns"])+index+1,"event":event}
        (directory/f"{index:03d}.json").write_text(json.dumps(envelope)+"\n",encoding="utf-8")

    def lifecycle(self, project, contract, *, model="haiku", resolved=None, final="Native bounded result.", child_tool="Read", prompt=None, status="completed", same_transcript=False, extra_start=False, second_cwd=None, second_model=None, malformed=False, run_background=False, omit_background=False):
        agent="agent-one"; tool_use="toolu-one"; parent=self.parent_transcript(project,contract)
        child=self.child_transcript(project,contract,agent_id=agent,model=model,final=final,tool=child_tool,second_cwd=second_cwd,second_model=second_model,malformed=malformed)
        if same_transcript: child=parent
        common={"session_id":contract["parent_session_id"],"transcript_path":str(parent)}
        tool_input={"prompt":contract["message"] if prompt is None else prompt,"subagent_type":contract["runtime_role"],"model":contract["model_selector"]}
        if not omit_background: tool_input["run_in_background"]=run_background
        events=[
          {"hook_event_name":"PreToolUse","tool_name":"Agent","tool_use_id":tool_use,"tool_input":tool_input,**common},
          {"hook_event_name":"SubagentStart","agent_id":agent,"agent_type":contract["runtime_role"],**common},
          {"hook_event_name":"PreToolUse","agent_id":agent,"tool_name":child_tool,**common},
          {"hook_event_name":"PostToolUse","agent_id":agent,"tool_name":child_tool,**common},
          {"hook_event_name":"SubagentStop","agent_id":agent,"agent_type":contract["runtime_role"],"agent_transcript_path":str(child),"last_assistant_message":final,**common},
          {"hook_event_name":"PostToolUse","tool_name":"Agent","tool_use_id":tool_use,"tool_response":{"status":status,"agentId":agent,"resolvedModel":resolved or model,"modelsUsed":[model]},**common},
        ]
        if extra_start: events.insert(2,{"hook_event_name":"SubagentStart","agent_id":"agent-two","agent_type":contract["runtime_role"],**common})
        for i,value in enumerate(events): self.event(contract,i,value)
        return parent,child

    def test_prepare_freezes_nonce_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            _,context,request,packet,path,first=self.prepare(d); path2,second=prepare_native(context,request,packet)
            self.assertEqual(path,path2); self.assertEqual(first,second); self.assertIn(first["attempt_nonce"],first["message"]); self.assertEqual(first["schema_version"],2)

    def test_exact_invocation_and_child_transcript_are_attested(self):
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); parent,child=self.lifecycle(project,contract)
            output,att,raw=collect_native(context,request,packet); self.assertEqual(output,"Native bounded result."); self.assertEqual(att["schema_version"],2)
            self.assertEqual(att["execution"]["collector"],"claude-invocation-hooks-transcript-v2")
            self.assertTrue(os.path.samefile(raw["parent_transcript_ref"], parent))
            self.assertTrue(os.path.samefile(raw["child_transcript_ref"], child))

    def test_parent_and_child_transcripts_must_differ(self):
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,same_transcript=True)
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"paths must differ"): collect_native(context,request,packet)

    def test_wrong_prompt_cannot_claim_same_role(self):
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,prompt="another task")
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"matching parent PreToolUse"): collect_native(context,request,packet)

    def test_model_reporting_variants_are_same_identity(self):
        # Proxies report the same model in different forms: the child
        # transcript carries the base name ("sonnet") while the parent
        # resolvedModel carries a context-window annotation ("sonnet[1m]").
        # The binder must treat these as one identity rather than a drift.
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d)
            self.lifecycle(project,contract,model="haiku",resolved="haiku[1m]")
            output,att,raw=collect_native(context,request,packet)
            self.assertEqual(output,"Native bounded result.")

    def test_marker_wrapped_prompt_from_real_parent_still_matches(self):
        # A real governed parent receives the child prompt wrapped in the
        # harness BEGIN/END markers embedded in the frozen parent instruction
        # and passes that wrapped text byte-for-byte as the Agent prompt. The
        # binder must strip those harness-injected markers before comparing
        # to the frozen contract message; otherwise the chain is attested as
        # unmatched even though the parent behaved exactly as instructed.
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d)
            marked = (
                "----- Sitter CHILD PROMPT BEGIN -----\n"
                f"{contract['message']}\n"
                "----- Sitter CHILD PROMPT END -----"
            )
            self.lifecycle(project,contract,prompt=marked)
            output,att,raw=collect_native(context,request,packet)
            self.assertEqual(output,"Native bounded result.")
            self.assertEqual(att["schema_version"],2)

    def test_background_and_extra_agent_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,status="async_launched")
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"foreground"): collect_native(context,request,packet)
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,extra_start=True)
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"additional or nested"): collect_native(context,request,packet)

    def test_explicit_background_tool_input_is_rejected_but_omission_is_foreground(self):
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d)
            self.lifecycle(project,contract,run_background=True)
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"foreground"): collect_native(context,request,packet)
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d)
            self.lifecycle(project,contract,omit_background=True)
            output,att,raw=collect_native(context,request,packet)
            self.assertEqual(output,"Native bounded result.")

    def test_forbidden_nested_multiple_cwd_and_model_are_rejected(self):
        for tool in ("Bash","Agent"):
            with self.subTest(tool=tool),tempfile.TemporaryDirectory() as d:
                project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,child_tool=tool)
                with self.assertRaisesRegex(ClaudeNativeRuntimeError,"forbidden|nested"): collect_native(context,request,packet)
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,second_cwd=str(project/"other"))
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"share one cwd"): collect_native(context,request,packet)
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,second_model="opus")
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"share one model"): collect_native(context,request,packet)

    def test_wrong_model_final_message_and_malformed_transcript_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,model="opus")
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"resolution policy"): collect_native(context,request,packet)
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,final="Transcript final")
            stop=Path(contract["evidence_dir"])/"004.json"; envelope=json.loads(stop.read_text()); envelope["event"]["last_assistant_message"]="Different"; stop.write_text(json.dumps(envelope)+"\n")
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"final message differs"): collect_native(context,request,packet)
        with tempfile.TemporaryDirectory() as d:
            project,context,request,packet,_,contract=self.prepare(d); self.lifecycle(project,contract,malformed=True)
            with self.assertRaisesRegex(ClaudeNativeRuntimeError,"invalid JSON"): collect_native(context,request,packet)


if __name__=="__main__": unittest.main()
