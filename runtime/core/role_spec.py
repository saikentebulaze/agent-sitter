"""Provider-independent Sitter delegation role specifications."""

from __future__ import annotations

from dataclasses import dataclass


class RoleSpecError(ValueError):
    pass


@dataclass(frozen=True)
class RoleSpec:
    role: str
    authorization_scope: str
    projection: str
    allowed_targets: frozenset[str]
    authority_files: tuple[str, ...]
    inline_change_fields: tuple[str, ...]
    max_context_supplements: int = 2


ROLE_SPECS = {
    "source_locator": RoleSpec(
        role="source_locator",
        authorization_scope="readonly-exploration",
        projection="locator-v1",
        allowed_targets=frozenset({"task", "investigation", "change"}),
        authority_files=("change.yaml",),
        inline_change_fields=("id", "title", "status", "execution_state", "change_budget"),
    ),
    "context_scout": RoleSpec(
        role="context_scout",
        authorization_scope="readonly-exploration",
        projection="context-scout-v1",
        allowed_targets=frozenset({"task", "investigation", "change"}),
        authority_files=("change.yaml", "proposal.md", "design.md"),
        inline_change_fields=(
            "id", "title", "status", "execution_state", "risk",
            "critical_surfaces", "change_budget", "relations",
        ),
    ),
    "test_scout": RoleSpec(
        role="test_scout",
        authorization_scope="readonly-exploration",
        projection="test-scout-v1",
        allowed_targets=frozenset({"investigation", "change"}),
        authority_files=(
            "change.yaml", "proposal.md", "design.md", "tasks.md", "verification.md",
        ),
        inline_change_fields=(
            "id", "title", "status", "risk", "critical_surfaces",
            "change_budget", "verification",
        ),
    ),
    "framework_scout": RoleSpec(
        role="framework_scout",
        authorization_scope="readonly-exploration",
        projection="framework-scout-v1",
        allowed_targets=frozenset({"investigation", "change"}),
        authority_files=("change.yaml", "proposal.md", "design.md", "tasks.md"),
        inline_change_fields=(
            "id", "title", "status", "execution_state", "risk",
            "critical_surfaces", "change_budget", "relations", "human_in_loop",
        ),
    ),
    "maintainer_reviewer": RoleSpec(
        role="maintainer_reviewer",
        authorization_scope="readonly-review",
        projection="maintainer-reviewer-v1",
        allowed_targets=frozenset({"change"}),
        authority_files=(
            "change.yaml", "proposal.md", "design.md", "tasks.md", "verification.md",
        ),
        inline_change_fields=(
            "id", "title", "status", "execution_state", "risk",
            "critical_surfaces", "change_budget", "approval", "human_in_loop",
        ),
    ),
    "deep_reviewer": RoleSpec(
        role="deep_reviewer",
        authorization_scope="readonly-review",
        projection="deep-reviewer-v1",
        allowed_targets=frozenset({"investigation", "change"}),
        authority_files=(
            "change.yaml", "proposal.md", "design.md", "tasks.md", "verification.md",
        ),
        inline_change_fields=(
            "id", "title", "status", "execution_state", "risk",
            "critical_surfaces", "change_budget", "relations",
            "approval", "human_in_loop", "verification",
        ),
    ),
}


def role_spec_for(role: str) -> RoleSpec:
    try:
        return ROLE_SPECS[role]
    except KeyError as error:
        raise RoleSpecError(f"unsupported delegation role: {role}") from error


def project_change(change: dict, role_spec: RoleSpec) -> dict:
    return {
        key: change.get(key)
        for key in role_spec.inline_change_fields
        if key in change
    }
