from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import harness as harness_module  # noqa: E402
from decision_authority import human_decision_digest  # noqa: E402
from governance_checks import _validate_decision_authority  # noqa: E402
from governed_validation import investigation_exploration_status  # noqa: E402
from knowledge_tool import resolve_knowledge_path  # noqa: E402
from memory_context import memory_freshness  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from review_transaction import ReviewTransactionError  # noqa: E402
from work_graph import WorkGraph  # noqa: E402


class V6MergeReviewRegressionTests(unittest.TestCase):
    def test_g1_unrelated_task_level_scout_does_not_satisfy_new_investigation(self) -> None:
        task = {
            "id": "review-task",
            "work_risk": {
                "current": {"semantic": "critical", "repository_change": "critical"},
            },
            "delegation": {
                "planned": [
                    {
                        "id": "dlg-001",
                        "agent": "context_scout",
                        "target": {"type": "task", "ref": "review-task"},
                    }
                ],
                "completed": [{"id": "dlg-001"}],
            },
        }
        investigation = {"source": {"type": "task", "ref": "review-task"}}
        graph = WorkGraph(
            task_root=Path("."),
            task=task,
            investigations={"inv-002": investigation},
            changes={},
        )

        unrelated = investigation_exploration_status(graph, "inv-002")
        self.assertTrue(unrelated["required"])
        self.assertFalse(unrelated["satisfied"])
        self.assertEqual(unrelated["completed_exploration"], [])

        task["delegation"]["planned"][0]["target"] = {
            "type": "investigation",
            "ref": "inv-002",
        }
        relevant = investigation_exploration_status(graph, "inv-002")
        self.assertTrue(relevant["satisfied"])
        self.assertEqual(relevant["completed_exploration"], ["dlg-001"])

    def test_resolved_human_decision_cannot_drop_authority_protocol(self) -> None:
        data = self._authority_change()
        data.pop("decision_authority_protocol")
        with self.assertRaises(SystemExit):
            _validate_decision_authority(data)

    def test_knowledge_candidate_cannot_drop_authority_digest(self) -> None:
        data = self._authority_change()
        data["knowledge_sync"] = {
            "status": "candidate",
            "human_decisions_sha256": "",
        }
        with self.assertRaises(SystemExit):
            _validate_decision_authority(data)

        data["knowledge_sync"]["human_decisions_sha256"] = human_decision_digest(data)
        _validate_decision_authority(data)

    def test_promote_knowledge_fails_before_base_mutation_when_digest_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            change = project / "changes" / "active" / "authority-change"
            change.mkdir(parents=True)
            data = self._authority_change()
            data["knowledge_sync"] = {
                "status": "reviewed",
                "human_decisions_sha256": "",
            }
            (change / "change.yaml").write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
            called: list[bool] = []
            original = harness_module._base_command_promote_knowledge
            harness_module._base_command_promote_knowledge = (
                lambda *_args, **_kwargs: called.append(True)
            )
            try:
                with self.assertRaises(ReviewTransactionError):
                    harness_module.command_promote_knowledge(
                        context,
                        change,
                        "user",
                        "reviewed",
                    )
            finally:
                harness_module._base_command_promote_knowledge = original
            self.assertEqual(called, [])

    def test_knowledge_path_rejects_parent_traversal_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            knowledge = project / "knowledge"
            knowledge.mkdir(parents=True)
            outside = project.parent / "outside.txt"
            outside.write_text("outside", encoding="utf-8")

            with self.assertRaises(ValueError):
                resolve_knowledge_path(
                    project,
                    "knowledge/../../outside.txt",
                    require_exists=True,
                )

            link = knowledge / "link.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(ValueError):
                resolve_knowledge_path(
                    project,
                    "knowledge/link.txt",
                    require_exists=True,
                )

    def test_memory_freshness_handles_unicode_space_and_rename_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            self._git(project, "init")
            self._git(project, "config", "user.email", "v6-review@example.invalid")
            self._git(project, "config", "user.name", "V6 Review")
            source = project / "src" / "状态" / "会话 file.py"
            source.parent.mkdir(parents=True)
            source.write_text("VALUE = 1\n", encoding="utf-8")
            self._git(project, "add", "-A")
            self._git(project, "commit", "-m", "unicode source")
            source_commit = self._git(project, "rev-parse", "HEAD").stdout.strip()

            target = project / "src" / "状态" / "新 名称.py"
            self._git(project, "mv", str(source.relative_to(project)), str(target.relative_to(project)))

            context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
            entry = {
                "source_commit": source_commit,
                "validity_surface": ["src/状态"],
            }
            freshness = memory_freshness(context, entry)
            self.assertEqual(freshness["status"], "suspect")
            hits = set(freshness["working_tree_hits"])
            self.assertIn("src/状态/会话 file.py", hits)
            self.assertIn("src/状态/新 名称.py", hits)

    @staticmethod
    def _authority_change() -> dict:
        return {
            "decision_authority_protocol": 1,
            "human_in_loop": {
                "decision_assessment": {
                    "status": "resolved",
                    "reasons": ["material choice"],
                },
                "decisions": [
                    {
                        "id": "DEC-H1",
                        "question": "Which behavior is authoritative?",
                        "user_decision": "B",
                        "evidence": "user selected B",
                    }
                ],
            },
            "review": {"status": "pending"},
            "knowledge_sync": {"status": "pending"},
        }

    @staticmethod
    def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=project,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
