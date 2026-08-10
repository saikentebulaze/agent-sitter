from __future__ import annotations

import argparse
import json
from pathlib import Path


FILES = {
    "src/input/request.py": """\
def build_request(payload):
    return {\"mode\": payload.get(\"mode\", \"incremental\"), \"value\": payload[\"value\"]}
""",
    "src/planner/dispatch.py": """\
def plan(request):
    # Root-cause surface: the planner incorrectly disables committed-state reuse
    # for incremental work when a value is negative.
    preserve_committed_state = request[\"mode\"] == \"incremental\" and request[\"value\"] >= 0
    return {\"preserve_committed_state\": preserve_committed_state}
""",
    "src/state/session.py": """\
class SessionState:
    def __init__(self):
        self.committed = 10

    def value_for(self, plan):
        return self.committed if plan[\"preserve_committed_state\"] else 0
""",
    "src/solver/execute.py": """\
def solve(state, plan, delta):
    # Surface symptom: the solver only consumes the state selected upstream.
    return state.value_for(plan) + delta
""",
    "src/result/render.py": """\
def render(value):
    return {\"result\": value}
""",
    "tests/test_pipeline.py": """\
def expected_incremental_negative_case():
    # Incremental work must start from committed state even for a negative delta.
    return 8
""",
    "docs/legacy-solver.md": """\
Legacy note: an obsolete solver once reset state before every solve.
This document is intentionally a decoy and does not describe current ownership.
""",
    "src/legacy/old_solver.py": """\
def solve(delta):
    # Obsolete implementation retained only as a decoy.
    return delta
""",
}

CLASSIFICATION = {
    "required": [
        "src/input/request.py",
        "src/planner/dispatch.py",
        "src/state/session.py",
        "src/solver/execute.py",
        "tests/test_pipeline.py",
    ],
    "useful": ["src/result/render.py"],
    "decoy": ["docs/legacy-solver.md", "src/legacy/old_solver.py"],
}

PROMPT = """\
The incremental negative-value case returns 2 but the expected result is 8.
Investigate the root cause before proposing a production change. The visible
symptom is in the solver, but do not assume the solver owns the defect.
"""


def manifest() -> dict:
    return {
        "schema_version": 1,
        "scenario": "C1-context-coverage",
        "prompt": PROMPT,
        "classification": CLASSIFICATION,
        "expected_root_cause": [
            "src/planner/dispatch.py",
            "src/state/session.py",
        ],
        "scoring": {
            "required_context_recall_target": 1.0,
            "context_pollution_target_max": 0.25,
            "premature_convergence_allowed": False,
        },
    }


def create_fixture(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for relative, content in FILES.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    output = destination / "benchmark.json"
    output.write_text(
        json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def score_result(payload: dict) -> dict:
    selected = {
        str(value).replace("\\", "/")
        for value in payload.get("selected_files") or []
        if isinstance(value, str)
    }
    required = set(CLASSIFICATION["required"])
    decoy = set(CLASSIFICATION["decoy"])
    found_required = sorted(required & selected)
    found_decoy = sorted(decoy & selected)
    recall = len(found_required) / len(required)
    pollution = len(found_decoy) / max(1, len(selected))
    premature = bool(payload.get("conclusion_before_independent_exploration", False))
    independent = bool(payload.get("independent_exploration_completed", False))
    return {
        "required_context_recall": recall,
        "context_pollution": pollution,
        "required_found": found_required,
        "required_missing": sorted(required - selected),
        "decoy_selected": found_decoy,
        "premature_convergence": premature,
        "independent_exploration_completed": independent,
        "meets_v6_target": (
            recall == 1.0
            and pollution <= 0.25
            and not premature
            and independent
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V6 C1 context coverage fixture")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("destination", type=Path)

    score = subparsers.add_parser("score")
    score.add_argument("result", type=Path)

    args = parser.parse_args()
    if args.command == "create":
        print(create_fixture(args.destination))
        return

    payload = json.loads(args.result.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("result must be a JSON object")
    print(json.dumps(score_result(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
