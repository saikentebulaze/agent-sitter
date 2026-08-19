from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from change_lifecycle import (  # noqa: E402
    ChangeLifecycleError,
    advance_change,
    record_user_review,
)
from review_runner import run_atomic_review  # noqa: E402
from test_v62_atomic_review import (  # noqa: E402
    fake_role_runner,
    load_yaml,
    make_project,
    prepare_change,
    write_yaml,
)


class LateLifecycleTests(unittest.TestCase):
    def test_final_verification_blocks_then_advances_to_archive_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = prepare_change(project, context)
            run_atomic_review(
                context,
                "chg-one",
                role_runner=fake_role_runner(
                    "  architecture: pass\n"
                    "  scope: pass\n"
                    "  numerical_evidence: pass\n"
                    "  remediation_route: null\n"
                ),
            )
            self.assertEqual(advance_change(context, "chg-one"), "candidate-review")
            record_user_review(
                context,
                "chg-one",
                decision="approved",
                evidence="fixture human acceptance",
            )
            self.assertEqual(advance_change(context, "chg-one"), "verifying")

            with self.assertRaisesRegex(ChangeLifecycleError, "final verification"):
                advance_change(context, "chg-one")

            data = load_yaml(change / "change.yaml")
            data["verification"] = {
                "status": "pass",
                "latest_results": [
                    {
                        "id": "full",
                        "kind": "regression",
                        "result": "pass",
                        "command_or_entry": "ctest",
                        "checked_at": "2026-08-18T00:00:00Z",
                        "evidence": "ci:1",
                    }
                ],
            }
            write_yaml(change / "change.yaml", data)
            self.assertEqual(advance_change(context, "chg-one"), "syncing")

            data = load_yaml(change / "change.yaml")
            data["knowledge_sync"]["status"] = "deferred"
            data["knowledge_sync"]["deferred_reason"] = "fixture"
            data["archive"]["experiment_cleanup_complete"] = True
            data["archive"]["temporary_production_files"] = []
            data["archive"]["blockers"] = []
            write_yaml(change / "change.yaml", data)

            self.assertEqual(advance_change(context, "chg-one"), "ready-to-archive")
            with self.assertRaisesRegex(ChangeLifecycleError, "archive transaction"):
                advance_change(context, "chg-one")


if __name__ == "__main__":
    unittest.main()
