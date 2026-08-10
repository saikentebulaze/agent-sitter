from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]; RUNTIME=ROOT/"runtime"
if str(RUNTIME) not in sys.path: sys.path.insert(0,str(RUNTIME))

from core.provider_registry import get_provider  # noqa: E402
from project_context import ProjectContext  # noqa: E402


class ProviderBoundaryTests(unittest.TestCase):
 def context(self): return ProjectContext(ROOT,ROOT,ROOT/"adapters"/"default")
 def test_codex_provider_declares_authoritative_and_compatibility_assets(self):
  assets=set(get_provider("codex").required_assets(self.context()))
  for relative in ("runtime/providers/codex/app_server.py","runtime/providers/codex/attestation.py","runtime/providers/codex/delegation_runtime.py","runtime/providers/codex/external_fallback.py","runtime/providers/codex/managed_runtime.py","runtime/providers/codex/profile_validation.py","runtime/providers/codex/profiles.py","runtime/providers/codex/projection.py","runtime/providers/codex/trust.py","runtime/codex_app_server.py","runtime/codex_runtime_attestation.py","runtime/codex_managed_runtime.py","runtime/codex_trust.py","runtime/delegation_runtime.py","runtime/launch_scout.py","runtime/projection.py"):
   with self.subTest(path=relative): self.assertIn(ROOT/relative,assets)
 def test_claude_provider_declares_real_static_assets(self):
  assets=set(get_provider("claude").required_assets(self.context()))
  for relative in ("runtime/providers/claude/provider.py","runtime/providers/claude/profiles.py","runtime/providers/claude/profile_validation.py","runtime/providers/claude/projection.py","runtime/providers/claude/managed_runtime.py","runtime/providers/claude/native_runtime.py","runtime/providers/claude/governed_session.py","adapters/default/model-profiles.yaml","adapters/default/claude/governed-settings.json","adapters/default/claude/agents/context-scout.md","adapters/default/docs/Claude子Agent运行时验收.md"):
   with self.subTest(path=relative): self.assertIn(ROOT/relative,assets)
  self.assertNotIn(ROOT/"adapters/default/claude/settings.local.json",assets)
 def test_core_string_literals_do_not_contain_provider_runtime_vocabulary(self):
  forbidden=("gpt-5.6-","spawn_agent","codex-rollout","app-server",".codex","AGENTS.md",".claude","CLAUDE.local.md","SubagentStart","SubagentStop","PreCompact","InstructionsLoaded","transcript_path","haiku","sonnet","opus")
  for path in sorted((RUNTIME/"core").glob("*.py")):
   literals=[node.value for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"),filename=str(path))) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
   for token in forbidden:
    with self.subTest(path=path.name,token=token): self.assertFalse(any(token in literal for literal in literals),f"{token!r} leaked into Core")

if __name__=="__main__": unittest.main()
