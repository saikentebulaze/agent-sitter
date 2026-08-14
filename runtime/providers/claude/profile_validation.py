from __future__ import annotations

import re

from project_context import ProjectContext
from providers.claude.profiles import load_native_agent_profile


EXPECTED_ROLES = (
    "source_locator",
    "memory_scout",
    "context_scout",
    "framework_scout",
    "test_scout",
    "maintainer_reviewer",
    "deep_reviewer",
)

_REQUIRED_DENIED_TOOLS = {
    "Write",
    "Edit",
    "NotebookEdit",
    "Bash",
    "PowerShell",
    "Agent",
    "Skill",
    "WebFetch",
    "WebSearch",
}


def validate_agent_profiles(context: ProjectContext) -> None:
    for role in EXPECTED_ROLES:
        profile = load_native_agent_profile(context, role)
        text = profile.source.read_text(encoding="utf-8")
        required = (
            "tools: Read, Grep, Glob",
            "permissionMode: dontAsk",
            "background: false",
            "model: {{MODEL_SELECTOR}}",
            "effort: {{REASONING_EFFORT}}",
        )
        missing = [value for value in required if value not in text]
        if missing:
            raise ValueError(f"{role} Claude profile is missing: {missing[0]}")
        if re.search(r"(?m)^memory:\s*", text):
            raise ValueError(f"{role} Claude profile must not enable persistent memory")
        if re.search(r"(?m)^isolation:\s*worktree\s*$", text):
            raise ValueError(f"{role} Claude profile must not use worktree isolation")
        match = re.search(r"(?m)^disallowedTools:\s*(.+)$", text)
        if match is None:
            raise ValueError(f"{role} Claude profile has no disallowedTools")
        denied = {item.strip() for item in match.group(1).split(",")}
        if not _REQUIRED_DENIED_TOOLS.issubset(denied):
            raise ValueError(f"{role} Claude profile does not deny all unsafe tools")
