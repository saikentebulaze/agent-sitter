from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from core.managed_projection import MARKER, PACKAGE_NAME
from project_context import ProjectContext
from providers.codex.profiles import load_native_agent_profile


def entrypoint_text() -> str:
    return f"""<!-- {MARKER}; do not edit. -->
# Sitter Harness entrypoint

When the user asks to update this Harness, do not edit this generated file, `.codex/`, `.agents/skills/`, or `.harness/{PACKAGE_NAME}/`. Read `.harness/{PACKAGE_NAME}/source.yaml`; update only the independent Harness repository at `source_root`, then run its `install.py --update --project <this project root>`. If `source_root` is missing or unavailable, stop and ask the user for the new source path.

Read `.harness/{PACKAGE_NAME}/adapters/default/bootstrap/AGENTS.md.template` as the lightweight routing policy for repository work. It decides whether the request stays on the LOW Fast Path or enters formal governance. Do not load the full Governor unless that router or an active governed Task requires it.
"""


def toml_text(source: Path) -> str:
    return f"# {MARKER}; do not edit.\n" + source.read_text(encoding="utf-8")


def hooks_json_text() -> str:
    argv = [
        str(Path(sys.executable).resolve()),
        f".harness/{PACKAGE_NAME}/runtime/session_start_hook.py",
    ]
    command = (
        subprocess.list2cmdline(argv)
        if os.name == "nt"
        else shlex.join(argv)
    )
    payload = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 5,
                            "statusMessage": "Loading bounded Sitter task continuity",
                        }
                    ],
                }
            ]
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def agent_toml_text(context: ProjectContext, source: Path) -> str:
    """Render one frozen Codex role with the effective native model settings."""

    with source.open("rb") as stream:
        import tomllib

        data = tomllib.load(stream)
    role = str(data.get("name") or "")
    if not role:
        raise ValueError(f"Codex Agent template has no canonical name: {source}")
    profile = load_native_agent_profile(context, role)
    text = source.read_text(encoding="utf-8")
    text, model_count = re.subn(
        r'(?m)^model[ \t]*=[ \t]*"[^"]*"[ \t]*$',
        f'model = "{profile.model}"',
        text,
        count=1,
    )
    text, effort_count = re.subn(
        r'(?m)^model_reasoning_effort[ \t]*=[ \t]*"[^"]*"[ \t]*$',
        f'model_reasoning_effort = "{profile.reasoning_effort}"',
        text,
        count=1,
    )
    if model_count != 1 or effort_count != 1:
        raise ValueError(
            f"Codex Agent template must contain one model and effort field: {source}"
        )
    return f"# {MARKER}; do not edit.\n" + text


def _skill_frontmatter_value(source: Path, key: str) -> str:
    text = source.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"Skill must start with YAML frontmatter: {source}")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"Skill has no closing YAML frontmatter: {source}")
    frontmatter = text[4:end]
    match = re.search(rf"(?m)^{re.escape(key)}:[ \t]*(.+?)[ \t]*$", frontmatter)
    if not match:
        raise ValueError(f"Skill frontmatter has no {key}: {source}")
    return match.group(1).strip().strip('"').strip("'")


def skill_wrapper_text(source: Path) -> str:
    skill_name = source.parent.name
    description = _skill_frontmatter_value(source, "description")
    return f"""---
name: {skill_name}
description: {description}
---

# {MARKER}; do not edit.

This is a generated discovery bridge, not a second policy source. Once this Skill is explicitly selected by the router or user, read `.harness/{PACKAGE_NAME}/adapters/default/skills/{skill_name}/SKILL.md` and follow it. Do not select this Skill merely to perform unrelated LOW fast-path work.
"""


def skill_metadata_text(source: Path) -> str:
    return f"# {MARKER}; do not edit.\n" + source.read_text(encoding="utf-8")
