from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


HARNESS_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = HARNESS_ROOT / "runtime"
TEMPLATE = (
    HARNESS_ROOT
    / "adapters"
    / "default"
    / "skills"
    / "change-governor"
    / "assets"
    / "change.yaml.template"
)
ARTIFACTS = (
    "proposal.md",
    "design.md",
    "tasks.md",
    "verification.md",
    "knowledge-sync.md",
    "archive-summary.md",
)


def write_change(root: Path, *, resolved: bool, downstream_choice: str) -> None:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    data.update({
        "id": "human-authority-fixture",
        "task_id": "human-authority-task",
        "title": "Human authority fixture",
        "status": "approved",
        "execution_state": "active",
    })
    data["risk"] = {"semantic": "high", "repository_change": "high"}
    data["approval"] = {
        "required": True,
        "status": "approved",
        "approved_by": "fixture",
        "approved_at": "2026-08-10T00:00:00Z",
    }
    decision = {
        "id": "DEC-H1",
        "question": "Which state ownership scheme is authoritative?",
        "options": ["A", "B"],
        "recommendation": "A",
    }
    if resolved:
        decision.update({
            "user_decision": "B",
            "evidence": "fixture-user-explicitly-selected-B",
        })
    data["human_in_loop"] = {
        "mode": "guided",
        "mode_evidence": None,
        "decision_assessment": {
            "status": "resolved" if resolved else "required",
            "reasons": ["both ownership schemes are technically plausible"],
        },
        "decisions": [decision],
        "interruption_budget": {"batch_questions": True, "max_design_checkpoints": 1},
    }

    root.mkdir(parents=True, exist_ok=True)
    (root / "change.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for name in ARTIFACTS:
        text = f"# {name}\n\nAuthoritative implementation choice: {downstream_choice}.\n"
        (root / name).write_text(text, encoding="utf-8")


def validate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / "validate_change.py"), str(root)],
        cwd=HARNESS_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sitter-v6-human-") as directory:
        base = Path(directory)

        unresolved = base / "unresolved"
        write_change(unresolved, resolved=False, downstream_choice="A")
        h2 = validate(unresolved)

        drift = base / "drift"
        # User selected B, but downstream artifacts intentionally drift back to A.
        write_change(drift, resolved=True, downstream_choice="A")
        h1 = validate(drift)

        result = {
            "H1-human-override": {
                "v6_target": "downstream drift to A is blocked after user selected B",
                "current_validator_allows_drift": h1.returncode == 0,
                "v6_pass": h1.returncode != 0,
                "stderr": h1.stderr.strip(),
            },
            "H2-material-decision-gate": {
                "v6_target": "unresolved material decision blocks advanced HIGH work",
                "current_validator_blocks": h2.returncode != 0,
                "v6_pass": h2.returncode != 0,
                "stderr": h2.stderr.strip(),
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
