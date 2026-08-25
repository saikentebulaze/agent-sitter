from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TESTS = ROOT / "tests"
for path in (RUNTIME, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from implementation_entry import (  # noqa: E402
    ImplementationEntryError,
    begin_implementation,
)
from prepare_candidate import prepare_candidate  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from test_v62_atomic_review import fake_role_runner, load_yaml, write_yaml  # noqa: E402
from test_v62_rc2_closure import (  # noqa: E402
    PASS_VERDICT,
    make_project,
    write_manifest_lock,
)


def setup_change(root: Path):
    project, context = make_project(root)
    write_manifest_lock(project)
    initialize_provider_task(
        context,
        task_id="task-entry",
        title="V6.3 implementation entry",
        entry="change",
        provider_id="codex",
        change_id="chg-entry",
    )
    change = project / "changes/active/chg-entry"
    data = load_yaml(change / "change.yaml")
    data["change_budget"]["allowed_files"] = ["src/solver.cpp"]
    data["change_budget"]["explicit_non_goals"] = ["no adjacent refactor"]
    write_yaml(change / "change.yaml", data)
    return project, context, change


class V63ImplementationEntryTests(unittest.TestCase):
    def test_begin_implementation_closes_planning_states_and_freezes_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = setup_change(Path(directory))
            result = begin_implementation(context, "chg-entry")
            self.assertEqual(result["status"], "implementing")
            self.assertEqual(
                result["transitions"],
                ["designed", "approved", "implementing"],
            )
            self.assertFalse(result["idempotent"])
            self.assertTrue(result["readiness_contract_sha256"])

            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "implementing")
            self.assertTrue(data["readiness"]["contract_sha256"])
            self.assertTrue(data["readiness"]["frozen_at"])
            self.assertFalse(data["completion"]["implementation_complete"])
            self.assertFalse(data["completion"]["ready_for_user_review"])

            repeated = begin_implementation(context, "chg-entry")
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(repeated["transitions"], [])

    def test_begin_implementation_connects_cleanly_to_prepare_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = setup_change(Path(directory))
            begin_implementation(context, "chg-entry")
            result = prepare_candidate(
                context,
                "chg-entry",
                readiness_batch=[
                    {
                        "criterion_id": "focused-regression",
                        "result": "pass",
                        "command_or_entry": "fixture focused regression",
                        "evidence": "fixture:focused-pass",
                    }
                ],
                role_runner=fake_role_runner(PASS_VERDICT),
            )
            self.assertEqual(result["status"], "candidate-review")
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "candidate-review")
            self.assertEqual(data["review"]["status"], "pass")
            self.assertEqual(len(data["review_history"]), 1)
            self.assertEqual(data["user_review"]["status"], "pending")

    def test_unresolved_human_decision_blocks_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = setup_change(Path(directory))
            data = load_yaml(change / "change.yaml")
            data["human_in_loop"]["decision_assessment"] = {
                "status": "required",
                "reasons": ["fixture material semantic fork"],
            }
            data["human_in_loop"]["decisions"] = [
                {
                    "id": "D1",
                    "question": "Choose fixture behavior",
                    "options": ["A", "B"],
                    "recommendation": "A",
                }
            ]
            write_yaml(change / "change.yaml", data)
            before = (change / "change.yaml").read_bytes()

            with self.assertRaisesRegex(
                ImplementationEntryError,
                "human design decisions must be resolved",
            ):
                begin_implementation(context, "chg-entry")
            self.assertEqual((change / "change.yaml").read_bytes(), before)

    def test_empty_change_budget_blocks_before_readiness_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = setup_change(Path(directory))
            data = load_yaml(change / "change.yaml")
            data["change_budget"]["allowed_files"] = []
            data["change_budget"]["allowed_modules"] = []
            write_yaml(change / "change.yaml", data)
            before = (change / "change.yaml").read_bytes()

            with self.assertRaisesRegex(
                ImplementationEntryError,
                "Change Budget must define",
            ):
                begin_implementation(context, "chg-entry")
            self.assertEqual((change / "change.yaml").read_bytes(), before)
            self.assertFalse(load_yaml(change / "change.yaml")["readiness"]["contract_sha256"])

    def test_high_repository_risk_requires_explicit_approval_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context, change = setup_change(Path(directory))
            data = load_yaml(change / "change.yaml")
            data["risk"]["repository_change"] = "high"
            write_yaml(change / "change.yaml", data)
            before = (change / "change.yaml").read_bytes()

            with self.assertRaisesRegex(
                ImplementationEntryError,
                "Change approval is required",
            ):
                begin_implementation(context, "chg-entry")
            self.assertEqual((change / "change.yaml").read_bytes(), before)

            result = begin_implementation(
                context,
                "chg-entry",
                approved_by="user",
            )
            self.assertEqual(result["status"], "implementing")
            data = load_yaml(change / "change.yaml")
            self.assertTrue(data["approval"]["required"])
            self.assertEqual(data["approval"]["status"], "approved")
            self.assertEqual(data["approval"]["approved_by"], "user")
            self.assertTrue(data["approval"]["approved_at"])

    def test_public_help_exposes_begin_implementation_before_candidate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RUNTIME / "harness.py"), "--help"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("begin-implementation CHANGE", result.stdout)
        self.assertLess(
            result.stdout.index("begin-implementation CHANGE"),
            result.stdout.index("prepare-candidate CHANGE --readiness-batch FILE"),
        )


if __name__ == "__main__":
    unittest.main()
