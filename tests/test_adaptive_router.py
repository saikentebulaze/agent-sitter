from __future__ import annotations

from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from project_context import ProjectContext  # noqa: E402
from providers.claude.projection import entrypoint_text as claude_entrypoint_text  # noqa: E402
from providers.claude.projection import skill_wrapper_text as claude_skill_wrapper_text  # noqa: E402
from providers.codex.projection import entrypoint_text as codex_entrypoint_text  # noqa: E402
from providers.codex.projection import skill_wrapper_text as codex_skill_wrapper_text  # noqa: E402


class AdaptiveRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ROOT / "adapters" / "default"
        self.router = self.adapter / "bootstrap" / "AGENTS.md.template"
        self.governor = self.adapter / "skills" / "change-governor" / "SKILL.md"

    def test_router_is_small_and_keeps_low_work_outside_work_graph(self) -> None:
        text = self.router.read_text(encoding="utf-8")
        self.assertLess(len(text.encode("utf-8")), 4500)
        self.assertIn("LOW Fast Path", text)
        self.assertIn("Do not create `.agent-work`", text)
        self.assertIn("Do not load the full Governor", text)
        self.assertIn("Incremental turns", text)
        self.assertIn("does not maintain per-session Skill-loaded state", text)
        self.assertNotIn("Governed continuation", text)
        self.assertNotIn("authorize-delegation", text)
        self.assertNotIn("record-model-review", text)

    def test_governor_is_formal_governance_not_universal_repository_entrypoint(self) -> None:
        text = self.governor.read_text(encoding="utf-8")
        self.assertLess(len(text.encode("utf-8")), 10000)
        self.assertIn("Do not use for ordinary LOW fast-path work", text)
        self.assertIn("delegate_once.py", text)
        self.assertIn("finalize_tests.py", text)
        self.assertIn("change.risk", text)
        self.assertIn("Progressive disclosure", text)

    def test_codex_and_claude_entrypoints_both_route_through_lightweight_policy(self) -> None:
        codex = codex_entrypoint_text()
        claude = claude_entrypoint_text()
        for value in (codex, claude):
            self.assertIn("lightweight routing policy", value)
            self.assertIn("LOW Fast Path", value)
            self.assertIn("Do not load the full Governor", value)
            self.assertNotIn("read `.harness/sitter/adapters/default/bootstrap/AGENTS.md.template` in full", value)

    def test_generated_skill_bridges_no_longer_force_full_read_before_any_action(self) -> None:
        source = self.governor
        codex = codex_skill_wrapper_text(source)
        claude = claude_skill_wrapper_text(source)
        for value in (codex, claude):
            self.assertNotIn("Before taking any action", value)
            self.assertIn("LOW fast-path work", value)
            self.assertIn("read `.harness/", value)
        self.assertNotIn("disable-model-invocation", claude)

    def test_heavy_governor_disables_implicit_codex_invocation(self) -> None:
        metadata = yaml.safe_load(
            (self.governor.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        self.assertFalse(metadata["policy"]["allow_implicit_invocation"])


if __name__ == "__main__":
    unittest.main()
