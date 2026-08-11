from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = HARNESS_ROOT / "runtime"
ADAPTER = HARNESS_ROOT / "adapters" / "default"


def run_script(name: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(HARNESS_ROOT / "scripts" / "acceptance" / name)],
        cwd=HARNESS_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"{name} failed:\n{result.stderr}")
    return json.loads(result.stdout)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    lock = project / ".harness" / "sitter" / "manifest-lock.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text("package: sitter\nformat_version: 1\n", encoding="utf-8")
    return project


def task_status_probe() -> dict:
    with tempfile.TemporaryDirectory(prefix="sitter-v6-status-") as directory:
        project = create_project(Path(directory))
        created = subprocess.run(
            [
                sys.executable,
                str(RUNTIME / "create_task.py"),
                "status-probe",
                "--title",
                "Status probe",
                "--entry",
                "investigation",
                "--signature",
                "status-probe",
                "--project",
                str(project),
            ],
            cwd=HARNESS_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if created.returncode:
            raise RuntimeError(created.stderr)
        status = project / ".agent-work" / "status-probe" / "status.md"
        before = sha(status)
        result = subprocess.run(
            [
                sys.executable,
                str(RUNTIME / "work.py"),
                "--project",
                str(project),
                "task-status",
                "status-probe",
            ],
            cwd=HARNESS_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        after = sha(status)
        return {
            "current_read_only": before == after,
            "status_artifact_changed": before != after,
            "v6_target": "task-status performs no mutation",
        }


def h4_probe() -> dict:
    source = (RUNTIME / "learning.py").read_text(encoding="utf-8")
    applies_one_decision_to_all = (
        "for candidate_id in candidates:" in source
        and 'review.update({"decision": decision' in source
    )
    return {
        "per_candidate_curation_available": not applies_one_decision_to_all,
        "current_bulk_attention_semantics": applies_one_decision_to_all,
        "v6_target": "K01/O01/W01 may be approved or dismissed independently",
    }


def static_capabilities() -> dict:
    delegation = (RUNTIME / "delegation_context.py").read_text(encoding="utf-8")
    router = (ADAPTER / "bootstrap" / "AGENTS.md.template").read_text(encoding="utf-8")
    schema = json.loads(
        (ADAPTER / "knowledge" / "schemas" / "knowledge-index.schema.json").read_text(
            encoding="utf-8"
        )
    )
    schema_text = json.dumps(schema)
    entry_types = set(schema["$defs"]["entry"]["properties"]["type"]["enum"])
    return {
        "C2-independent-exploration": {
            "v6_pass": (
                '"inheritance": "none"' in delegation
                and '"parent_hypotheses": "withheld"' in delegation
                and '"desired_outcome": "withheld"' in delegation
            ),
        },
        "H3-no-hitl-overhead": {
            "v6_pass": (
                "LOW Fast Path" in router
                and "Do not create `.agent-work`" in router
                and "long plan, or subagent" in router
            ),
        },
        "P2-fast-path-cost": {
            "v6_pass": (
                "Do not create `.agent-work`" in router
                and "Learning record" in router
            ),
        },
        "C6-memory-evolution": {
            "implemented": (
                "source_commit" in schema_text
                and "validity_surface" in schema_text
                and "freshness" in schema_text
            ),
        },
        "C7-open-thread": {
            "implemented": "open-thread" in entry_types and "watchpoint" in entry_types,
        },
        "H5-memory-conflict": {
            "implemented": "supersedes" in schema_text and "conflict" in schema_text,
        },
    }


def main() -> None:
    result = {
        "baseline_source": "main@f179c2ece4f5e428bfcd33d375c67f87a289e6cb",
        "observation": "frozen historical baseline; current checkout capability is reported separately",
        "C1-context-coverage": {
            "status": "MODEL_RUN_REQUIRED",
            "fixture": "scripts/acceptance/context-coverage-fixture.py",
        },
        "C2-independent-exploration": {"v6_pass": True},
        "H3-no-hitl-overhead": {"v6_pass": True},
        "P2-fast-path-cost": {"v6_pass": True},
        "C6-memory-evolution": {"implemented": False},
        "C7-open-thread": {"implemented": False},
        "H5-memory-conflict": {"implemented": False},
        "C3-cross-session-continuity": {
            "status": "NOT_IMPLEMENTED",
            "reason": "no bounded Active Task Index / resume projection exists",
        },
        "C4-memory-recall": {
            "status": "NOT_IMPLEMENTED",
            "reason": "no Memory Scout or durable memory retrieval path exists",
        },
        "C5-memory-suppression": {
            "v6_pass": True,
            "note": "LOW router currently avoids governed Learning/Memory work",
        },
        "H1-human-override": {
            "v6_target": "downstream drift to A is blocked after user selected B",
            "current_validator_allows_drift": True,
            "v6_pass": False,
        },
        "H2-material-decision-gate": {
            "v6_target": "unresolved material decision blocks advanced HIGH work",
            "current_validator_blocks": True,
            "v6_pass": True,
        },
        "H4-human-curated-memory": {
            "per_candidate_curation_available": False,
            "current_bulk_attention_semantics": True,
            "v6_target": "K01/O01/W01 may be approved or dismissed independently",
        },
        "G1-exploration-gate": {
            "record-evidence": {"current_pass": True, "v6_target": "pass"},
            "record-open-claim": {"current_pass": True, "v6_target": "pass"},
            "experiment": {"current_pass": True, "v6_target": "pass"},
            "accepted-decision": {
                "current_pass": True,
                "v6_target": "block-until-independent-exploration",
            },
            "conclude-investigation": {
                "current_pass": True,
                "v6_target": "block-until-independent-exploration",
            },
            "pivot-to-change": {
                "current_pass": True,
                "v6_target": "block-until-independent-exploration",
            },
            "g1_v6_pass": False,
        },
        "task-status-dashboard": {
            "current_read_only": False,
            "status_artifact_changed": True,
            "v6_target": "task-status performs no mutation",
        },
        "P1-long-term-cost": {
            "status": "N/A_UNTIL_CONTINUITY_EXISTS",
            "reason": "current SessionStart does not load an Active Task Index",
        },
        "R1-codex-runtime-smoke": {"status": "NOT_RUN_L3"},
        "R2-claude-runtime-smoke": {"status": "NOT_RUN_L3"},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
