"""Backward-compatible entrypoint for provider-independent role policy.

The authoritative role definitions now live in core.role_spec. Existing V4
callers keep their public names while V5 code can use RoleSpec directly.
"""

from __future__ import annotations

from core.role_spec import (
    ROLE_SPECS,
    RoleSpec,
    RoleSpecError,
    project_change,
    role_spec_for,
)


DelegationPolicy = RoleSpec
DelegationPolicyError = RoleSpecError
POLICIES = ROLE_SPECS
policy_for_role = role_spec_for


__all__ = [
    "DelegationPolicy",
    "DelegationPolicyError",
    "POLICIES",
    "policy_for_role",
    "project_change",
]
