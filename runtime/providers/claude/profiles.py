"""Claude Code native role profile loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from model_profiles import ModelProfileError, resolve_model_selection
from project_context import ProjectContext


class ClaudeProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ClaudeAgentProfile:
    name: str
    runtime_name: str
    model: str
    model_grade: str
    reasoning_effort: str
    source: Path
    model_config_sha256: str
    model_resolution_mode: str = "native"
    expected_resolved_model: str = ""
    proxy_provider: str = ""


def runtime_role_name(role: str) -> str:
    return role.replace("_", "-")


def load_native_agent_profile(
    context: ProjectContext,
    role: str,
) -> ClaudeAgentProfile:
    runtime_name = runtime_role_name(role)
    source = context.adapter_root / "claude" / "agents" / f"{runtime_name}.md"
    if not source.is_file():
        raise ClaudeProfileError(f"unknown Claude role: {role}")
    try:
        selection = resolve_model_selection(context, "claude", role)
    except ModelProfileError as error:
        raise ClaudeProfileError(str(error)) from error
    return ClaudeAgentProfile(
        name=role,
        runtime_name=runtime_name,
        model=selection.model_selector,
        model_grade=selection.model_grade,
        reasoning_effort=selection.reasoning_effort,
        source=source,
        model_config_sha256=selection.config_sha256,
        model_resolution_mode=selection.resolution_mode,
        expected_resolved_model=selection.expected_resolved_model,
        proxy_provider=selection.proxy_provider,
    )
