from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

from common import fail
from project_context import ProjectContext, resolve_project_context


def load_toml(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing configuration: {path}")
    with path.open("rb") as stream:
        return tomllib.load(stream)


def find_role(role: str, context: ProjectContext) -> tuple[Path, dict]:
    agent_dir = context.adapter_root / "codex" / "agents"
    direct = agent_dir / f"{role}.toml"
    if direct.is_file():
        return direct, load_toml(direct)
    for candidate in agent_dir.glob("*.toml"):
        config = load_toml(candidate)
        if config.get("name") == role:
            return candidate, config
    fail(f"unknown Claude role: {role}")


def build_command(role: str, prompt: str, context: ProjectContext) -> tuple[dict, list[str]]:
    _, role_config = find_role(role, context)
    if role_config.get("sandbox_mode") != "read-only":
        fail(f"Scout role must be read-only: {role}")

    model = role_config.get("model")
    effort = role_config.get("model_reasoning_effort")
    if not isinstance(model, str) or not model:
        fail(f"role {role} has no explicit model")
    if not isinstance(effort, str) or not effort:
        fail(f"role {role} has no explicit model_reasoning_effort")

    # A dry-run should remain usable in CI and static checks even when the
    # Codex CLI is not installed. Actual fallback execution checks PATH later.
    executable = shutil.which("codex") or "codex"

    canonical_name = str(role_config.get("name") or role)
    instructions = str(role_config.get("developer_instructions", "")).strip()
    full_prompt = (
        f"You are the read-only Sitter role: {canonical_name}.\n\n"
        f"Role instructions:\n{instructions}\n\n"
        f"Task:\n{prompt.strip()}\n\n"
        "Do not modify files. Return concise, evidence-linked findings only."
    )
    command = [
        executable,
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(context.project_root),
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--json",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        full_prompt,
    ]
    metadata = {
        "agent": canonical_name,
        "model": model,
        "model_reasoning_effort": effort,
        "execution": "external-codex-fallback",
    }
    return metadata, command


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or explicitly run the external Codex fallback command. "
            "Normal Harness work must use native subagents."
        )
    )
    parser.add_argument("--role", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the external fallback. Native subagent spawning remains the normal path.",
    )
    parser.add_argument(
        "--external-fallback-approved",
        action="store_true",
        help="Required with --execute to prevent accidental use as the normal router.",
    )
    args = parser.parse_args()

    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        fail(str(error))

    metadata, command = build_command(args.role, args.prompt, context)
    if not args.execute:
        print(json.dumps({**metadata, "command": command}))
        return
    if not args.external_fallback_approved:
        fail("--execute requires --external-fallback-approved")
    if shutil.which("codex") is None:
        fail("Codex CLI was not found on PATH")

    completed = subprocess.run(command, cwd=context.project_root)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
