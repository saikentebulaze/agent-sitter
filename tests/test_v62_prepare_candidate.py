from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TESTS = ROOT / "tests"
for path in (RUNTIME, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prepare_candidate import PrepareCandidateError, prepare_candidate  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_role_runner import RoleRunResult  # noqa: E402
from readiness import freeze_readiness_contract, record_readiness  # noqa: E402
from test_v62_atomic_review import _valid_codex_attestation  # noqa: E402


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


def setup_fixture(root: Path, *, add_unclassified_test: bool):
    project = root / "project"
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "tests@example.com")
    git(project, "config", "user.name", "Sitter Tests")
    (project / "src.cpp").write_text("// baseline\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-m", "baseline")
    context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")

    task = project / ".agent-work" / "task"
    write_yaml(
        task / "task.yaml",
        {
            "schema_version": 4,
            "id": "task",
            "status": "active",
            "execution": {"orchestrator_provider": "codex"},
        },
    )

    template = yaml.safe_load(
        (
            ROOT
            / "adapters/default/skills/change-governor/assets/change.yaml.template"
        ).read_text(encoding="utf-8")
    )
    template["id"] = "chg"
    template["task_id"] = "task"
    template["title"] = "Prepare candidate fixture"
    template["status"] = "approved"
    template["candidate_readiness_protocol"] = 1
    template["human_in_loop"]["decision_assessment"] = {
        "status": "not-required",
        "reasons": ["no material semantic fork"],
    }
    template["human_in_loop"]["decisions"] = []
    template["readiness"]["criteria"] = [
        {
            "id": "focused",
            "kind": "focused-test",
            "required": True,
            "description": "focused behavior passes",
        }
    ]

    change = project / "changes/active/chg"
    write_yaml(change / "change.yaml", template)
    for name in (
        "proposal.md",
        "design.md",
        "tasks.md",
        "verification.md",
        "knowledge-sync.md",
        "archive-summary.md",
    ):
        (change / name).write_text(
            f"# {name}\n\nFixture content long enough for validation.\n",
            encoding="utf-8",
        )

    freeze_readiness_contract(context, "chg")
    data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
    data["status"] = "implementing"
    write_yaml(change / "change.yaml", data)

    if add_unclassified_test:
        test = project / "tests/test_new_behavior.py"
        test.parent.mkdir()
        test.write_text("def test_new_behavior():\n    assert True\n", encoding="utf-8")

    record_readiness(
        context,
        "chg",
        criterion_id="focused",
        result="pass",
        command_or_entry="focused fixture",
        evidence="fixture:focused",
    )
    return project, change, context


def pass_runner(counter: list[int]):
    def run(context: ProjectContext, packet: dict, message: str) -> RoleRunResult:
        counter.append(1)
        session = "app-server-thread:prepare-candidate"
        return RoleRunResult(
            provider="codex",
            role_id="maintainer_reviewer",
            output=(
                "No blocking findings.\n\n"
                "```yaml\n"
                "sitter_review:\n"
                "  architecture: pass\n"
                "  scope: pass\n"
                "  numerical_evidence: pass\n"
                "  remediation_route: null\n"
                "```\n"
            ),
            packet=packet,
            attestation=_valid_codex_attestation(context, packet, session),
            evidence={"fixture": True},
            session_ref=session,
        )

    return run


class PrepareCandidateTests(unittest.TestCase):
    def test_unclassified_test_blocks_before_reviewer_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, context = setup_fixture(
                Path(directory),
                add_unclassified_test=True,
            )
            calls: list[int] = []
            with self.assertRaisesRegex(
                PrepareCandidateError,
                "changed test is unclassified",
            ):
                prepare_candidate(
                    context,
                    "chg",
                    role_runner=pass_runner(calls),
                )
            self.assertEqual(calls, [])

    def test_ready_change_reaches_candidate_review_in_one_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, change, context = setup_fixture(
                Path(directory),
                add_unclassified_test=False,
            )
            calls: list[int] = []
            result = prepare_candidate(
                context,
                "chg",
                role_runner=pass_runner(calls),
            )
            self.assertEqual(calls, [1])
            self.assertEqual(result["status"], "candidate-review")
            data = yaml.safe_load((change / "change.yaml").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "candidate-review")
            self.assertEqual(data["review"]["status"], "pass")
            self.assertEqual(data["user_review"]["status"], "pending")
            self.assertTrue((change / "test-finalization.yaml").is_file())
            self.assertFalse((change / "review-request.yaml").exists())


if __name__ == "__main__":
    unittest.main()
