from __future__ import annotations

import json
import re
from pathlib import Path

from core.managed_projection import MARKER, PACKAGE_NAME
from project_context import ProjectContext
from providers.claude.profiles import load_native_agent_profile


_AGENT_HOOKS = """hooks:
  PreToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python
          args:
            - "${CLAUDE_PROJECT_DIR}/.claude/hooks/governance-runtime-hook.py"
  PostToolUse:
    - matcher: "*"
      hooks:
        - type: command
          command: python
          args:
            - "${CLAUDE_PROJECT_DIR}/.claude/hooks/governance-runtime-hook.py"
  PreCompact:
    - matcher: "manual|auto"
      hooks:
        - type: command
          command: python
          args:
            - "${CLAUDE_PROJECT_DIR}/.claude/hooks/governance-runtime-hook.py"
  PostCompact:
    - matcher: "manual|auto"
      hooks:
        - type: command
          command: python
          args:
            - "${CLAUDE_PROJECT_DIR}/.claude/hooks/governance-runtime-hook.py"
  WorktreeCreate:
    - hooks:
        - type: command
          command: python
          args:
            - "${CLAUDE_PROJECT_DIR}/.claude/hooks/governance-runtime-hook.py"
"""


def entrypoint_text() -> str:
    return f"""<!-- {MARKER}; do not edit. -->
# Sitter Harness Claude entrypoint

When the user asks to update this Harness, do not edit this generated file, `.claude/`, or `.harness/{PACKAGE_NAME}/`. Read `.harness/{PACKAGE_NAME}/source.yaml`; update only the independent Harness repository at `source_root`, then run its installer/update command against this project.

Read `.harness/{PACKAGE_NAME}/adapters/default/bootstrap/AGENTS.md.template` as the lightweight routing policy for repository work. It decides whether the request stays on the LOW Fast Path or enters formal governance. Do not load the full Governor merely because the user mentioned code, tests, or a calculation case.
"""


def _inject_agent_hooks(text: str) -> str:
    if not text.startswith("---\n"):
        raise ValueError("Claude Agent template must start with YAML frontmatter")
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise ValueError("Claude Agent template has no closing frontmatter delimiter")
    prefix = text[:closing]
    if "\nmcpServers:" not in prefix:
        prefix += "\nmcpServers: []"
    return prefix + "\n" + _AGENT_HOOKS.rstrip() + text[closing:]


def agent_text(context: ProjectContext, source: Path) -> str:
    runtime_name = source.stem
    role = runtime_name.replace("-", "_")
    profile = load_native_agent_profile(context, role)
    rendered = source.read_text(encoding="utf-8").replace(
        "{{MODEL_SELECTOR}}", profile.model
    ).replace(
        "{{REASONING_EFFORT}}", profile.reasoning_effort
    )
    injected = _inject_agent_hooks(rendered)
    closing = injected.find("\n---\n", 4)
    if closing < 0:
        raise ValueError("Claude Agent template has no closing frontmatter delimiter")
    end = closing + len("\n---\n")
    return injected[:end] + f"\n<!-- {MARKER}; do not edit. -->\n" + injected[end:].lstrip("\n")


def hook_text(source: Path) -> str:
    return f"# {MARKER}; do not edit.\n" + source.read_text(encoding="utf-8")


def governed_settings_text(source: Path) -> str:
    data = json.loads(source.read_text(encoding="utf-8"))
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def settings_text(source: Path) -> str:
    return governed_settings_text(source)


def _skill_description(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"Skill must start with YAML frontmatter: {source}")
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise ValueError(f"Skill has no closing YAML frontmatter: {source}")
    match = re.search(r"(?m)^description:[ \t]*(.+?)[ \t]*$", text[4:closing])
    if not match:
        raise ValueError(f"Skill frontmatter has no description: {source}")
    return match.group(1).strip().strip('"').strip("'")


def skill_wrapper_text(source: Path) -> str:
    skill_name = source.parent.name
    description = _skill_description(source)
    return f"""---
name: {skill_name}
description: {description}
---

<!-- {MARKER}; do not edit. -->

This is a generated discovery bridge. Once this Skill is selected by the router or user, read `.harness/{PACKAGE_NAME}/adapters/default/skills/{skill_name}/SKILL.md` and follow it. Do not select it merely to perform unrelated LOW fast-path work.
"""
