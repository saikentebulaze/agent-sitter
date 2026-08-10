from __future__ import annotations

import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TOOLS = HARNESS_ROOT / "runtime"
ARTIFACTS = (
    "proposal.md", "design.md", "tasks.md", "verification.md",
    "knowledge-sync.md", "archive-summary.md",
)


def run_tool(name: str, *args: object, project: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(TOOLS / name)]
    if project is not None:
        command.extend(["--project", str(project)])
    command.extend(map(str, args))
    return subprocess.run(command, cwd=HARNESS_ROOT, text=True, encoding="utf-8", capture_output=True)


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def copy_harness_fixture(destination: Path) -> None:
    shutil.copytree(
        HARNESS_ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".agent-work"),
    )


def create_project(package_root: Path) -> Path:
    project = package_root / "project"
    project.mkdir()
    result = subprocess.run(["git", "init", str(project)], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project


def human_not_required() -> dict:
    return {
        "mode": "guided",
        "mode_evidence": None,
        "decision_assessment": {
            "status": "not-required",
            "reasons": ["the bounded task has no material semantic fork"],
        },
        "decisions": [],
        "interruption_budget": {"batch_questions": True, "max_design_checkpoints": 1},
    }


def human_resolved() -> dict:
    return {
        "mode": "guided",
        "mode_evidence": None,
        "decision_assessment": {
            "status": "resolved",
            "reasons": ["unloading semantics affect external state history"],
        },
        "decisions": [{
            "id": "DEC-001",
            "question": "Which unloading semantics should be used?",
            "options": ["committed-state", "trial-state"],
            "recommendation": "committed-state preserves lifecycle ownership",
            "user_decision": "committed-state",
            "evidence": "user approved in the design checkpoint",
        }],
        "interruption_budget": {"batch_questions": True, "max_design_checkpoints": 1},
    }


def snapshot() -> dict:
    return {
        "design_sha256": "1111111111111111",
        "tasks_sha256": "2222222222222222",
        "diff_sha256": "3333333333333333",
        "verification_sha256": "4444444444444444",
    }


def review_execution(agent: str = "maintainer_reviewer") -> dict:
    deep = agent == "deep_reviewer"
    data = {
        "agent": agent,
        "model": "gpt-5.6-sol" if deep else "gpt-5.6-terra",
        "tier": "sol" if deep else "terra",
        "method": "native-subagent",
        "output_ref": "reviews/1.md",
        "evidence_ref": "native-thread-review-1",
        "round": 1,
        "input_snapshot": snapshot(),
    }
    if deep:
        data["elevated_authorization_ref"] = "task.yaml#delegation.model_budget"
    return data


def latest_verification() -> list[dict]:
    return [{
        "id": "unit-tests",
        "kind": "test",
        "command_or_entry": "python -m unittest discover -s tests -v",
        "result": "pass",
        "checked_at": "2026-08-03T18:00:00+08:00",
        "evidence": "ci-run-1",
    }]


def change_data(*, review_status: str = "pass", status: str = "implementing") -> dict:
    dimensions = {
        "architecture": review_status,
        "scope": "pass" if review_status != "pending" else "pending",
        "numerical_evidence": "pass" if review_status != "pending" else "pending",
    }
    review = {"status": review_status, **dimensions}
    history: list[dict] = []
    if review_status != "pending":
        review["execution"] = review_execution()
        history = [{"round": 1, "status": review_status, **dimensions, "execution": review_execution()}]
        if review_status == "block":
            history[0]["remediation_route"] = "implementation"
    else:
        review["execution"] = {}

    archive_bound = status in {"ready-to-archive", "archived"}
    implementation_complete = status in {"verifying", "syncing", "ready-to-archive", "archived"}
    ready_for_user_review = status in {"syncing", "ready-to-archive", "archived"}
    return {
        "schema_version": 4,
        "id": "fixture-change",
        "task_id": "fixture-task",
        "title": "Fixture change",
        "status": status,
        "execution_state": "active",
        "hold": {"reason": None, "investigation_ref": None, "held_at": None},
        "relations": {
            "derived_from": {"investigations": [], "claims": [], "decisions": [], "evidence": []},
            "produced": {"investigations": [], "evidence": []},
            "supersedes": [], "superseded_by": None,
        },
        "resume_history": [],
        "revision_history": [],
        "risk": {"semantic": "high", "repository_change": "high"},
        "approval": {"status": "approved"},
        "human_in_loop": human_resolved(),
        "critical_surfaces": [],
        "change_budget": {"explicit_non_goals": [], "adjacent_issues": []},
        "methodology": {
            "planning_level": "full",
            "superpowers_skills": ["writing-plans", "test-driven-development"],
            "tdd_mode": "required",
            "temporary_tests": [],
            "test_cleanup_complete": review_status != "pending" or archive_bound,
            "retained_test_rationale": ["protects external solver behavior"],
        },
        "completion": {
            "implementation_complete": implementation_complete,
            "ready_for_user_review": ready_for_user_review,
        },
        "user_review": {
            "status": "approved" if archive_bound else "pending",
            "evidence": "user approved code review" if archive_bound else None,
        },
        "review": review,
        "review_history": history,
        "remediation": {
            "route": "implementation" if review_status == "block" else None,
            "within_approved_scope": review_status == "block",
        },
        "verification": {
            "status": "pass",
            "latest_results": latest_verification() if archive_bound else [],
        },
        "knowledge_sync": {
            "status": "deferred" if archive_bound else "pending",
            "entries": [],
            "deferred_reason": "no durable project fact changed" if archive_bound else None,
        },
        "archive": {
            "experiment_cleanup_complete": True,
            "temporary_production_files": [],
            "blockers": [],
        },
    }


def write_change(root: Path, data: dict) -> None:
    write_yaml(root / "change.yaml", data)
    for name in ARTIFACTS:
        (root / name).write_text("This artifact has enough content for validation.", encoding="utf-8")


def task_template() -> dict:
    path = (
        HARNESS_ROOT / "adapters" / "default" / "skills"
        / "change-governor" / "assets" / "task.yaml.template"
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["id"] = "fixture-task"
    data["title"] = "Fixture task"
    data["status"] = "active"
    data["learning"]["intake"] = {
        "status": "completed", "checked_at": "2026-08-03T00:00:00Z",
        "relevant_entries": [], "recommended_tools": [], "evidence": ".agent-work/_learning/inbox.yaml",
    }
    return data


class TaskStateValidationTests(unittest.TestCase):
    def test_v4_task_rejects_legacy_mode_phase_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.yaml"
            write_yaml(path, {"schema_version": 3.3, "mode": "investigation", "phase": "intake"})
            result = run_tool("validate_task_state.py", path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("schema_version must be 4", result.stderr)

    def test_pending_delegation_blocks_active_required_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.yaml"
            data = task_template()
            data["delegation"] = {
                "decision": "required",
                "authorization": {"status": "pending", "scopes": ["readonly-exploration"], "evidence": None},
                "model_budget": {
                    "parent_model": "gpt-5.6-terra", "parent_tier": "terra", "default_ceiling": "parent",
                    "elevated_authorization": {"status": "not-requested", "approved_tiers": [], "evidence": None},
                    "reasoning_authorization": {"status": "not-requested", "approved_efforts": [], "evidence": None},
                },
                "planned": [{
                    "agent": "context_scout", "model": "gpt-5.6-luna", "tier": "luna",
                    "reasoning_effort": "medium", "default_reasoning_effort": "medium",
                    "effort_escalation": "not-required", "purpose": "trace the bounded chain",
                    "relation_to_parent": "weaker", "elevation_authorization": "not-required",
                }],
                "completed": [], "failed": [], "user_override": False,
            }
            write_yaml(path, data)
            result = run_tool("validate_task_state.py", path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("authorization", result.stderr.lower())

    def test_human_checkpoint_requires_blocked_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.yaml"
            data = task_template()
            data["escalation"] = {
                "level": "human-checkpoint", "reason": "repeated failure", "signature": "same-problem",
                "related_refs": ["inv-002"],
                "model_review": {"required": True, "status": "inconclusive"},
                "human_checkpoint": {"required": True, "status": "pending", "question": "Choose", "decision": None, "evidence": None},
            }
            write_yaml(path, data)
            result = run_tool("validate_task_state.py", path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("blocked", result.stderr.lower())


class ChangeStateValidationTests(unittest.TestCase):
    def test_review_pass_without_native_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = change_data()
            data["review"].pop("execution")
            data["review_history"] = []
            write_change(root, data)
            result = run_tool("validate_change.py", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("execution", result.stderr.lower())

    def test_deep_reviewer_requires_elevated_authorization_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = change_data()
            execution = review_execution("deep_reviewer")
            execution.pop("elevated_authorization_ref")
            data["review"]["execution"] = execution
            data["review_history"][0]["execution"] = copy.deepcopy(execution)
            write_change(root, data)
            result = run_tool("validate_change.py", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("elevated_authorization_ref", result.stderr)

    def test_paused_change_cannot_continue_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = change_data(status="verifying")
            data["execution_state"] = "paused"
            data["hold"] = {"reason": "investigation-required", "investigation_ref": "inv-002", "held_at": "now"}
            write_change(root, data)
            result = run_tool("validate_change.py", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("paused", result.stderr.lower())

    def test_blocked_review_cannot_continue_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_change(root, change_data(review_status="block", status="verifying"))
            result = run_tool("validate_change.py", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("block", result.stderr.lower())

    def test_valid_reviewed_change_can_reach_archive_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_change(root, change_data(status="ready-to-archive"))
            result = run_tool("validate_change.py", root)
            self.assertEqual(result.returncode, 0, result.stderr)


class BootstrapProfileAndSchemaTests(unittest.TestCase):
    def test_create_task_uses_v4_work_graph_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            harness_copy = Path(directory) / "harness"
            copy_harness_fixture(harness_copy)
            project = create_project(harness_copy)
            result = subprocess.run(
                [
                    sys.executable, str(harness_copy / "runtime" / "create_task.py"),
                    "runtime-smoke", "--title", "Runtime smoke", "--entry", "investigation",
                    "--question", "What is happening?", "--signature", "runtime-smoke",
                    "--project", str(project),
                ],
                cwd=harness_copy, text=True, encoding="utf-8", capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            task = yaml.safe_load(
                (project / ".agent-work" / "runtime-smoke" / "task.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(task["schema_version"], 4)
            self.assertNotIn("mode", task)
            self.assertIn("pivot_control", task)
            self.assertTrue(
                (project / ".agent-work" / "runtime-smoke" / "investigations" / "inv-001.yaml").is_file()
            )

    def test_native_agent_configs_are_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project(Path(directory))
            result = run_tool("check_agent_profiles.py", project=project)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_safe_workspace_permission_defaults_are_projected(self) -> None:
        text = (HARNESS_ROOT / "adapters" / "default" / "codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('approval_policy = "on-request"', text)
        self.assertIn('sandbox_mode = "workspace-write"', text)
        self.assertNotIn('sandbox_mode = "danger-full-access"', text)

    def test_templates_define_v4_objects(self) -> None:
        root = HARNESS_ROOT / "adapters" / "default" / "skills" / "change-governor" / "assets"
        task = yaml.safe_load((root / "task.yaml.template").read_text(encoding="utf-8"))
        investigation = yaml.safe_load((root / "investigation.yaml.template").read_text(encoding="utf-8"))
        change = yaml.safe_load((root / "change.yaml.template").read_text(encoding="utf-8"))
        self.assertEqual(task["schema_version"], 4)
        self.assertIn("current_focus", task)
        self.assertIn("claims", investigation)
        self.assertEqual(change["schema_version"], 4)
        self.assertIn("execution_state", change)
        self.assertIn("relations", change)

    def test_closure_and_work_graph_clis_exist(self) -> None:
        for name in (
            "harness.py", "work.py", "work_graph.py", "pivot_transaction.py",
            "validate_task_state.py", "validate_investigation.py", "validate_work_graph.py",
        ):
            self.assertTrue((TOOLS / name).is_file(), name)

    def test_yaml_tools_fail_clearly_without_pyyaml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task.yaml"
            write_yaml(task, {"schema_version": 4})
            result = subprocess.run(
                [sys.executable, "-S", str(TOOLS / "validate_task_state.py"), str(task)],
                cwd=HARNESS_ROOT, text=True, encoding="utf-8", capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PyYAML", result.stderr)


if __name__ == "__main__":
    unittest.main()
