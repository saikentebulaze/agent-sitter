"""Backward-compatible Codex profile entrypoint.

V5 runtime-neutral code resolves providers through core.provider_registry.
Legacy callers keep importing this module and receive the exact v4.1 profile
shape, so existing Task and delegation behavior remains unchanged.
"""

from __future__ import annotations

from core.provider_registry import get_provider
from project_context import ProjectContext
from providers.codex.profiles import AgentProfile, AgentProfileError, MODEL_TIERS


def load_agent_profile(context: ProjectContext, role: str) -> AgentProfile:
    profile = get_provider("codex").load_role_profile(context, role)
    sandbox_mode = "read-only" if profile.write_isolation == "os-readonly" else "unknown"
    return AgentProfile(
        name=profile.runtime_role,
        model=profile.model,
        tier=profile.tier,
        reasoning_effort=profile.reasoning_effort,
        sandbox_mode=sandbox_mode,
        source=profile.source,
    )


__all__ = [
    "AgentProfile",
    "AgentProfileError",
    "MODEL_TIERS",
    "load_agent_profile",
]
