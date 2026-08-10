from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


HARNESS_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = HARNESS_ROOT / "runtime"
ASSETS = (
    HARNESS_ROOT
    / "adapters"
    / "default"
    / "skills"
    / "change-governor"
    / "assets"
)
CHANGE_ARTIFACTS = (
    "proposal.md",
    "design.md",
    "tasks.md",
    "verification.md",
    "knowledge-sync.md",
    "archive-summary.md",
)


def run_validator(script: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), str(path)],
        cwd=HARNESS_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def expect(
    label: str,
    result: subprocess.CompletedProcess[str],
    *,
    success: bool,
    contains: str | None = None,
) -> None:
    passed = result.returncode == 0 if success else result.returncode != 0
    combined = result.stdout + result.stderr
    if contains is not None:
        passed = passed and contains in combined
    if not passed:
        raise RuntimeError(
            f"{label} produced an unexpected result\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    print(f"{label}: {'pass' if success else 'blocked'}")


def write_change(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "change.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for name in CHANGE_ARTIFACTS:
        (root / name).write_text(
            "Synthetic acceptance artifact; no production source is modified.\n",
            encoding="utf-8",
        )


def change_fixture() -> dict:
    data = yaml.safe_load(
        (ASSETS / "change.yaml.template").read_text(encoding="utf-8")
    )
    data["id"] = "v5-high-risk-fixture"
    data["task_id"] = "v5-high-risk-fixture-task"
    data["title"] = "Synthetic high-risk governance fixture"
    data["risk"] = {"semantic": "high", "repository_change": "high"}
    data["critical_surfaces"] = [{
        "id": "synthetic-state-ownership",
        "risk_floor": "high",
        "required_validation": [
            "unresolved material decisions block lifecycle advancement",
            "explicit approval is required before implementation",
        ],
    }]
    data["approval"] = {
        "required": True,
        "status": "pending",
        "approved_by": None,
        "approved_at": None,
    }
    data["human_in_loop"] = {
        "mode": "guided",
        "mode_evidence": None,
        "decision_assessment": {
            "status": "required",
            "reasons": [
                "state ownership has two materially plausible semantics"
            ],
        },
        "decisions": [{
            "id": "DEC-SYNTHETIC-001",
            "question": "Which component owns committed state?",
            "options": ["analysis-object", "solver-step"],
            "recommendation": "analysis-object preserves existing ownership",
        }],
        "interruption_budget": {
            "batch_questions": True,
            "max_design_checkpoints": 1,
        },
    }
    data["change_budget"]["explicit_non_goals"] = [
        "no production source modification",
    ]
    data["change_budget"]["adjacent_issues"] = [
        "legacy knowledge index migration is evaluated separately",
    ]
    data["methodology"]["planning_level"] = "full"
    data["methodology"]["tdd_mode"] = "required"
    return data


def task_fixture() -> dict:
    data = yaml.safe_load(
        (ASSETS / "task.yaml.template").read_text(encoding="utf-8")
    )
    data["id"] = "v5-human-checkpoint-fixture"
    data["title"] = "Synthetic human checkpoint fixture"
    data["status"] = "active"
    data["learning"]["intake"] = {
        "status": "completed",
        "checked_at": "2026-08-05T00:00:00Z",
        "relevant_entries": [],
        "recommended_tools": [],
        "evidence": "synthetic fixture",
    }
    data["escalation"] = {
        "level": "human-checkpoint",
        "reason": "stronger-model review remained inconclusive",
        "signature": "synthetic-repeated-pivot",
        "related_refs": ["inv-synthetic"],
        "model_review": {
            "required": True,
            "status": "inconclusive",
            "role": "framework_scout",
            "model": "gpt-5.6-terra",
            "tier": "terra",
            "outcome": "inconclusive",
            "evidence_ref": "synthetic-terra-review",
        },
        "human_checkpoint": {
            "required": True,
            "status": "pending",
            "question": "Choose the state ownership boundary",
            "decision": None,
            "evidence": None,
        },
    }
    return data


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sitter-v5-high-risk-") as directory:
        root = Path(directory)
        change_root = root / "change"
        change = change_fixture()
        write_change(change_root, change)

        expect(
            "change-proposed-unresolved",
            run_validator("validate_change.py", change_root),
            success=True,
        )

        change["status"] = "approved"
        write_change(change_root, change)
        expect(
            "change-advanced-unresolved",
            run_validator("validate_change.py", change_root),
            success=False,
            contains="unresolved material human decisions",
        )

        resolved = copy.deepcopy(change)
        resolved["human_in_loop"]["decision_assessment"]["status"] = "resolved"
        resolved["human_in_loop"]["decisions"][0].update({
            "user_decision": "analysis-object",
            "evidence": "synthetic explicit acceptance decision",
        })
        write_change(change_root, resolved)
        expect(
            "change-resolved-unapproved",
            run_validator("validate_change.py", change_root),
            success=False,
            contains="HIGH/CRITICAL change is not approved",
        )

        resolved["approval"].update({
            "status": "approved",
            "approved_by": "synthetic-acceptance",
            "approved_at": "2026-08-05T00:00:00Z",
        })
        write_change(change_root, resolved)
        expect(
            "change-resolved-approved",
            run_validator("validate_change.py", change_root),
            success=True,
        )

        task_path = root / "task.yaml"
        task = task_fixture()
        task_path.write_text(
            yaml.safe_dump(task, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        expect(
            "task-human-checkpoint-active",
            run_validator("validate_task_state.py", task_path),
            success=False,
            contains="task must be blocked",
        )

        task["status"] = "blocked"
        task_path.write_text(
            yaml.safe_dump(task, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        expect(
            "task-human-checkpoint-blocked",
            run_validator("validate_task_state.py", task_path),
            success=True,
        )

    print("high_risk_fixture: passed")


if __name__ == "__main__":
    main()
