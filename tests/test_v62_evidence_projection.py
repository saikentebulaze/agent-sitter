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

from evidence_projection import (  # noqa: E402
    EvidenceProjectionError,
    record_verification,
    render_evidence,
)
from project_context import ProjectContext  # noqa: E402


def git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        text=True,
        capture_output=True,
    )


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def make_fixture(root: Path, *, status: str = "verifying", accepted: bool = True):
    project = root / "project"
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "tests@example.com")
    git(project, "config", "user.name", "Sitter Tests")
    (project / "src.cpp").write_text("// baseline\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-m", "baseline")

    change = project / "changes" / "active" / "chg"
    write_yaml(
        change / "change.yaml",
        {
            "schema_version": 4,
            "id": "chg",
            "title": "Projection fixture",
            "status": status,
            "candidate_readiness_protocol": 1,
            "readiness": {
                "assurance_class": "numerical",
                "status": "pass",
                "criteria": [
                    {
                        "id": "case",
                        "kind": "representative-case",
                        "required": True,
                        "description": "representative case",
                    }
                ],
                "latest_results": [
                    {
                        "criterion_id": "case",
                        "result": "pass",
                        "command_or_entry": "run case",
                        "observed": "0.4% displacement error",
                        "checked_at": "2026-08-18T00:00:00Z",
                        "evidence": "case.log",
                        "production_snapshot_sha256": "a" * 64,
                    }
                ],
                "contract_sha256": "b" * 64,
                "evidence_sha256": "c" * 64,
                "production_snapshot": {"sha256": "a" * 64},
            },
            "review": {
                "status": "pass",
                "architecture": "pass",
                "scope": "pass",
                "numerical_evidence": "pass",
                "execution": {
                    "output_ref": "changes/active/chg/reviews/round-1.md",
                    "runtime_evidence_ref": ".agent-work/task/review-runtime.yaml",
                },
            },
            "user_review": {
                "status": "approved" if accepted else "pending",
                "evidence": "user accepted case" if accepted else None,
            },
            "verification": {"status": "pending", "latest_results": []},
            "knowledge_sync": {"status": "pending"},
            "archive": {"experiment_cleanup_complete": False, "blockers": []},
        },
    )
    write_yaml(
        change / "test-finalization.yaml",
        {"schema_version": 1, "change_id": "chg", "decisions": []},
    )
    context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
    return project, change, context


class EvidenceProjectionTests(unittest.TestCase):
    def test_record_verification_is_authoritative_and_render_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, change, context = make_fixture(Path(directory))
            entry = record_verification(
                context,
                "chg",
                result_id="full-regression",
                kind="regression",
                result="pass",
                command_or_entry="ctest --output-on-failure",
                evidence="ci:123",
                observed="all suites passed",
                proves="broad regression remains green",
                does_not_prove="commercial-software equivalence beyond candidate case",
            )
            self.assertEqual(entry["result"], "pass")
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            self.assertEqual(data["verification"]["status"], "pass")
            self.assertEqual(len(data["verification"]["latest_results"]), 1)

            first = (change / "verification.md").read_text(encoding="utf-8")
            self.assertIn("Generated from structured Sitter evidence", first)
            self.assertIn("0.4% displacement error", first)
            self.assertIn("full-regression", first)
            self.assertIn("commercial-software equivalence", first)
            archive = (change / "archive-summary.md").read_text(encoding="utf-8")
            self.assertIn("Final verification: `pass`", archive)

            (change / "verification.md").write_text(
                "MANUAL DRIFT THAT MUST NOT BECOME AUTHORITY\n",
                encoding="utf-8",
            )
            render_evidence(context, "chg")
            second = (change / "verification.md").read_text(encoding="utf-8")
            self.assertEqual(first, second)
            render_evidence(context, "chg")
            self.assertEqual(
                second,
                (change / "verification.md").read_text(encoding="utf-8"),
            )

    def test_final_verification_cannot_be_recorded_before_user_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, context = make_fixture(
                Path(directory),
                status="candidate-review",
                accepted=False,
            )
            with self.assertRaisesRegex(
                EvidenceProjectionError,
                "after Candidate acceptance",
            ):
                record_verification(
                    context,
                    "chg",
                    result_id="full-regression",
                    kind="regression",
                    result="pass",
                    command_or_entry="ctest",
                    evidence="ci:blocked",
                )


if __name__ == "__main__":
    unittest.main()
