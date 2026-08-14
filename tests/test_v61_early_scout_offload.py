from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters" / "default"
ROUTER = ADAPTER / "bootstrap" / "AGENTS.md.template"
GOVERNOR = ADAPTER / "skills" / "change-governor" / "SKILL.md"
SUBAGENT_POLICY = (
    ADAPTER
    / "skills"
    / "change-governor"
    / "references"
    / "subagent-model-policy.md"
)
TASK_TEMPLATE = (
    ADAPTER
    / "skills"
    / "change-governor"
    / "assets"
    / "task.yaml.template"
)
MODEL_PROFILES = ADAPTER / "model-profiles.yaml"


class V61EarlyScoutOffloadTests(unittest.TestCase):
    def test_router_promotes_before_parent_repository_wide_scan(self) -> None:
        text = ROUTER.read_text(encoding="utf-8")
        self.assertIn("One or two obvious anchor reads are enough to route", text)
        self.assertIn("instead of pre-scanning the repository in the parent context", text)

    def test_governor_uses_scout_as_early_context_cost_offload(self) -> None:
        text = GOVERNOR.read_text(encoding="utf-8")
        self.assertIn("### Exploration offload economics", text)
        self.assertIn("After at most one or two obvious anchor reads", text)
        self.assertIn("Default to one Scout, not fan-out", text)
        self.assertIn("satisfy required independent exploration **early**", text)
        self.assertIn("do not repeat its broad search in the parent", text)
        self.assertIn("--decision optional|required", text)
        self.assertIn("same-tier or cheaper read-only Scout", text)

    def test_subagent_policy_preserves_single_scout_and_no_duplicate_search(self) -> None:
        text = SUBAGENT_POLICY.read_text(encoding="utf-8")
        self.assertIn("context-cost optimization tool", text)
        self.assertIn("Prefer exactly one Scout initially", text)
        self.assertIn("must not mechanically repeat the child's whole search", text)
        self.assertIn("MEDIUM work remains eligible to stay entirely in the parent", text)
        self.assertIn("LOW Fast Path work does not use subagents for ceremony", text)

    def test_behavior_tuning_does_not_silently_pre_authorize_every_task(self) -> None:
        task = yaml.safe_load(TASK_TEMPLATE.read_text(encoding="utf-8"))
        delegation = task["delegation"]
        self.assertEqual(delegation["decision"], "not-needed")
        self.assertEqual(delegation["authorization"]["status"], "not-required")
        self.assertEqual(delegation["authorization"]["scopes"], [])

    def test_offload_roles_stay_cheaper_than_sol_parent_by_default(self) -> None:
        profiles = yaml.safe_load(MODEL_PROFILES.read_text(encoding="utf-8"))["roles"]
        self.assertEqual(profiles["source_locator"]["model_grade"], "low")
        self.assertEqual(profiles["context_scout"]["model_grade"], "low")
        self.assertEqual(profiles["test_scout"]["model_grade"], "low")
        self.assertEqual(profiles["framework_scout"]["model_grade"], "medium")


if __name__ == "__main__":
    unittest.main()
