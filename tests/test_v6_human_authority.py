from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TEMPLATE = (
    ROOT
    / "adapters"
    / "default"
    / "skills"
    / "change-governor"
    / "assets"
    / "change.yaml.template"
)
ARTIFACTS = (
    "proposal.md",
    "design.md",
    "tasks.md",
    "verification.md",
    "knowledge-sync.md",
    "archive-summary.md",
)


def run_harness(project: Path, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / "harness.py"), "--project", str(project), *map(str, args)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def run_validator(change: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / "validate_change.py"), str(change)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def create_project(root: Path) -> tuple[Path, Path]:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")

    change = project / "changes" / "active" / "authority-change"
    change.mkdir(parents=True)
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data.update(
        {
            "id": "authority-change",
            "task_id": "authority-task",
            "title": "Authority change",
            "status": "implementing",
            "execution_state": "active",
        }
    )
    data["risk"] = {"semantic": "high", "repository_change": "high"}
    data["approval"] = {
        "required": True,
        "status": "approved",
        "approved_by": "fixture",
        "approved_at": "2026-08-10T00:00:00Z",
    }
    data["human_in_loop"] = {
        "mode": "guided",
        "mode_evidence": None,
        "decision_assessment": {
            "status": "resolved",
            "reasons": ["two state ownership choices remain materially valid"],
        },
        "decisions": [
            {
                "id": "DEC-H1",
                "question": "Which state ownership scheme is authoritative?",
                "options": ["A", "B"],
                "recommendation": "A",
                "user_decision": "B",
                "evidence": "user explicitly selected B",
            }
        ],
        "interruption_budget": {"batch_questions": True, "max_design_checkpoints": 1},
    }
    data["critical_surfaces"] = []
    data["change_budget"]["explicit_non_goals"] = []
    data["change_budget"]["adjacent_issues"] = []
    data["methodology"].update(
        {
            "planning_level": "full",
            "test_cleanup_complete": True,
            "retained_test_rationale": ["protect the decision authority contract"],
        }
    )
    (change / "change.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for name in ARTIFACTS:
        (change / name).write_text(
            f"# {name}\n\nWork is being performed under user choice B.\n",
            encoding="utf-8",
        )
    return project, change


class V6HumanAuthorityTests(unittest.TestCase):
    def test_review_packet_projects_user_choice_not_agent_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change = create_project(Path(directory))
            result = run_harness(project, "review", "authority-change")
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = yaml.safe_load(
                (change / "review-request.yaml").read_text(encoding="utf-8")
            )
            authority = packet["decision_authority"]
            self.assertEqual(authority["status"], "authoritative")
            self.assertEqual(authority["decisions"][0]["user_decision"], "B")
            self.assertNotIn("recommendation", authority["decisions"][0])
            self.assertEqual(
                packet["input_snapshot"]["human_decisions_sha256"],
                authority["sha256"],
            )
            self.assertIn("authoritative", packet["instructions"].lower())
            self.assertIn("BLOCK", packet["instructions"])

    def test_changing_user_choice_after_review_start_invalidates_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change = create_project(Path(directory))
            self.assertEqual(
                run_harness(project, "review", "authority-change").returncode,
                0,
            )
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            data["human_in_loop"]["decisions"][0]["user_decision"] = "A"
            data["human_in_loop"]["decisions"][0]["evidence"] = "silent drift to recommendation"
            (change / "change.yaml").write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            artifact = project / "review-output.md"
            artifact.write_text("# Review\n\nNo findings.\n", encoding="utf-8")
            result = run_harness(
                project,
                "record-review",
                "authority-change",
                "--artifact",
                artifact,
                "--architecture",
                "pass",
                "--scope",
                "pass",
                "--numerical-evidence",
                "pass",
                "--evidence-ref",
                "fixture-review",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("authoritative human decisions changed", result.stderr)

    def test_knowledge_candidate_with_old_human_decision_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, change = create_project(Path(directory))
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            data["status"] = "proposed"
            data["knowledge_sync"].update(
                {
                    "status": "candidate",
                    "candidate_ref": "changes/active/authority-change/knowledge-sync.md",
                    "human_decisions_sha256": "0" * 64,
                }
            )
            (change / "change.yaml").write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            result = run_validator(change)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("knowledge candidate does not match", result.stderr)


if __name__ == "__main__":
    unittest.main()
