from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from common import fail
from project_context import ProjectContext, resolve_project_context


EXPECTED = {
    "source_locator": ("gpt-5.6-luna", "low"),
    "memory_scout": ("gpt-5.6-luna", "low"),
    "context_scout": ("gpt-5.6-luna", "medium"),
    "test_scout": ("gpt-5.6-luna", "medium"),
    "framework_scout": ("gpt-5.6-terra", "medium"),
    "maintainer_reviewer": ("gpt-5.6-terra", "medium"),
    "deep_reviewer": ("gpt-5.6-sol", "high"),
}


def validate_agent_profiles(context: ProjectContext) -> None:
    agent_dir = context.adapter_root / "codex" / "agents"
    config_path = context.adapter_root / "codex" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    agents_config = config.get("agents")
    if not isinstance(agents_config, dict):
        fail("config.toml has no [agents] table")
    if not isinstance(agents_config.get("max_concurrent_threads_per_session"), int):
        fail("[agents].max_concurrent_threads_per_session must be an integer")
    if "profiles" in config:
        fail("project-level profiles are not allowed for native Sitter subagents")

    errors: list[str] = []
    seen_names: set[str] = set()
    discovered: set[str] = set()

    for agent_file in sorted(agent_dir.glob("*.toml")):
        agent = tomllib.loads(agent_file.read_text(encoding="utf-8"))
        name = agent.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{agent_file.name} has no canonical name")
            continue
        if name in seen_names:
            errors.append(f"duplicate canonical agent name: {name}")
        seen_names.add(name)
        discovered.add(name)

        if "profile" in agent:
            errors.append(
                f"{agent_file.name} still uses profile instead of native model fields"
            )
        if agent.get("sandbox_mode") != "read-only":
            errors.append(f"{agent_file.name} must be read-only")

        expected = EXPECTED.get(name)
        if expected is None:
            errors.append(f"{agent_file.name} has an unregistered Sitter role: {name}")
            continue
        expected_model, expected_effort = expected
        if agent.get("model") != expected_model:
            errors.append(f"{name} must use {expected_model}")
        if agent.get("model_reasoning_effort") != expected_effort:
            errors.append(f"{name} must use {expected_effort} reasoning")

    missing = set(EXPECTED) - discovered
    if missing:
        errors.append("missing agent roles: " + ", ".join(sorted(missing)))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("agent_profiles: valid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        validate_agent_profiles(context)
    except ValueError as error:
        fail(str(error))


if __name__ == "__main__":
    main()
