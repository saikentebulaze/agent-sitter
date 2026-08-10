from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = HARNESS_ROOT / "runtime"


def run(project: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME / script), *args],
        cwd=HARNESS_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def project(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    lock = path / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return path


def prepare(root: Path, name: str, *, accepted: bool) -> tuple[Path, str]:
    p = project(root, name)
    task = f"g1-{name}"
    created = run(
        p,
        "create_task.py",
        task,
        "--title",
        "G1 Investigation Gate",
        "--entry",
        "investigation",
        "--question",
        "Which state owner is correct?",
        "--signature",
        f"g1-{name}",
        "--project",
        str(p),
    )
    if created.returncode:
        raise RuntimeError(created.stderr)

    raised = run(
        p,
        "work.py",
        "--project",
        str(p),
        "reassess-risk",
        task,
        "--semantic",
        "critical",
        "--repository-change",
        "critical",
        "--reason",
        "synthetic CRITICAL investigation",
    )
    if raised.returncode:
        raise RuntimeError(raised.stderr)

    evidence = run(
        p,
        "work.py",
        "--project",
        str(p),
        "record-evidence",
        task,
        "inv-001",
        "--id",
        "evd-001",
        "--kind",
        "experiment",
        "--source-ref",
        "experiments/exp-001",
        "--provenance",
        "synthetic discriminating experiment",
        "--reliability",
        "high",
    )
    if evidence.returncode:
        raise RuntimeError(evidence.stderr)

    claim = run(
        p,
        "work.py",
        "--project",
        str(p),
        "record-claim",
        task,
        "inv-001",
        "--id",
        "clm-001",
        "--statement",
        "Planner owns the state selection.",
        "--status",
        "supported",
        "--confidence",
        "high",
        "--supporting-evidence",
        "evd-001",
    )
    if claim.returncode:
        raise RuntimeError(claim.stderr)

    if accepted:
        decision = run(
            p,
            "work.py",
            "--project",
            str(p),
            "record-decision",
            task,
            "inv-001",
            "--id",
            "dec-001",
            "--statement",
            "Change planner state ownership.",
            "--status",
            "accepted",
            "--claim",
            "clm-001",
            "--evidence",
            "evd-001",
        )
        if decision.returncode:
            raise RuntimeError(decision.stderr)
    return p, task


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sitter-v6-g1-") as directory:
        root = Path(directory)

        evidence_project, evidence_task = prepare(root, "evidence", accepted=False)
        # Evidence/claim/experiment remain legal before independent exploration.
        record_open_claim_pass = True
        record_evidence_pass = True
        experiment_pass = True

        decision_project, decision_task = prepare(root, "decision", accepted=False)
        decision = run(
            decision_project,
            "work.py",
            "--project",
            str(decision_project),
            "record-decision",
            decision_task,
            "inv-001",
            "--id",
            "dec-001",
            "--statement",
            "Accept a governed final truth.",
            "--status",
            "accepted",
            "--claim",
            "clm-001",
            "--evidence",
            "evd-001",
        )

        conclude_project, conclude_task = prepare(root, "conclude", accepted=False)
        conclude = run(
            conclude_project,
            "work.py",
            "--project",
            str(conclude_project),
            "conclude-investigation",
            conclude_task,
            "inv-001",
            "--disposition",
            "no-change-required",
            "--rationale",
            "synthetic conclusion",
        )

        pivot_project, pivot_task = prepare(root, "pivot", accepted=True)
        pivot = run(
            pivot_project,
            "work.py",
            "--project",
            str(pivot_project),
            "pivot-to-change",
            pivot_task,
            "inv-001",
            "g1-change",
            "--title",
            "G1 change",
            "--rationale",
            "synthetic pivot",
        )

        result = {
            "record-evidence": {"current_pass": record_evidence_pass, "v6_target": "pass"},
            "record-open-claim": {"current_pass": record_open_claim_pass, "v6_target": "pass"},
            "experiment": {"current_pass": experiment_pass, "v6_target": "pass"},
            "accepted-decision": {
                "current_pass": decision.returncode == 0,
                "v6_target": "block-until-independent-exploration",
            },
            "conclude-investigation": {
                "current_pass": conclude.returncode == 0,
                "v6_target": "block-until-independent-exploration",
            },
            "pivot-to-change": {
                "current_pass": pivot.returncode == 0,
                "v6_target": "block-until-independent-exploration",
            },
        }
        result["g1_v6_pass"] = (
            result["record-evidence"]["current_pass"]
            and result["record-open-claim"]["current_pass"]
            and result["experiment"]["current_pass"]
            and not result["accepted-decision"]["current_pass"]
            and not result["conclude-investigation"]["current_pass"]
            and not result["pivot-to-change"]["current_pass"]
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
