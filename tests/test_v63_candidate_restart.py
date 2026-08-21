from __future__ import annotations

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

from prepare_candidate import PrepareCandidateError, prepare_candidate  # noqa: E402
from test_v62_atomic_review import load_yaml  # noqa: E402
from test_v62_prepare_candidate import pass_runner, setup_fixture  # noqa: E402


class V63CandidateRestartTests(unittest.TestCase):
    def test_repeating_prepare_at_current_human_stop_does_not_launch_second_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, change, context = setup_fixture(
                Path(directory),
                add_unclassified_test=False,
            )
            calls: list[int] = []
            first = prepare_candidate(
                context,
                "chg",
                role_runner=pass_runner(calls),
            )
            self.assertEqual(first["status"], "candidate-review")
            self.assertFalse(first["idempotent"])
            second = prepare_candidate(
                context,
                "chg",
                role_runner=pass_runner(calls),
            )
            self.assertEqual(second["status"], "candidate-review")
            self.assertTrue(second["idempotent"])
            self.assertEqual(calls, [1])
            data = load_yaml(change / "change.yaml")
            self.assertEqual(len(data["review_history"]), 1)
            self.assertEqual(data["user_review"]["status"], "pending")

    def test_human_stop_rejects_readiness_resubmission_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, change, context = setup_fixture(
                Path(directory),
                add_unclassified_test=False,
            )
            calls: list[int] = []
            prepare_candidate(context, "chg", role_runner=pass_runner(calls))
            before = (change / "change.yaml").read_bytes()
            with self.assertRaisesRegex(
                PrepareCandidateError,
                "already prepared",
            ):
                prepare_candidate(
                    context,
                    "chg",
                    readiness_batch=[
                        {
                            "criterion_id": "focused",
                            "result": "pass",
                            "command_or_entry": "redundant",
                            "evidence": "fixture:redundant",
                        }
                    ],
                    role_runner=pass_runner(calls),
                )
            self.assertEqual((change / "change.yaml").read_bytes(), before)
            self.assertEqual(calls, [1])

    def test_human_stop_reuse_fails_closed_after_production_change_without_new_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, change, context = setup_fixture(
                Path(directory),
                add_unclassified_test=False,
            )
            calls: list[int] = []
            prepare_candidate(context, "chg", role_runner=pass_runner(calls))
            (project / "src.cpp").write_text("// production changed after review\n", encoding="utf-8")
            with self.assertRaisesRegex(
                PrepareCandidateError,
                "stale because production/test files changed",
            ):
                prepare_candidate(
                    context,
                    "chg",
                    role_runner=pass_runner(calls),
                )
            self.assertEqual(calls, [1])
            data = load_yaml(change / "change.yaml")
            self.assertEqual(len(data["review_history"]), 1)
            self.assertEqual(data["status"], "candidate-review")


if __name__ == "__main__":
    unittest.main()
