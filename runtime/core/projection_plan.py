"""Provider-independent installation projection model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Projection:
    """One provider-owned text file projected into a target project."""

    owner: str
    relative_path: Path
    content: str

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("projection owner is required")
        path = Path(self.relative_path)
        # On Windows, a root-relative path such as ``\file`` has an anchor but
        # no drive and Path.is_absolute() may be false. Any anchor would still
        # escape the target project when joined, so reject both forms.
        if path.is_absolute() or path.anchor or not path.parts or ".." in path.parts:
            raise ValueError(f"projection path must stay relative: {path}")
        object.__setattr__(self, "relative_path", path)

    def target(self, project_root: Path) -> Path:
        return project_root / self.relative_path


@dataclass(frozen=True)
class ProjectionPlan:
    """Complete desired local projection set for one provider."""

    provider: str
    projections: tuple[Projection, ...]

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("projection plan provider is required")
        seen: set[Path] = set()
        for projection in self.projections:
            if projection.owner != self.provider:
                raise ValueError(
                    f"projection owner {projection.owner} does not match plan {self.provider}"
                )
            if projection.relative_path in seen:
                raise ValueError(
                    f"duplicate projection in {self.provider}: {projection.relative_path}"
                )
            seen.add(projection.relative_path)

    def targets(self, project_root: Path) -> tuple[Path, ...]:
        return tuple(item.target(project_root) for item in self.projections)


def _casefolded_parts(path: Path) -> tuple[str, ...]:
    """Return a platform-independent comparison key for projected paths."""

    return tuple(part.casefold() for part in path.parts)


def _is_ancestor(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) < len(right) and right[: len(left)] == left


def merge_projection_plans(
    plans: Iterable[ProjectionPlan],
) -> tuple[Projection, ...]:
    """Merge plans and reject exact, case-folded, and ancestor conflicts.

    A conflict must be rejected before installation writes anything. Exact
    path comparison alone is insufficient because some filesystems treat
    case-only variants as the same path, and one Provider may otherwise claim
    a file where another Provider needs a directory tree.
    """

    merged: list[Projection] = []
    claimed: list[tuple[tuple[str, ...], Path, str]] = []
    for plan in plans:
        for projection in plan.projections:
            path = projection.relative_path
            folded = _casefolded_parts(path)
            duplicate_same_owner = False
            for previous_folded, previous_path, previous_owner in claimed:
                same = folded == previous_folded
                ancestor = _is_ancestor(folded, previous_folded) or _is_ancestor(
                    previous_folded,
                    folded,
                )
                if same and previous_owner == projection.owner:
                    duplicate_same_owner = True
                    break
                if same or ancestor:
                    raise ValueError(
                        "projection ownership conflict: "
                        f"{path} claimed by {projection.owner} conflicts with "
                        f"{previous_path} claimed by {previous_owner}"
                    )
            if duplicate_same_owner:
                continue
            claimed.append((folded, path, projection.owner))
            merged.append(projection)
    return tuple(merged)
