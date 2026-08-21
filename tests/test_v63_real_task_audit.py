from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/acceptance/v63-pr-a-audit.py"
spec = importlib.util.spec_from_file_location("v63_pr_a_audit", SCRIPT)
assert spec and spec.loader
AUDIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUDIT)

SNAPSHOT = "fixture-production-snapshot"


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def base_change(status: str) -> dict:
    return {
        "id": "chg",
        "task_id": "task",
        "status": status,
        "candidate_readiness_protocol": 1,
        "readiness": {
            "status": "pass",
            "production_snapshot": {"sha256": SNAPSHOT},
        },
        "review": {
            "status": "pass",
            "execution": {
                "review_protocol": 2,
                "provider": "codex",
                "runtime_method": "app-server-isolated-agent",
                "attestation_ref": "evidence/attestation.yaml",
                "runtime_evidence_ref": "evidence/runtime.json",
                "output_ref": "evidence/review.md",
                "input_snapshot": {
                    "snapshot_protocol": 2,
                    "production_sha256": SNAPSHOT,
                },
            },
        },
        "review_history": [{"round": 1}],
        "user_review": {"status": "pending"},
        "verification": {"status": "pending", "latest_results": []},
        "knowledge_sync": {"status": "pending", "entries": []},
        "archive": {"experiment_cleanup_complete": False},
    }


def prepare_project(root: Path, status: str = "candidate-review") -> Path:
    project = root / "project"
    project.mkdir()
    parent = "archive" if status == "archived" else "active"
    write_yaml(project / f"changes/{parent}/chg/change.yaml", base_change(status))
    write_yaml(
        project / ".agent-work/task/task.yaml",
        {
            "id": "task",
            "status": "active",
            "learning": {
                "closeout": {"status": "pending"},
                "user_attention": {"required": False, "decision": "not-required"},
            },
        },
    )
    for ref in ("attestation.yaml", "runtime.json", "review.md"):
        path = project / "evidence" / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence\n", encoding="utf-8")
    return project


VALID = {
    "change": {"ok": True, "returncode": 0, "stdout": "valid", "stderr": ""},
    "task": {"ok": True, "returncode": 0, "stdout": "valid", "stderr": ""},
}
CURRENT = {
    "ok": True,
    "returncode": 0,
    "stdout": SNAPSHOT,
    "stderr": "",
    "sha256": SNAPSHOT,
}


class V63RealTaskAuditTests(unittest.TestCase):
    def audit(self, project: Path, phase: str, *, snapshot: dict | None = None) -> dict:
        with (
            mock.patch.object(AUDIT, "_installed_validation", return_value=VALID),
            mock.patch.object(
                AUDIT,
                "_installed_current_snapshot",
                return_value=CURRENT if snapshot is None else snapshot,
            ),
        ):
            return AUDIT.audit(project, "chg", phase)

    def test_candidate_phase_requires_true_human_stop_and_one_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = prepare_project(Path(directory))
            result = self.audit(project, "candidate")
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["checks"]["user_review_pending"])
            self.assertTrue(result["checks"]["readiness_matches_current_production"])
            self.assertTrue(result["checks"]["review_matches_current_production"])
            self.assertEqual(result["review_rounds"], 1)

    def test_candidate_phase_fails_when_current_production_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = prepare_project(Path(directory))
            stale = {
                "ok": True,
                "returncode": 0,
                "stdout": "different-snapshot",
                "stderr": "",
                "sha256": "different-snapshot",
            }
            result = self.audit(project, "candidate", snapshot=stale)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("readiness_matches_current_production", result["hard_failures"])
            self.assertIn("review_matches_current_production", result["hard_failures"])

    def test_closure_phase_distinguishes_engineering_proof_from_governance_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = prepare_project(Path(directory), status="syncing")
            change_path = project / "changes/active/chg/change.yaml"
            data = yaml.safe_load(change_path.read_text(encoding="utf-8"))
            data["user_review"] = {"status": "approved"}
            data["verification"] = {
                "status": "pass",
                "latest_results": [
                    {"id": "full", "production_snapshot_sha256": SNAPSHOT}
                ],
            }
            data["knowledge_sync"] = {"status": "candidate", "entries": [{"id": "K1"}]}
            write_yaml(change_path, data)
            result = self.audit(project, "closure")
            self.assertEqual(result["status"], "GOVERNANCE_PENDING")
            self.assertTrue(result["checks"]["final_verification_pass_or_partial"])
            self.assertTrue(result["checks"]["final_verification_matches_current_production"])
            self.assertIn("Knowledge status", " ".join(result["governance_pending"]))

    def test_archived_zero_candidate_closure_passes_when_task_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = prepare_project(Path(directory), status="archived")
            change_path = project / "changes/archive/chg/change.yaml"
            data = yaml.safe_load(change_path.read_text(encoding="utf-8"))
            data["user_review"] = {"status": "approved"}
            data["verification"] = {
                "status": "pass",
                "latest_results": [
                    {"id": "full", "production_snapshot_sha256": SNAPSHOT}
                ],
            }
            data["knowledge_sync"] = {"status": "deferred", "entries": []}
            data["archive"] = {"experiment_cleanup_complete": True}
            write_yaml(change_path, data)
            task_path = project / ".agent-work/task/task.yaml"
            task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
            task["status"] = "completed"
            task["learning"] = {
                "closeout": {"status": "assessed"},
                "user_attention": {"required": False, "decision": "not-required"},
            }
            write_yaml(task_path, task)
            result = self.audit(project, "closure")
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["normal_success_single_reviewer"])


if __name__ == "__main__":
    unittest.main()
