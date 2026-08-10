from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.work_risk import (  # noqa: E402
    RiskLevel,
    RiskVector,
    can_reduce_current_risk,
    execution_profile,
    max_vector,
    raise_to_floor,
    vector_from_mapping,
    vector_mapping,
)


class DynamicWorkRiskTests(unittest.TestCase):
    def test_raise_to_floor_only_increases_risk(self) -> None:
        current = RiskVector(RiskLevel.LOW, RiskLevel.MEDIUM)
        floor = RiskVector(RiskLevel.HIGH, RiskLevel.LOW)
        result = raise_to_floor(current, floor)
        self.assertEqual(result.semantic, RiskLevel.HIGH)
        self.assertEqual(result.repository_change, RiskLevel.MEDIUM)
        self.assertEqual(max_vector(current, floor), result)

    def test_current_risk_reduction_requires_unknowns_removed(self) -> None:
        self.assertFalse(
            can_reduce_current_risk(
                has_open_investigation=True,
                has_active_escalation=False,
                has_unresolved_decision=False,
                remaining_work_bounded=True,
            )
        )
        self.assertFalse(
            can_reduce_current_risk(
                has_open_investigation=False,
                has_active_escalation=False,
                has_unresolved_decision=False,
                remaining_work_bounded=False,
            )
        )
        self.assertTrue(
            can_reduce_current_risk(
                has_open_investigation=False,
                has_active_escalation=False,
                has_unresolved_decision=False,
                remaining_work_bounded=True,
            )
        )

    def test_execution_profile_is_derived_from_current_risk(self) -> None:
        self.assertEqual(
            execution_profile(RiskVector(RiskLevel.LOW, RiskLevel.LOW)),
            "fast",
        )
        self.assertEqual(
            execution_profile(RiskVector(RiskLevel.MEDIUM, RiskLevel.LOW)),
            "lite",
        )
        self.assertEqual(
            execution_profile(RiskVector(RiskLevel.LOW, RiskLevel.HIGH)),
            "full",
        )
        self.assertEqual(
            execution_profile(RiskVector(RiskLevel.CRITICAL, RiskLevel.LOW)),
            "full",
        )

    def test_vector_mapping_round_trips_without_assurance_state(self) -> None:
        current = RiskVector(RiskLevel.HIGH, RiskLevel.MEDIUM)
        encoded = vector_mapping(current)
        self.assertEqual(
            encoded,
            {"semantic": "high", "repository_change": "medium"},
        )
        self.assertEqual(vector_from_mapping(encoded), current)
        self.assertFalse(hasattr(current, "assurance"))


if __name__ == "__main__":
    unittest.main()
