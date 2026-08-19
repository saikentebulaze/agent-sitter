from __future__ import annotations

import hashlib
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

from change_lifecycle import advance_change  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_role_runner import RoleRunResult  # noqa: E402
from readiness import (  # noqa: E402
    finalize_readiness,
    freeze_readiness_contract,
    record_readiness,
)
from review_runner import run_atomic_review  # noqa: E402


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


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def make_project(root: Path) -> tuple[Path, ProjectContext]:
    project = root / "project"
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "tests@example.com")
    git(project, "config", "user.name", "Sitter Tests")
    (project / "src").mkdir()
    (project / "src" / "solver.cpp").write_text("// baseline\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-m", "baseline")
    context = ProjectContext(ROOT, project, ROOT / "adapters" / "default")
    return project, context


def prepare_change(project: Path, context: ProjectContext) -> Path:
    task = project / ".agent-work" / "task-one"
    write_yaml(
        task / "task.yaml",
        {
            "schema_version": 4,
            "id": "task-one",
            "status": "active",
            "execution": {"orchestrator_provider": "codex"},
        },
    )

    template = yaml.safe_load(
        (
            ROOT
            / "adapters"
            / "default"
            / "skills"
            / "change-governor"
            / "assets"
            / "change.yaml.template"
        ).read_text(encoding="utf-8")
    )
    template["id"] = "chg-one"
    template["task_id"] = "task-one"
    template["title"] = "Atomic review fixture"
    template["status"] = "approved"
    template["candidate_readiness_protocol"] = 1
    template["risk"] = {"semantic": "medium", "repository_change": "medium"}
    template["human_in_loop"]["decision_assessment"] = {
        "status": "not-required",
        "reasons": ["fixture has no material semantic fork"],
    }
    template["human_in_loop"]["decisions"] = []
    template["readiness"]["assurance_class"] = "standard"
    template["readiness"]["criteria"] = [
        {
            "id": "focused-regression",
            "kind": "focused-test",
            "required": True,
            "description": "directly affected behavior passes focused regression",
        }
    ]

    change = project / "changes" / "active" / "chg-one"
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
            f"# {name}\n\nEnough deterministic fixture content for validation.\n",
            encoding="utf-8",
        )

    freeze_readiness_contract(context, "chg-one")
    data = load_yaml(change / "change.yaml")
    data["status"] = "implementing"
    write_yaml(change / "change.yaml", data)
    record_readiness(
        context,
        "chg-one",
        criterion_id="focused-regression",
        result="pass",
        command_or_entry="focused fixture",
        evidence="fixture:focused-pass",
        observed="target behavior passed",
    )
    finalize_readiness(context, "chg-one")

    write_yaml(
        change / "test-finalization.yaml",
        {"schema_version": 1, "change_id": "chg-one", "decisions": []},
    )
    data = load_yaml(change / "change.yaml")
    data["methodology"]["test_cleanup_complete"] = True
    data["methodology"]["test_cleanup_evidence"] = (
        "changes/active/chg-one/test-finalization.yaml"
    )
    write_yaml(change / "change.yaml", data)
    return change


def _valid_codex_attestation(context: ProjectContext, packet: dict, session: str) -> dict:
    requested = packet["requested_profile"]
    profile = Path(str(requested["source"])).resolve()
    profile_ref = profile.relative_to(context.package_root.resolve()).as_posix()
    profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
    return {
        "schema_version": 2,
        "execution": {
            "method": "app-server-isolated-agent",
            "collector": "codex-app-server-managed-v1",
            "session_ref": session,
            "thread_id": "fixture-review",
            "turn_id": "fixture-turn",
        },
        "observed": {
            "agent": requested["agent"],
            "agent_binding": "verified-thread-start-profile",
            "model": requested["model"],
            "tier": requested["tier"],
            "reasoning_effort": requested["reasoning_effort"],
            "sandbox_mode": "read-only",
            "context_inheritance": "none",
            "child_thread_id": "fixture-review",
            "parent_thread_id": None,
            "forked_from_id": None,
            "cwd": str(context.project_root.resolve()),
        },
        "evidence": {
            "source": "verified-app-server-managed",
            "agent_profile_ref": profile_ref,
            "agent_profile_sha256": profile_hash,
            "developer_instructions_sha256": "fixture-instructions",
            "thread_start_request_sha256": "fixture-thread-start",
            "turn_start_request_sha256": "fixture-turn-start",
        },
    }


def fake_role_runner(verdict: str):
    def run(context: ProjectContext, packet: dict, message: str) -> RoleRunResult:
        if packet.get("review_protocol") != 2:
            raise AssertionError("review protocol was not frozen")
        if (packet.get("input_snapshot") or {}).get("snapshot_protocol") != 2:
            raise AssertionError("snapshot protocol 2 was not frozen")
        if "Candidate Readiness Review" not in message:
            raise AssertionError("review instructions were not supplied")
        session = "app-server-thread:fixture-review"
        output = (
            "Fixture reviewer findings.\n\n"
            "```yaml\n"
            "sitter_review:\n"
            f"{verdict}"
            "```\n"
        )
        return RoleRunResult(
            provider="codex",
            role_id="maintainer_reviewer",
            output=output,
            packet=packet,
            attestation=_valid_codex_attestation(context, packet, session),
            evidence={"fixture": True},
            session_ref=session,
        )

    return run


def validate_change(project: Path, change: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / "validate_change.py"), str(change)],
        cwd=project,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


class AtomicReviewTests(unittest.TestCase):
    def test_pass_review_records_protocol2_and_can_reach_candidate_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = prepare_change(project, context)
            result = run_atomic_review(
                context,
                "chg-one",
                role_runner=fake_role_runner(
                    "  architecture: pass\n"
                    "  scope: pass\n"
                    "  numerical_evidence: pass\n"
                    "  remediation_route: null\n"
                ),
            )
            self.assertEqual(result["status"], "pass")
            data = load_yaml(change / "change.yaml")
            execution = data["review"]["execution"]
            self.assertEqual(execution["review_protocol"], 2)
            self.assertEqual(execution["provider"], "codex")
            self.assertEqual(execution["tier"], "medium")
            self.assertEqual(execution["method"], "provider-managed-readonly")
            self.assertEqual(execution["runtime_method"], "app-server-isolated-agent")
            self.assertFalse((change / "review-request.yaml").exists())
            self.assertTrue((change / "reviews" / "round-1.request.yaml").is_file())

            validated = validate_change(project, change)
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(advance_change(context, "chg-one"), "candidate-review")
            validated = validate_change(project, change)
            self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_protocol2_review_cannot_survive_deleted_or_tampered_attestation(self) -> None:
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
            data = load_yaml(change / "change.yaml")
            attestation = project / data["review"]["execution"]["attestation_ref"]
            original = attestation.read_text(encoding="utf-8")

            attestation.unlink()
            rejected = validate_change(project, change)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("attestation", rejected.stderr.lower())

            attestation.write_text(original, encoding="utf-8")
            tampered = load_yaml(attestation)
            tampered["execution"]["session_ref"] = "app-server-thread:forged"
            write_yaml(attestation, tampered)
            rejected = validate_change(project, change)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("session", rejected.stderr.lower())

    def test_implementation_block_returns_to_implementation_and_stales_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = prepare_change(project, context)
            result = run_atomic_review(
                context,
                "chg-one",
                role_runner=fake_role_runner(
                    "  architecture: block\n"
                    "  scope: pass\n"
                    "  numerical_evidence: warn\n"
                    "  remediation_route: implementation\n"
                ),
            )
            self.assertEqual(result["status"], "block")
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "implementing")
            self.assertEqual(data["readiness"]["status"], "stale")
            self.assertTrue(data["remediation"]["within_approved_scope"])
            validated = validate_change(project, change)
            self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_semantic_block_routes_to_design_without_claiming_approved_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = make_project(Path(directory))
            change = prepare_change(project, context)
            result = run_atomic_review(
                context,
                "chg-one",
                role_runner=fake_role_runner(
                    "  architecture: block\n"
                    "  scope: warn\n"
                    "  numerical_evidence: pass\n"
                    "  remediation_route: awaiting-production-design\n"
                ),
            )
            self.assertEqual(result["remediation_route"], "awaiting-production-design")
            data = load_yaml(change / "change.yaml")
            self.assertEqual(data["status"], "designed")
            self.assertFalse(data["remediation"]["within_approved_scope"])
            validated = validate_change(project, change)
            self.assertEqual(validated.returncode, 0, validated.stderr)


if __name__ == "__main__":
    unittest.main()
