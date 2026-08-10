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

from adaptive_work import investigate_change, pivot_to_change  # noqa: E402
from core.work_risk import RiskLevel, RiskVector  # noqa: E402
from delegation_transaction import authorize_delegation, request_delegation  # noqa: E402
from governed_validation import validate_high_risk_exploration  # noqa: E402
from governed_work import record_claim, record_decision, record_evidence  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from risk_transaction import reassess_task_risk  # noqa: E402
from work_graph import WorkGraph, WorkGraphError  # noqa: E402


def create_project(root: Path) -> tuple[Path, ProjectContext]:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project, ProjectContext(ROOT, project, ROOT / "adapters" / "default")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def complete_independent_exploration_if_required(
    context: ProjectContext,
    task: str,
    investigation: str,
) -> None:
    """Complete one deterministic L2 Scout after the real request transaction.

    These lifecycle tests do not launch a live Codex process. They use the real
    authorization/request path to freeze an independent Context Capsule, then
    materialize the minimal completed record needed by the state validator.
    Real runtime/attestation remains an L3 acceptance concern.
    """

    task_root = context.project_root / ".agent-work" / task
    task_path = task_root / "task.yaml"
    data = load(task_path)
    risk = (data.get("work_risk") or {}).get("current") or {}
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    current_max = max(
        order.get(str(risk.get("semantic", "low")), 0),
        order.get(str(risk.get("repository_change", "low")), 0),
    )
    if current_max < order["high"]:
        return

    delegation = data.get("delegation") or {}
    for planned in delegation.get("planned") or []:
        if (
            str((planned.get("target") or {}).get("ref") or "") == investigation
            and str(planned.get("agent") or "") in {
                "source_locator", "context_scout", "test_scout", "framework_scout"
            }
            and str(planned.get("id") or "")
            in {
                str(item.get("id"))
                for item in delegation.get("completed") or []
                if isinstance(item, dict)
            }
        ):
            return

    authorization = delegation.get("authorization") or {}
    if authorization.get("status") != "granted":
        authorize_delegation(
            context,
            task,
            decision="required",
            scopes=["readonly-exploration"],
            evidence="deterministic V6 lifecycle fixture",
            parent_model="gpt-5.6-terra",
            parent_tier="terra",
        )

    request_path = request_delegation(
        context,
        task,
        role="context_scout",
        target_type="investigation",
        target_ref=investigation,
        purpose="independent lifecycle fixture exploration",
        question="Independently inspect the investigation before governed final truth.",
        decision_supported="Whether the Investigation may form governed final truth.",
        include=["."],
        exclude=[],
        start_refs=[],
        confirmed_facts=[],
    )

    data = load(task_path)
    planned = (data.get("delegation") or {}).get("planned")[-1]
    delegation_id = str(planned["id"])
    output = request_path.parent / "attempt-01.output.md"
    record = request_path.parent / "attempt-01.record.yaml"
    output.write_text(
        "# Deterministic independent exploration\n\nSynthetic L2 completion only.\n",
        encoding="utf-8",
    )
    record.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "delegation_id": delegation_id,
                "outcome": "completed",
                "fixture": "deterministic-l2",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    planned["status"] = "completed"
    data["delegation"].setdefault("completed", []).append(
        {
            "id": delegation_id,
            "agent": planned["agent"],
            "model": planned["model"],
            "tier": planned["tier"],
            "reasoning_effort": planned["reasoning_effort"],
            "execution": "native-subagent",
            "context": {"inheritance": "none"},
            "output_ref": output.relative_to(context.project_root).as_posix(),
            "record_ref": record.relative_to(context.project_root).as_posix(),
            "evidence_ref": f"fixture:{delegation_id}",
        }
    )
    task_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def actionable_decision(context: ProjectContext, task: str, investigation: str) -> None:
    record_evidence(
        context,
        task,
        investigation,
        evidence_id="evd-001",
        kind="experiment",
        source_ref="fixture:evidence",
        provenance="bounded unit fixture",
        reliability="high",
        supports=[],
        contradicts=[],
        limitations=[],
    )
    record_claim(
        context,
        task,
        investigation,
        claim_id="clm-001",
        statement="The bounded production action is supported",
        status="supported",
        confidence="high",
        supporting_evidence=["evd-001"],
        contradicting_evidence=[],
    )
    complete_independent_exploration_if_required(context, task, investigation)
    record_decision(
        context,
        task,
        investigation,
        decision_id="dec-001",
        statement="Proceed with the production change",
        status="accepted",
        claims=["clm-001"],
        evidence=["evd-001"],
        requires_human=False,
        evidence_ref=None,
    )


class AdaptiveWorkTests(unittest.TestCase):
    def test_change_to_investigation_automatically_raises_work_and_assurance_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="adaptive-task",
                title="Adaptive",
                entry="change",
                change_id="adaptive-change",
            )
            investigation = investigate_change(
                context,
                "adaptive-change",
                title="Unexpected result",
                question="Why did verification diverge?",
                signature="unexpected-result",
                discrimination_rationale=None,
            )
            self.assertEqual(investigation, "inv-001")
            task = load(task_root / "task.yaml")
            self.assertEqual(task["work_risk"]["current"]["semantic"], "high")
            self.assertEqual(task["work_risk"]["peak"]["semantic"], "high")
            self.assertEqual(task["delegation"]["decision"], "required")
            self.assertEqual(task["current_focus"], {"type": "investigation", "ref": "inv-001"})
            change = load(project / "changes" / "active" / "adaptive-change" / "change.yaml")
            self.assertEqual(change["execution_state"], "paused")
            self.assertEqual(change["risk"]["semantic"], "high")

    def test_investigation_to_change_propagates_current_risk_into_assurance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="adaptive-investigation",
                title="Adaptive investigation",
                entry="investigation",
                question="What behavior is correct?",
                signature="adaptive-investigation",
            )
            reassess_task_risk(
                context,
                "adaptive-investigation",
                target=RiskVector(RiskLevel.CRITICAL, RiskLevel.HIGH),
                reason="path-dependent production semantics discovered",
            )
            actionable_decision(context, "adaptive-investigation", "inv-001")
            change_root = pivot_to_change(
                context,
                "adaptive-investigation",
                "inv-001",
                change_id="critical-change",
                title="Implement confirmed semantics",
                rationale="accepted evidence-backed decision",
            )
            change = load(change_root / "change.yaml")
            self.assertEqual(
                change["risk"],
                {"semantic": "critical", "repository_change": "high"},
            )
            task = load(task_root / "task.yaml")
            self.assertEqual(task["current_focus"], {"type": "change", "ref": "critical-change"})
            self.assertEqual(task["work_risk"]["peak"]["semantic"], "critical")

    def test_high_risk_exploration_gate_blocks_active_implementation_without_scout(self) -> None:
        graph = WorkGraph(
            task_root=Path("/tmp/task"),
            task={
                "id": "demo",
                "work_risk": {
                    "current": {"semantic": "low", "repository_change": "low"},
                    "peak": {"semantic": "high", "repository_change": "medium"},
                    "history": [],
                },
                "delegation": {"planned": [], "completed": []},
            },
            investigations={},
            changes={
                "change-1": (
                    Path("/tmp/change-1"),
                    {
                        "id": "change-1",
                        "status": "implementing",
                        "execution_state": "active",
                        "relations": {"derived_from": {"investigations": []}},
                    },
                )
            },
        )
        with self.assertRaisesRegex(WorkGraphError, "independent exploration"):
            validate_high_risk_exploration(graph)

        graph.task["delegation"] = {
            "planned": [
                {
                    "id": "dlg-001",
                    "agent": "context_scout",
                    "target": {"type": "change", "ref": "change-1"},
                }
            ],
            "completed": [{"id": "dlg-001"}],
        }
        validate_high_risk_exploration(graph)

    def test_paused_high_risk_change_does_not_require_scout_until_resume(self) -> None:
        graph = WorkGraph(
            task_root=Path("/tmp/task"),
            task={
                "id": "demo",
                "work_risk": {
                    "current": {"semantic": "high", "repository_change": "medium"},
                    "peak": {"semantic": "high", "repository_change": "medium"},
                    "history": [],
                },
                "delegation": {"planned": [], "completed": []},
            },
            investigations={},
            changes={
                "change-1": (
                    Path("/tmp/change-1"),
                    {
                        "id": "change-1",
                        "status": "implementing",
                        "execution_state": "paused",
                        "relations": {"derived_from": {"investigations": []}},
                    },
                )
            },
        )
        validate_high_risk_exploration(graph)


if __name__ == "__main__":
    unittest.main()
