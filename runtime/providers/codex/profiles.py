"""Codex-native role profile loading.

The source TOML files remain the frozen V4.1/V5-A role and prompt baseline.
V5-B overlays only the native model selector and reasoning effort from the
Provider-neutral model configuration before projection or request freezing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from model_profiles import ModelProfileError, resolve_model_selection
from project_context import ProjectContext


GRADE_TO_LEGACY_TIER = {
    "low": "luna",
    "medium": "terra",
    "high": "sol",
}
LEGACY_TIER_TO_GRADE = {value: key for key, value in GRADE_TO_LEGACY_TIER.items()}

# Preserved for compatibility with existing callers and tests. Runtime code
# that needs project-local custom selectors should use effective_model_tiers().
MODEL_TIERS = {
    "gpt-5.6-luna": "luna",
    "gpt-5.6-terra": "terra",
    "gpt-5.6-sol": "sol",
}


class AgentProfileError(ValueError):
    pass


@dataclass(frozen=True)
class AgentProfile:
    name: str
    model: str
    tier: str
    reasoning_effort: str
    sandbox_mode: str
    source: Path
    model_grade: str = ""
    model_config_sha256: str = ""


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        raise AgentProfileError(f"missing agent profile: {path}")
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data, dict):
        raise AgentProfileError(f"agent profile must be a mapping: {path}")
    return data


def effective_model_tiers(context: ProjectContext) -> dict[str, str]:
    result = dict(MODEL_TIERS)
    for role in (
        "source_locator",
        "memory_scout",
        "context_scout",
        "test_scout",
        "framework_scout",
        "maintainer_reviewer",
        "deep_reviewer",
    ):
        try:
            selection = resolve_model_selection(context, "codex", role)
        except ModelProfileError as error:
            raise AgentProfileError(str(error)) from error
        result[selection.model_selector] = GRADE_TO_LEGACY_TIER[
            selection.model_grade
        ]
    return result


def model_tier_for_selector(context: ProjectContext, model: str) -> str | None:
    return effective_model_tiers(context).get(model)


def load_native_agent_profile(context: ProjectContext, role: str) -> AgentProfile:
    agent_dir = context.adapter_root / "codex" / "agents"
    direct = agent_dir / f"{role}.toml"
    candidates = [direct] if direct.is_file() else sorted(agent_dir.glob("*.toml"))
    for path in candidates:
        data = _load_toml(path)
        name = str(data.get("name") or "")
        if name != role:
            continue
        sandbox = str(data.get("sandbox_mode") or "")
        if sandbox != "read-only":
            raise AgentProfileError(
                f"{role} must be read-only for delegation protocol v1"
            )
        try:
            selection = resolve_model_selection(context, "codex", role)
        except ModelProfileError as error:
            raise AgentProfileError(str(error)) from error
        tier = GRADE_TO_LEGACY_TIER[selection.model_grade]
        return AgentProfile(
            name=name,
            model=selection.model_selector,
            tier=tier,
            reasoning_effort=selection.reasoning_effort,
            sandbox_mode=sandbox,
            source=path,
            model_grade=selection.model_grade,
            model_config_sha256=selection.config_sha256,
        )
    raise AgentProfileError(f"unknown Codex role: {role}")


# Provider-local compatibility for callers that import this module directly.
load_agent_profile = load_native_agent_profile
