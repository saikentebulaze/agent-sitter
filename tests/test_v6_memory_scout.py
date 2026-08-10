from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from delegation_transaction import authorize_delegation, request_delegation  # noqa: E402
from governed_validation import EXPLORATION_ROLES  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from providers.claude.profiles import load_native_agent_profile as load_claude_profile  # noqa: E402
from providers.codex.profiles import load_native_agent_profile as load_codex_profile  # noqa: E402
from work_graph import load_yaml  # noqa: E402


def create_project(root: Path) -> tuple[Path, ProjectContext]:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "v6@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "V6 Fixture"], check=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project, ProjectContext(ROOT, project, ROOT / "adapters" / "default")


def import_memory_scout_module():
    spec = importlib.util.spec_from_file_location("memory_scout_once_fixture", RUNTIME / "memory_scout_once.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import memory_scout_once")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V6MemoryScoutTests(unittest.TestCase):
    def test_memory_scout_is_low_cost_on_both_providers_and_not_an_engineering_exploration_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context = create_project(Path(directory))
            codex = load_codex_profile(context, "memory_scout")
            claude = load_claude_profile(context, "memory_scout")
            self.assertEqual(codex.model_grade, "low")
            self.assertEqual(codex.reasoning_effort, "low")
            self.assertEqual(claude.model_grade, "low")
            self.assertEqual(claude.reasoning_effort, "low")
            self.assertNotIn("memory_scout", EXPLORATION_ROLES)

    def test_memory_scout_request_freezes_recall_packet_and_forbids_repository_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="memory-task",
                title="Memory task",
                entry="investigation",
                signature="memory-task",
            )
            authorize_delegation(
                context,
                "memory-task",
                decision="optional",
                scopes=["readonly-exploration"],
                evidence="fixture allows bounded historical recall",
                parent_model="gpt-5.6-terra",
                parent_tier="terra",
            )
            recall = task_root / "memory-recalls" / "recall-001.json"
            recall.parent.mkdir(parents=True)
            recall.write_text(
                json.dumps(
                    {
                        "selected": [
                            {
                                "id": "K01",
                                "freshness": {"status": "suspect"},
                                "usage": "historical-lead",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            packet_path = request_delegation(
                context,
                "memory-task",
                role="memory_scout",
                target_type="task",
                target_ref="memory-task",
                purpose="recover bounded historical context",
                question="What prior context is relevant?",
                decision_supported="No engineering decision; historical recovery only.",
                include=[".agent-work/memory-task/memory-recalls/recall-001.json"],
                exclude=[],
                start_refs=[".agent-work/memory-task/memory-recalls/recall-001.json"],
                confirmed_facts=["suspect memory is historical lead only"],
            )
            packet = load_yaml(packet_path)
            self.assertEqual(packet["context_policy"]["inheritance"], "none")
            self.assertEqual(packet["context_policy"]["additional_repository_search"], "forbidden")
            self.assertEqual(packet["context_policy"]["max_context_supplements"], 0)
            self.assertEqual(packet["bias_control"]["parent_hypotheses"], "withheld")
            self.assertIn(
                ".agent-work/memory-task/memory-recalls/recall-001.json",
                packet["snapshot"],
            )
            self.assertIn("new engineering conclusions", packet["output_contract"]["forbidden"])
            self.assertIn(
                "upgrading suspect or unknown memory to current fact",
                packet["output_contract"]["forbidden"],
            )

    def test_memory_scout_once_does_not_start_agent_when_recall_has_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            initialize_provider_task(
                context,
                task_id="memory-empty",
                title="Memory empty",
                entry="investigation",
                signature="memory-empty",
            )
            knowledge = project / "knowledge"
            knowledge.mkdir()
            (knowledge / "index.yaml").write_text("version: 1\nentries: []\n", encoding="utf-8")
            module = import_memory_scout_module()
            with mock.patch.object(module, "delegate_once") as delegate:
                result = module.run_memory_scout(
                    project,
                    "memory-empty",
                    query="unrelated low rename",
                    limit=3,
                )
            self.assertFalse(result["memory_scout_started"])
            self.assertEqual(result["selected_count"], 0)
            delegate.assert_not_called()
            task = yaml.safe_load(
                (project / ".agent-work" / "memory-empty" / "task.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(task["delegation"]["planned"], [])


if __name__ == "__main__":
    unittest.main()
