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

from core.work_risk import RiskLevel, RiskVector  # noqa: E402
from governed_validation import validate_governed_work_graph  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from provider_task import initialize_provider_task  # noqa: E402
from risk_transaction import (  # noqa: E402
    RiskTransactionError,
    reassess_task_risk,
)


def create_project(root: Path) -> tuple[Path, ProjectContext]:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        "package: sitter\nformat_version: 1\n",
        encoding="utf-8",
    )
    return project, ProjectContext(ROOT, project, ROOT / "adapters" / "default")


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class RiskTransactionTests(unittest.TestCase):
    def test_new_governed_task_starts_medium_and_tracks_peak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="risk-demo",
                title="Risk demo",
                entry="change",
                change_id="risk-change",
            )
            task = read_yaml(task_root / "task.yaml")
            self.assertEqual(
                task["work_risk"]["current"],
                {"semantic": "medium", "repository_change": "medium"},
            )
            self.assertEqual(task["work_risk"]["peak"], task["work_risk"]["current"])
            self.assertEqual(task["work_risk"]["history"], [])
            self.assertEqual(task["delegation"]["decision"], "not-needed")
            validate_governed_work_graph(context, task_root)

    def test_risk_upgrade_can_raise_change_assurance_and_scout_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="risk-demo",
                title="Risk demo",
                entry="change",
                change_id="risk-change",
            )
            current, peak, assurance_change = reassess_task_risk(
                context,
                "risk-demo",
                target=RiskVector(RiskLevel.HIGH, RiskLevel.HIGH),
                reason="state lifecycle discovered",
                evidence_ref="code:state-owner",
                raise_assurance=True,
            )
            self.assertEqual(current, RiskVector(RiskLevel.HIGH, RiskLevel.HIGH))
            self.assertEqual(peak, current)
            self.assertEqual(assurance_change, "risk-change")

            task = read_yaml(task_root / "task.yaml")
            self.assertEqual(task["work_risk"]["current"]["semantic"], "high")
            self.assertEqual(len(task["work_risk"]["history"]), 1)
            self.assertEqual(task["delegation"]["decision"], "required")
            self.assertTrue(
                any(
                    item.get("type") == "delegation-obligation-raised"
                    for item in task["timeline"]
                )
            )
            change = read_yaml(project / "changes" / "active" / "risk-change" / "change.yaml")
            self.assertEqual(
                change["risk"],
                {"semantic": "high", "repository_change": "high"},
            )

    def test_cleanup_can_lower_current_risk_without_lowering_assurance_or_scout_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="risk-demo",
                title="Risk demo",
                entry="change",
                change_id="risk-change",
            )
            reassess_task_risk(
                context,
                "risk-demo",
                target=RiskVector(RiskLevel.HIGH, RiskLevel.HIGH),
                reason="core state semantics changed",
                raise_assurance=True,
            )
            current, peak, assurance_change = reassess_task_risk(
                context,
                "risk-demo",
                target=RiskVector(RiskLevel.LOW, RiskLevel.LOW),
                reason="only bounded cleanup remains",
                remaining_work_bounded=True,
            )
            self.assertEqual(current, RiskVector(RiskLevel.LOW, RiskLevel.LOW))
            self.assertEqual(peak, RiskVector(RiskLevel.HIGH, RiskLevel.HIGH))
            self.assertIsNone(assurance_change)
            change = read_yaml(project / "changes" / "active" / "risk-change" / "change.yaml")
            self.assertEqual(
                change["risk"],
                {"semantic": "high", "repository_change": "high"},
            )
            task = read_yaml(task_root / "task.yaml")
            self.assertEqual(len(task["work_risk"]["history"]), 2)
            self.assertEqual(task["delegation"]["decision"], "required")

    def test_open_investigation_blocks_risk_reduction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context = create_project(Path(directory))
            initialize_provider_task(
                context,
                task_id="risk-investigation",
                title="Risk investigation",
                entry="investigation",
                question="Why?",
                signature="risk-investigation",
            )
            reassess_task_risk(
                context,
                "risk-investigation",
                target=RiskVector(RiskLevel.HIGH, RiskLevel.MEDIUM),
                reason="unexpected result",
            )
            with self.assertRaisesRegex(RiskTransactionError, "cannot be reduced"):
                reassess_task_risk(
                    context,
                    "risk-investigation",
                    target=RiskVector(RiskLevel.LOW, RiskLevel.LOW),
                    reason="premature cleanup claim",
                    remaining_work_bounded=True,
                )

    def test_legacy_task_without_work_risk_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, context = create_project(Path(directory))
            task_root = initialize_provider_task(
                context,
                task_id="legacy-risk",
                title="Legacy",
                entry="change",
                change_id="legacy-change",
            )
            task_path = task_root / "task.yaml"
            task = read_yaml(task_path)
            task.pop("work_risk")
            task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
            validate_governed_work_graph(context, task_root)

            current, peak, _ = reassess_task_risk(
                context,
                "legacy-risk",
                target=RiskVector(RiskLevel.HIGH, RiskLevel.MEDIUM),
                reason="legacy task discovered higher risk",
            )
            self.assertEqual(current.semantic, RiskLevel.HIGH)
            self.assertEqual(peak.semantic, RiskLevel.HIGH)
            task = read_yaml(task_path)
            self.assertEqual(task["delegation"]["decision"], "required")
            validate_governed_work_graph(context, task_root)


if __name__ == "__main__":
    unittest.main()
