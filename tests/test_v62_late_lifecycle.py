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

from change_lifecycle import ChangeLifecycleError, advance_change  # noqa: E402
from production_snapshot import production_snapshot_sha256  # noqa: E402
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


def fixture(root: Path):
    project = root / "project"
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "tests@example.com")
    git(project, "config", "user.name", "Sitter Tests")
    (project / "src.cpp").write_text("// baseline\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-m", "baseline")
    context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
    snapshot = production_snapshot_sha256(project)
    contract = "b" * 64
    evidence = "c" * 64
    change = project / "changes/active/chg"
    write_yaml(
        change / "change.yaml",
        {
            "schema_version": 4,
            "id": "chg",
            "status": "verifying",
            "candidate_readiness_protocol": 1,
            "readiness": {
                "assurance_class": "standard",
                "status": "pass",
                "criteria": [
                    {
                        "id": "focused",
                        "kind": "focused-test",
                        "required": True,
                        "description": "focused behavior",
                    }
                ],
                "latest_results": [],
                "contract_sha256": contract,
                "evidence_sha256": evidence,
                "production_snapshot": {"sha256": snapshot},
            },
            "review": {
                "status": "pass",
                "execution": {
                    "input_snapshot": {
                        "snapshot_protocol": 2,
                        "production_sha256": snapshot,
                        "readiness_contract_sha256": contract,
                        "readiness_evidence_sha256": evidence,
                    }
                },
            },
            "user_review": {
                "status": "approved",
                "evidence": "accepted",
                "reviewed_at": "2026-08-18T00:00:00Z",
            },
            "verification": {"status": "pending", "latest_results": []},
            "knowledge_sync": {"status": "deferred", "deferred_reason": "fixture"},
            "archive": {
                "experiment_cleanup_complete": True,
                "temporary_production_files": [],
                "blockers": [],
            },
        },
    )
    return change, context


class LateLifecycleTests(unittest.TestCase):
    def test_final_verification_blocks_then_advances_to_archive_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            change, context = fixture(Path(directory))
            with self.assertRaisesRegex(ChangeLifecycleError, "final verification"):
                advance_change(context, "chg")

            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
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

            self.assertEqual(advance_change(context, "chg"), "syncing")
            self.assertEqual(advance_change(context, "chg"), "ready-to-archive")
            with self.assertRaisesRegex(ChangeLifecycleError, "archive transaction"):
                advance_change(context, "chg")


if __name__ == "__main__":
    unittest.main()
