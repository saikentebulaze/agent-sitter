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
import governed_work as governed_work_module  # noqa: E402
from active_task_index import load_active_task_index  # noqa: E402
from decision_authority import human_decision_digest  # noqa: E402
from governance_checks import _validate_decision_authority  # noqa: E402
from governed_validation import (  # noqa: E402
    investigation_exploration_status,
    validate_governed_work_graph,
)
from knowledge_tool import resolve_knowledge_path  # noqa: E402
from memory_context import memory_freshness  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from review_transaction import ReviewTransactionError  # noqa: E402
from work_graph import WorkGraph  # noqa: E402


class V6MergeReviewRegressionTests(unittest.TestCase):
    def test_task_completion_unregisters_active_task_in_same_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, task_root, task_path, investigation_path, index_path = (
                self._completion_fixture(Path(directory))
            )

            governed_work_module.complete_task(
                context,
                "completion-task",
                rationale="Close the completed Investigation",
            )

            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            investigation = yaml.safe_load(
                investigation_path.read_text(encoding="utf-8")
            )
            active_ids = {
                item["id"] for item in load_active_task_index(context)["tasks"]
            }
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["current_focus"], {"type": "none", "ref": None})
            self.assertEqual(investigation["status"], "closed")
            self.assertNotIn("completion-task", active_ids)
            self.assertTrue(index_path.is_file())
            validate_governed_work_graph(context, task_root)

    def test_task_completion_rolls_back_after_index_was_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _, task_path, investigation_path, active_index_path = (
                self._completion_fixture(Path(directory))
            )
            before = {
                task_path: task_path.read_bytes(),
                investigation_path: investigation_path.read_bytes(),
                active_index_path: active_index_path.read_bytes(),
            }
            original_unregister = governed_work_module.unregister_active_task
            mutation_observed: list[bool] = []

            def unregister_then_fail(*args: object, **kwargs: object) -> None:
                original_unregister(*args, **kwargs)
                current_ids = {
                    item["id"] for item in load_active_task_index(context)["tasks"]
                }
                mutation_observed.append("completion-task" not in current_ids)
                raise RuntimeError("deterministic post-index-mutation failure")

            governed_work_module.unregister_active_task = unregister_then_fail
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "deterministic post-index-mutation failure",
                ):
                    governed_work_module.complete_task(
                        context,
                        "completion-task",
                        rationale="Close the completed Investigation",
                    )
            finally:
                governed_work_module.unregister_active_task = original_unregister

            self.assertEqual(mutation_observed, [True])
            for path, original_bytes in before.items():
                self.assertEqual(path.read_bytes(), original_bytes, str(path))
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            active_ids = {
                item["id"] for item in load_active_task_index(context)["tasks"]
            }
            self.assertNotEqual(task["status"], "completed")
            self.assertIn("completion-task", active_ids)

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

    def test_dropping_protocol_does_not_disable_existing_v6_authority_snapshot(self) -> None:
        data = self._authority_change()
        data["review"] = {
            "status": "pass",
            "execution": {
                "input_snapshot": {"human_decisions_sha256": "0" * 64},
            },
        }
        data.pop("decision_authority_protocol")
        with self.assertRaises(SystemExit):
            _validate_decision_authority(data)

    def test_pre_v6_resolved_change_without_authority_markers_remains_read_compatible(self) -> None:
        data = self._authority_change()
        data.pop("decision_authority_protocol")
        data["review"] = {
            "status": "pass",
            "execution": {"input_snapshot": {"design_sha256": "legacy"}},
        }
        data["knowledge_sync"] = {"status": "pending"}
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

            for escaped in (str(outside.resolve()), "C:/outside.txt"):
                with self.subTest(escaped=escaped):
                    with self.assertRaises(ValueError):
                        resolve_knowledge_path(
                            project,
                            escaped,
                            require_exists=True,
                        )

    def test_knowledge_path_rejects_leaf_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            knowledge = project / "knowledge"
            knowledge.mkdir(parents=True)
            outside = project.parent / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            link = knowledge / "link.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"file symlinks unavailable: {error}")
            with self.assertRaises(ValueError):
                resolve_knowledge_path(
                    project,
                    "knowledge/link.txt",
                    require_exists=True,
                )

    def test_knowledge_path_rejects_symlinked_knowledge_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            outside = project.parent / "outside-knowledge"
            outside.mkdir()
            (outside / "entry.md").write_text("outside", encoding="utf-8")
            knowledge = project / "knowledge"
            try:
                knowledge.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                resolve_knowledge_path(
                    project,
                    "knowledge/entry.md",
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

    def test_memory_freshness_tracks_both_sides_of_committed_rename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            self._git(project, "init")
            self._git(project, "config", "user.email", "v6-review@example.invalid")
            self._git(project, "config", "user.name", "V6 Review")
            source = project / "src" / "状态" / "旧 file.py"
            source.parent.mkdir(parents=True)
            source.write_text("VALUE = 1\n", encoding="utf-8")
            self._git(project, "add", "-A")
            self._git(project, "commit", "-m", "original unicode source")
            source_commit = self._git(project, "rev-parse", "HEAD").stdout.strip()

            target = project / "archive" / "新 file.py"
            target.parent.mkdir()
            self._git(
                project,
                "mv",
                str(source.relative_to(project)),
                str(target.relative_to(project)),
            )
            self._git(project, "commit", "-m", "move source out of validity surface")

            context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
            freshness = memory_freshness(
                context,
                {
                    "source_commit": source_commit,
                    "validity_surface": ["src/状态"],
                },
            )
            self.assertEqual(freshness["status"], "suspect")
            self.assertIn("src/状态/旧 file.py", set(freshness["committed_hits"]))

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

    @staticmethod
    def _completion_fixture(
        root: Path,
    ) -> tuple[ProjectContext, Path, Path, Path, Path]:
        project = root / "project"
        project.mkdir()
        V6MergeReviewRegressionTests._git(project, "init")
        lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
        lock.parent.mkdir(parents=True)
        lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")

        created = subprocess.run(
            [
                sys.executable,
                str(RUNTIME / "create_task.py"),
                "completion-task",
                "--title",
                "Completion transaction fixture",
                "--entry",
                "investigation",
                "--question",
                "Can the Task close atomically?",
                "--signature",
                "completion-transaction",
                "--project",
                str(project),
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        task_root = project / created.stdout.strip()
        concluded = subprocess.run(
            [
                sys.executable,
                str(RUNTIME / "work.py"),
                "--project",
                str(project),
                "conclude-investigation",
                "completion-task",
                "inv-001",
                "--disposition",
                "no-change-required",
                "--rationale",
                "No production change is required",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        if concluded.stdout.strip() != "concluded: inv-001":
            raise AssertionError(concluded.stdout)

        task_path = task_root / "task.yaml"
        task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        task["learning"]["closeout"]["status"] = "assessed"
        task["learning"]["closeout"]["reason"] = "No reusable learning candidate"
        task_path.write_text(
            yaml.safe_dump(task, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
        active_index_path = project / ".agent-work" / "_context" / "active-tasks.yaml"
        active_ids = {
            item["id"] for item in load_active_task_index(context)["tasks"]
        }
        if "completion-task" not in active_ids:
            raise AssertionError("fixture Task was not registered in the Active Task Index")
        return (
            context,
            task_root,
            task_path,
            task_root / "investigations" / "inv-001.yaml",
            active_index_path,
        )


if __name__ == "__main__":
    unittest.main()
