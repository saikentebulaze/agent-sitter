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

from core.provider_registry import get_provider  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from providers.claude.managed_runtime import ClaudeManagedRuntimeError, execute_managed_read_only, require_supported_version, resolve_claude_executable  # noqa: E402

_FAKE = r'''import json, os, sys, time, uuid
from pathlib import Path
if "--version" in sys.argv:
 print(os.environ.get("FAKE_VERSION", "2.1.217 (Claude Code)")); raise SystemExit(0)
Path(os.environ.get("EXEC_MARKER", os.devnull)).write_text("executed", encoding="utf-8")
a=sys.argv[1:]
def v(flag): return a[a.index(flag)+1]
required={"-p","--agent","--model","--effort","--tools","--disallowedTools","--mcp-config","--strict-mcp-config","--output-format","--session-id","--settings","--setting-sources"}
if not required.issubset(set(a)): raise SystemExit(61)
if Path(v("--settings")).name != "governed-settings.json": raise SystemExit(62)
sid=v("--session-id"); model=v("--model"); scenario=os.environ.get("SCENARIO","ok")
dir=Path(os.environ["SITTER_CLAUDE_EVIDENCE_DIR"]); dir.mkdir(parents=True,exist_ok=True)
nonce=os.environ["SITTER_CLAUDE_ATTEMPT_NONCE"]
def event(name, **kw):
 e={"schema_version":2,"attempt_nonce":nonce,"execution_mode":"managed","recorded_at_ns":time.time_ns(),"event":{"hook_event_name":name,"session_id":sid,**kw}}
 (dir/f"{time.time_ns()}-{uuid.uuid4().hex}.json").write_text(json.dumps(e)+"\n",encoding="utf-8")
event("SessionStart",source="startup"); event("InstructionsLoaded",source="project")
tool="Bash" if scenario=="forbidden" else "Read"
event("PreToolUse",tool_name=tool); event("PostToolUse",tool_name=tool)
if scenario=="compact": event("PreCompact",trigger="auto")
if scenario!="missing-end": event("SessionEnd",reason="completed")
resolved="opus" if scenario=="wrong-model" else model
actual="other" if scenario=="wrong-session" else sid
mcp=[{"name":"bad"}] if scenario=="mcp" else []
rows=[{"type":"system","subtype":"init","session_id":actual,"model":resolved,"tools":["Read","Grep","Glob"],"mcp_servers":mcp,"cwd":os.getcwd()},{"type":"assistant","message":{"content":[{"type":"tool_use","name":tool}]}},{"type":"result","is_error":False,"session_id":actual,"model":resolved,"cwd":os.getcwd(),"result":"bounded"}]
for row in rows: print(json.dumps(row))
if scenario=="malformed": print("not-json")
'''

class ClaudeManagedRuntimeTests(unittest.TestCase):
 def context(self,directory):
  project=Path(directory)/"project"; project.mkdir(); subprocess.run(["git","init",str(project)],check=True,capture_output=True)
  install.install(project,dry_run=False,provider_ids=("claude",)); package=project/".harness"/"sitter"
  return project,ProjectContext(package,project,package/"adapters"/"default")
 def fake(self,directory):
  script=Path(directory)/"fake.py"; script.write_text(_FAKE,encoding="utf-8"); return (sys.executable,str(script))
 def packet(self,context):
  p=get_provider("claude").load_role_profile(context,"context_scout")
  requested={"schema_version":2,"provider":"claude","agent":p.role_id,"role_id":p.role_id,"runtime_role":p.runtime_role,"model":p.model,"model_selector":p.model,"tier":p.tier,"model_grade":p.tier,"model_resolution_mode":p.model_resolution_mode,"expected_resolved_model":p.expected_resolved_model,"proxy_provider":p.proxy_provider,"reasoning_effort":p.reasoning_effort,"sandbox_mode":p.write_isolation,"write_isolation":p.write_isolation}
  for key in ("profile_source_ref","profile_source_sha256","model_config_sha256","agent_projection_ref","agent_projection_sha256","settings_projection_ref","settings_projection_sha256","hook_projection_ref","hook_projection_sha256"): requested[key]=getattr(p,key)
  return {"schema_version":2,"runtime":{"provider":"claude"},"requested_profile":requested}
 def execute(self,directory,scenario="ok",version="2.1.217 (Claude Code)"):
  _,context=self.context(directory); previous=os.environ.get("FAKE_VERSION"); os.environ["FAKE_VERSION"]=version
  try:
   env=os.environ.copy(); env["SCENARIO"]=scenario
   return execute_managed_read_only(context,self.packet(context),message="read",command_prefix=self.fake(directory),environment=env)
  finally:
   if previous is None: os.environ.pop("FAKE_VERSION",None)
   else: os.environ["FAKE_VERSION"]=previous
 def test_success_uses_frozen_governed_settings_and_schema_v2(self):
  with tempfile.TemporaryDirectory() as d:
   output,att,raw=self.execute(d); self.assertEqual(output,"bounded"); self.assertEqual(att["schema_version"],2)
   self.assertEqual(att["execution"]["collector"],"claude-stream-hooks-transcript-v2"); self.assertIn("--settings",raw["command"])
   self.assertIn("governed-settings.json",raw["command"][raw["command"].index("--settings")+1]); self.assertEqual(set(att["observed"]["tools_configured"]),{"Read","Grep","Glob"})
 def test_old_version_fails_before_model_execution(self):
  with tempfile.TemporaryDirectory() as d:
   marker=Path(d)/"marker"; previous=os.environ.get("EXEC_MARKER"); os.environ["EXEC_MARKER"]=str(marker)
   try:
    with self.assertRaisesRegex(ClaudeManagedRuntimeError,"older than"): self.execute(d,version="2.1.187 (Claude Code)")
    self.assertFalse(marker.exists())
   finally:
    if previous is None: os.environ.pop("EXEC_MARKER",None)
    else: os.environ["EXEC_MARKER"]=previous
 def test_unparseable_cmd_shim_is_not_silently_executed(self):
  with tempfile.TemporaryDirectory() as d:
   shim=Path(d)/"claude.cmd"; shim.write_text('@echo off\nnode something.js %*\n',encoding="utf-8")
   with self.assertRaisesRegex(ClaudeManagedRuntimeError,"exactly one"): resolve_claude_executable(shim)
 def test_valid_cmd_shim_resolves_real_binary(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/"claude-real.exe"; exe.write_bytes(b"x"); shim=Path(d)/"claude.cmd"; shim.write_text('"%~dp0claude-real.exe" %*\n',encoding="utf-8")
   resolved,method=resolve_claude_executable(shim); self.assertEqual(resolved,exe.resolve()); self.assertEqual(method,"windows-shim-resolved")
 def test_runtime_mutations_are_rejected(self):
  for scenario,pattern in (("forbidden","forbidden tools"),("wrong-model","resolution policy"),("wrong-session","different session"),("mcp","MCP servers"),("compact","continuity"),("missing-end","lifecycle"),("malformed","invalid JSON")):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d:
    with self.assertRaisesRegex(ClaudeManagedRuntimeError,pattern): self.execute(d,scenario)
 def test_user_local_settings_remain_user_owned(self):
  with tempfile.TemporaryDirectory() as d:
   project=Path(d)/"project"; project.mkdir(); subprocess.run(["git","init",str(project)],check=True,capture_output=True)
   local=project/".claude"/"settings.local.json"; local.parent.mkdir(); local.write_text('{"permissions":{"allow":["Bash(git status)"]}}\n',encoding="utf-8")
   before=local.read_bytes(); install.install(project,dry_run=False,provider_ids=("claude",)); self.assertEqual(local.read_bytes(),before)
 def test_version_parser(self):
  require_supported_version("2.1.217 (Claude Code)")
  with self.assertRaises(ClaudeManagedRuntimeError): require_supported_version("bad")

if __name__=="__main__": unittest.main()