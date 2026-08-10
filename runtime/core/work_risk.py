from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping


class RiskLevel(IntEnum):
    """Ordering for current execution risk, not final production assurance."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


RISK_LEVEL_NAMES = {
    RiskLevel.LOW: "low",
    RiskLevel.MEDIUM: "medium",
    RiskLevel.HIGH: "high",
    RiskLevel.CRITICAL: "critical",
}
RISK_LEVEL_VALUES = {name: level for level, name in RISK_LEVEL_NAMES.items()}


@dataclass(frozen=True)
class RiskVector:
    semantic: RiskLevel
    repository_change: RiskLevel

    def maximum(self) -> RiskLevel:
        return max(self.semantic, self.repository_change)

    def dominates(self, other: "RiskVector") -> bool:
        return (
            self.semantic >= other.semantic
            and self.repository_change >= other.repository_change
        )

    def is_lower_than(self, other: "RiskVector") -> bool:
        return (
            self.semantic < other.semantic
            or self.repository_change < other.repository_change
        )


@dataclass(frozen=True)
class RiskTransition:
    previous: RiskVector
    current: RiskVector
    reason: str
    evidence_ref: str | None = None


def parse_level(value: object, *, default: RiskLevel | None = None) -> RiskLevel:
    if value is None and default is not None:
        return default
    name = str(value or "").strip().lower()
    try:
        return RISK_LEVEL_VALUES[name]
    except KeyError as error:
        allowed = ", ".join(RISK_LEVEL_VALUES)
        raise ValueError(f"invalid risk level {value!r}; expected one of: {allowed}") from error


def level_name(level: RiskLevel) -> str:
    try:
        return RISK_LEVEL_NAMES[RiskLevel(level)]
    except (KeyError, ValueError) as error:
        raise ValueError(f"invalid risk level: {level}") from error


def vector_from_mapping(
    value: object,
    *,
    default: RiskVector | None = None,
) -> RiskVector:
    if value is None and default is not None:
        return default
    if not isinstance(value, Mapping):
        raise ValueError("risk vector must be a mapping")
    return RiskVector(
        semantic=parse_level(value.get("semantic")),
        repository_change=parse_level(value.get("repository_change")),
    )


def vector_mapping(value: RiskVector) -> dict[str, str]:
    return {
        "semantic": level_name(value.semantic),
        "repository_change": level_name(value.repository_change),
    }


def max_level(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    return max(left, right)


def max_vector(left: RiskVector, right: RiskVector) -> RiskVector:
    return RiskVector(
        semantic=max_level(left.semantic, right.semantic),
        repository_change=max_level(left.repository_change, right.repository_change),
    )


def raise_to_floor(current: RiskVector, floor: RiskVector) -> RiskVector:
    """Apply a one-way risk floor from discovered engineering facts."""

    return max_vector(current, floor)


def execution_profile(value: RiskVector) -> str:
    """Return the governance intensity implied by current work risk.

    The profile is derived rather than stored so profile and risk cannot drift
    apart. LOW is the fast-path shape, MEDIUM uses the existing work graph
    lightly, and HIGH/CRITICAL use full governance.
    """

    maximum = value.maximum()
    if maximum == RiskLevel.LOW:
        return "fast"
    if maximum == RiskLevel.MEDIUM:
        return "lite"
    return "full"


def can_reduce_current_risk(
    *,
    has_open_investigation: bool,
    has_active_escalation: bool,
    has_unresolved_decision: bool,
    remaining_work_bounded: bool,
) -> bool:
    """Guard dynamic de-escalation.

    Current execution risk may decrease only after the unknown engineering
    surface has actually been reduced. This intentionally does not represent
    production assurance; Change assurance remains independent.
    """

    return (
        not has_open_investigation
        and not has_active_escalation
        and not has_unresolved_decision
        and remaining_work_bounded
    )
