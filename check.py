from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "runtime"))

from artifact_consistency import file_sha256  # noqa: E402
from core.provider_registry import get_provider  # noqa: E402
from install import (  # noqa: E402
    PACKAGE_NAME,
    desired_projections,
    installed_provider_ids,
    provider_context,
)
from model_profiles import load_effective_model_profiles  # noqa: E402


def check(project: Path) -> None:
    project = project.resolve()
    mirror = project / ".harness" / PACKAGE_NAME
    lock_path = mirror / "manifest-lock.yaml"
    if not lock_path.is_file():
        raise ValueError(f"Harness is not installed: {lock_path}")
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f"invalid installed Harness manifest: {lock_path}") from error
    if not isinstance(lock, dict) or lock.get("package") != PACKAGE_NAME:
        raise ValueError(f"invalid installed Harness manifest: {lock_path}")

    provider_ids = installed_provider_ids(project)
    if provider_ids is None:
        raise ValueError("installed Harness manifest has no enabled providers")

    context = provider_context(project)
    for provider_id in provider_ids:
        get_provider(provider_id).validate_static_configuration(context)

    expected = desired_projections(project, provider_ids)
    expected_paths = {item.relative_path.as_posix() for item in expected}
    recorded = lock.get("projections")
    owners = lock.get("projection_owners")
    if not isinstance(recorded, dict) or not isinstance(owners, dict):
        raise ValueError("installed Harness manifest has no projection hashes or owners")
    if set(recorded) != expected_paths or set(owners) != expected_paths:
        raise ValueError(
            "installed projection set differs from the current enabled Provider plans"
        )
    for projection in expected:
        relative = projection.relative_path.as_posix()
        target = projection.target(project)
        if owners.get(relative) != projection.owner:
            raise ValueError(
                f"projection owner mismatch for {relative}: "
                f"{owners.get(relative)} != {projection.owner}"
            )
        if not target.is_file():
            raise ValueError(f"installed projection is missing: {target}")
        actual = file_sha256(target)
        if recorded.get(relative) != actual:
            raise ValueError(f"installed projection was modified: {target}")
        if target.read_text(encoding="utf-8") != projection.content:
            raise ValueError(
                f"installed projection is stale for the current Provider configuration: {target}"
            )

    _, model_config_sha256 = load_effective_model_profiles(context)
    recorded_model_hash = str(lock.get("model_config_sha256") or "")
    if recorded_model_hash and recorded_model_hash != model_config_sha256:
        raise ValueError(
            "installed model configuration is stale; rerun install.py"
        )

    if "claude" in provider_ids:
        governed = (
            mirror
            / "adapters"
            / "default"
            / "claude"
            / "governed-settings.json"
        )
        if not governed.is_file():
            raise ValueError(
                f"Claude governed settings are missing from the Harness mirror: {governed}"
            )
        print("claude_governed_settings: passed")

    print("harness_check: passed")
    print("enabled_providers: " + ", ".join(provider_ids))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    try:
        check(args.project)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
