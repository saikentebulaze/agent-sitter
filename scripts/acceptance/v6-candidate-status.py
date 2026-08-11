from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def exists(*relative: str) -> bool:
    return all((ROOT / value).is_file() for value in relative)


def test_evidence(*names: str) -> list[str]:
    return [f"tests/{name}" for name in names]


def main() -> None:
    result = {
        "schema_version": 1,
        "candidate_source": "current checkout HEAD",
        "interpretation": (
            "PASS_L2 means deterministic behavior is implemented and covered by repository tests. "
            "It does not substitute for L3 real runtime or same-model/live behavior evidence."
        ),
        "C1-context-coverage": {
            "status": "L4_MODEL_RUN_REQUIRED",
            "protocol": "scripts/acceptance/v6-ab-benchmark.py",
            "fixture": "scripts/acceptance/context-coverage-fixture.py",
        },
        "C2-independent-exploration": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_memory_scout.py", "test_delegation_context.py"),
            "note": "engineering Scouts use inheritance=none and parent hypotheses/desired outcome are withheld",
        },
        "C3-cross-session-continuity": {
            "status": "PASS_L2_L3_PROTOCOL_READY",
            "evidence": test_evidence(
                "test_v6_continuity_memory.py",
                "test_v6_session_start.py",
                "test_v6_session_start_evidence.py",
            ),
            "runtime_protocol": "scripts/acceptance/v6-runtime-smoke.py",
        },
        "C4-memory-recall": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_continuity_memory.py", "test_v6_memory_scout.py"),
            "note": "deterministic top-N recall precedes optional cheap Memory Scout; archived Tasks are not scanned",
        },
        "C5-memory-suppression": {
            "status": "PASS_L2_LIVE_AB_PROTOCOL_READY",
            "evidence": test_evidence(
                "test_v6_continuity_memory.py",
                "test_v6_memory_scout.py",
                "test_adaptive_router.py",
                "test_v6_fast_path_ab_protocol.py",
            ),
            "live_protocol": "scripts/acceptance/v6-fast-path-ab.py",
        },
        "C6-memory-evolution": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_continuity_memory.py"),
            "states": ["fresh", "suspect", "unknown"],
        },
        "C7-open-thread-watchpoint": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_continuity_memory.py", "test_v6_durable_memory.py"),
        },
        "H1-human-override": {
            "status": "PASS_L2_MECHANICAL_LIVE_PROTOCOL_READY",
            "evidence": test_evidence(
                "test_v6_human_authority.py",
                "test_v6_durable_memory.py",
                "test_v6_human_authority_live_protocol.py",
            ),
            "live_protocol": "scripts/acceptance/v6-human-authority-live.py",
            "note": "the live prompt hides which option is authoritative and verifies downstream implementation/design/review/memory against recorded user state",
        },
        "H2-material-decision-gate": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_human_authority.py", "test_governance_validation.py"),
        },
        "H3-no-hitl-overhead": {
            "status": "PASS_L2_LIVE_AB_PROTOCOL_READY",
            "evidence": test_evidence(
                "test_adaptive_router.py",
                "test_v6_behavior_benchmark.py",
                "test_v6_fast_path_ab_protocol.py",
            ),
            "live_protocol": "scripts/acceptance/v6-fast-path-ab.py",
        },
        "H4-human-curated-memory": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_continuity_memory.py", "test_v6_durable_memory.py"),
        },
        "H5-memory-conflict": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_continuity_memory.py", "test_v6_durable_memory.py"),
            "note": "conflicts are historical leads; promotion requires explicit supersession instead of auto merge",
        },
        "G1-exploration-gate": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_context_authority.py", "test_adaptive_work.py"),
        },
        "P1-long-term-cost": {
            "status": "PASS_L2",
            "evidence": test_evidence("test_v6_continuity_memory.py", "test_v6_session_start.py"),
            "note": "SessionStart reads bounded Active Task Index only; archive count does not change payload",
        },
        "P2-fast-path-cost": {
            "status": "PASS_L2_LIVE_AB_PROTOCOL_READY",
            "evidence": test_evidence(
                "test_adaptive_router.py",
                "test_v6_memory_scout.py",
                "test_v6_fast_path_ab_protocol.py",
            ),
            "live_protocol": "scripts/acceptance/v6-fast-path-ab.py",
        },
        "R1-codex-runtime-smoke": {
            "status": "NOT_RUN_L3_PROTOCOL_READY",
            "protocol": "scripts/acceptance/v6-runtime-smoke.py",
        },
        "R2-claude-runtime-smoke": {
            "status": "NOT_RUN_L3_PROTOCOL_READY",
            "protocol": "scripts/acceptance/v6-runtime-smoke.py",
        },
        "L4-context-ab": {
            "status": "NOT_RUN_MODEL_PROTOCOL_READY",
            "protocol": "scripts/acceptance/v6-ab-benchmark.py",
            "controls": [
                "same model/config",
                "same code snapshot",
                "same prompt bytes",
                "attested engineering exploration evidence",
            ],
        },
        "L4-fast-path-ab": {
            "status": "NOT_RUN_MODEL_PROTOCOL_READY",
            "protocol": "scripts/acceptance/v6-fast-path-ab.py",
            "controls": [
                "same model/config",
                "same heavy-history snapshot",
                "same LOW prompt bytes",
                "observable governed-artifact overhead",
            ],
        },
        "assets_present": exists(
            "runtime/active_task_index.py",
            "runtime/session_start_hook.py",
            "runtime/memory_context.py",
            "runtime/memory_scout_once.py",
            "runtime/durable_memory.py",
            "scripts/acceptance/v6-runtime-smoke.py",
            "scripts/acceptance/v6-ab-benchmark.py",
            "scripts/acceptance/v6-human-authority-live.py",
            "scripts/acceptance/v6-fast-path-ab.py",
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
