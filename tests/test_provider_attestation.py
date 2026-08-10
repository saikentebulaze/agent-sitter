from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]; RUNTIME=ROOT/"runtime"
if str(RUNTIME) not in sys.path: sys.path.insert(0,str(RUNTIME))

from claude_test_support import claude_packet, valid_claude_attestation  # noqa: E402
from core.provider_registry import get_provider  # noqa: E402
from core.runtime_selection import provider_id_from_packet  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_attestation import validate_provider_attestation  # noqa: E402


class ProviderAttestationTests(unittest.TestCase):
 def context(self): return ProjectContext(ROOT,ROOT,ROOT/"adapters"/"default")
 def codex_packet(self,provider=None):
  runtime={"task_name":"sitter_dlg_001"};
  if provider is not None: runtime["provider"]=provider
  return {"project_root":str(ROOT),"requested_profile":{"agent":"source_locator","model":"gpt-5.6-luna","tier":"luna","reasoning_effort":"low","sandbox_mode":"read-only"},"runtime":runtime}
 def codex_attestation(self):
  return {"schema_version":2,"execution":{"method":"native-subagent","collector":"codex-rollout-app-server-v1","task_name":"sitter_dlg_001","spawn_call_id":"call-001","session_ref":"native-thread:child-001"},"observed":{"agent":"source_locator","model":"gpt-5.6-luna","tier":"luna","reasoning_effort":"low","sandbox_mode":"read-only","context_inheritance":"none","child_thread_id":"child-001","parent_thread_id":"parent-001","cwd":str(ROOT)},"evidence":{"source":"verified-combined"}}
 def claude_packet(self): return claude_packet(get_provider("claude").load_role_profile(self.context(),"context_scout"))
 def test_legacy_request_defaults_to_codex(self):
  packet=self.codex_packet(); self.assertEqual(provider_id_from_packet(packet),"codex"); self.assertEqual(validate_provider_attestation(packet,self.codex_attestation()).provider,"codex")
 def test_explicit_codex_provider_uses_same_contract(self): self.assertEqual(validate_provider_attestation(self.codex_packet("codex"),self.codex_attestation()).provider,"codex")
 def test_explicit_claude_provider_uses_schema2_contract(self):
  packet=self.claude_packet(); evidence=validate_provider_attestation(packet,valid_claude_attestation(packet)); self.assertEqual((evidence.provider,evidence.role_id,evidence.contract.write_isolation),("claude","context_scout","tool-restricted"))
 def test_unknown_provider_is_rejected(self):
  with self.assertRaisesRegex(ValueError,"Supported providers: claude, codex"): validate_provider_attestation(self.codex_packet("opencode"),self.codex_attestation())
 def test_incomplete_codex_attestation_is_rejected(self):
  att=self.codex_attestation(); att["schema_version"]=1
  with self.assertRaisesRegex(ValueError,"schema_version must be 2"): validate_provider_attestation(self.codex_packet(),att)
 def test_codex_and_claude_schemas_cannot_be_substituted(self):
  with self.assertRaisesRegex(ValueError,"unsupported execution method"): validate_provider_attestation(self.claude_packet(),self.codex_attestation())

if __name__=="__main__": unittest.main()
