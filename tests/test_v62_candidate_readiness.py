from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from change_lifecycle import (  # noqa: E402
    ChangeLifecycleError,
    advance_change,
    build_change_dashboard,
    record_user_review,
)
from production_snapshot import production_snapshot_sha256  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from readiness import (  # noqa: E402
    ReadinessError,
    finalize_readiness,
    freeze_readiness_contract,
    record_readiness,
    validate_readiness_contract,
)
from reference_resolver import resolve_change_ref, resolve_task_ref  # noqa: E402


def run_git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, text=True)


def make_project(root: Path) -> tuple[Path, ProjectContext]:
    project = root / "project"
    project.mkdir()
    run_git(project, "init")
    run_git(project, "config", "user.email", "tests@example.com")
    run_git(project, "config", "user.name", "Sitter Tests")
    (project / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    run_git(project, "add", "tracked.txt")
    run_git(project, "commit", "-m", "baseline")
    return project, ProjectContext(ROOT, project, ROOT / "adapters" / "default")


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def base_change(change_id: str, *, assurance: str = "standard") -> dict:
    criterion = {
        "id": "focused",
        "kind": "focused-test",
        "required": True,
        "description": "focused regression passes",
    }
    if assurance == "numerical":
        criterion = {
            "id": "representative",
            "kind": "representative-case",
            "required": True,
            "description": "representative engineering case matches the reference",
        }
    return {
        "schema_version": 4,
        "id": change_id,
        "status": "approved",
        "execution_state": "active",
        "candidate_readiness_protocol": 1,
        "readiness": {
            "assurance_class": assurance,
            "status": "pending",
            "criteria": [criterion],
            "latest_results": [],
        },
        "methodology": {
            "test_cleanup_protocol": 1,
            "test_cleanup_complete": True,
            "test_cleanup_evidence": f"changes/active/{change_id}/test-finalization.yaml",
        },
        "completion": {
            "implementation_complete": False,
            "ready_for_user_review": False,
        },
        "user_review": {"status": "pending", "evidence": None},
        "review": {
            "status": "pass",
            "architecture": "pass",
            "scope": "pass",
            "numerical_evidence": "pass",
        },
        "human_in_loop": {
            "decision_assessment": {
                "status": "not-required",
                "reasons": ["no unresolved material design fork"],
            }
        },
    }


def freeze_then_implement(context: ProjectContext, change: Path) -> None:
    freeze_readiness_contract(context, change)
    data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
    data["status"] = "implementing"
    write_yaml(change / "change.yaml", data)


class V62CandidateReadinessTests(unittest.TestCase):
    def test_task_and_change_reference_forms_resolve_identically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            task = project / ".agent-work" / "task-one"
            write_yaml(task / "task.yaml", {"id": "task-one"})
            change = project / "changes" / "active" / "chg-one"
            write_yaml(change / "change.yaml", {"id": "chg-one"})

            task_refs = [
                resolve_task_ref(context, "task-one"),
                resolve_task_ref(context, ".agent-work/task-one"),
                resolve_task_ref(context, ".agent-work/task-one/task.yaml"),
            ]
            self.assertEqual({item.root for item in task_refs}, {task.resolve()})

            change_refs = [
                resolve_change_ref(context, "chg-one"),
                resolve_change_ref(context, "changes/active/chg-one"),
                resolve_change_ref(context, "changes/active/chg-one/change.yaml"),
            ]
            self.assertEqual({item.root for item in change_refs}, {change.resolve()})

    def test_production_snapshot_ignores_harness_lifecycle_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _ = make_project(Path(directory))
            before = production_snapshot_sha256(project)
            harness_state = project / "changes" / "active" / "chg" / "verification.md"
            harness_state.parent.mkdir(parents=True)
            harness_state.write_text("evidence\n", encoding="utf-8")
            self.assertEqual(before, production_snapshot_sha256(project))

            (project / "tracked.txt").write_text("production changed\n", encoding="utf-8")
            self.assertNotEqual(before, production_snapshot_sha256(project))

    def test_numerical_contract_cannot_be_satisfied_by_focused_test_only(self) -> None:
        data = base_change("chg", assurance="standard")
        data["readiness"]["assurance_class"] = "numerical"
        with self.assertRaisesRegex(ReadinessError, "numerical readiness requires"):
            validate_readiness_contract(data)

    def test_readiness_contract_cannot_change_after_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = project / "changes" / "active" / "chg"
            write_yaml(change / "change.yaml", base_change("chg"))
            freeze_then_implement(context, change)
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            data["readiness"]["criteria"][0]["description"] = "easier criterion after implementation"
            write_yaml(change / "change.yaml", data)
            with self.assertRaisesRegex(ReadinessError, "changed after it was frozen"):
                record_readiness(
                    context,
                    "chg",
                    criterion_id="focused",
                    result="pass",
                    command_or_entry="pytest focused",
                    evidence="test-log.txt",
                )

    def test_readiness_evidence_becomes_stale_after_production_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = project / "changes" / "active" / "chg"
            write_yaml(change / "change.yaml", base_change("chg", assurance="numerical"))
            freeze_then_implement(context, change)

            record_readiness(
                context,
                "chg",
                criterion_id="representative",
                result="pass",
                command_or_entry="run representative case",
                evidence="results/case.txt",
                observed="reference delta within tolerance",
            )
            (project / "tracked.txt").write_text("changed after evidence\n", encoding="utf-8")
            with self.assertRaisesRegex(ReadinessError, "stale: representative"):
                finalize_readiness(context, "chg")

    def test_candidate_review_is_hard_human_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = project / "changes" / "active" / "chg"
            write_yaml(change / "change.yaml", base_change("chg"))
            freeze_then_implement(context, change)

            record_readiness(
                context,
                "chg",
                criterion_id="focused",
                result="pass",
                command_or_entry="pytest focused",
                evidence="test-log.txt",
            )
            finalize_readiness(context, "chg")
            self.assertEqual(advance_change(context, "chg"), "candidate-review")

            dashboard = build_change_dashboard(context, "chg")
            self.assertIn("user-review", dashboard["allowed_next"])
            self.assertIn("final verification", dashboard["blocked_next"])
            with self.assertRaisesRegex(ChangeLifecycleError, "user acceptance"):
                advance_change(context, "chg")

            record_user_review(
                context,
                "chg",
                decision="approved",
                evidence="user accepted representative result",
            )
            self.assertEqual(advance_change(context, "chg"), "verifying")

    def test_changes_requested_returns_to_implementation_and_stales_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = project / "changes" / "active" / "chg"
            write_yaml(change / "change.yaml", base_change("chg"))
            freeze_then_implement(context, change)
            record_readiness(
                context,
                "chg",
                criterion_id="focused",
                result="pass",
                command_or_entry="pytest focused",
                evidence="test-log.txt",
            )
            finalize_readiness(context, "chg")
            advance_change(context, "chg")
            state = record_user_review(
                context,
                "chg",
                decision="changes-requested",
                evidence="representative behavior is not acceptable",
            )
            self.assertEqual(state, "implementing")
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            self.assertEqual(data["readiness"]["status"], "stale")
            self.assertFalse(data["completion"]["implementation_complete"])


if __name__ == "__main__":
    unittest.main()
