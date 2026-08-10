from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "runtime"))

from providers.codex.trust import (  # noqa: E402
    UNTRUSTED,
    ensure_project_trusted,
    project_trust_state,
)
from core.projection_plan import Projection, ProjectionPlan, merge_projection_plans  # noqa: E402
from core.provider_registry import get_provider, registered_providers  # noqa: E402
from project_context import ProjectContext  # noqa: E402
from projection import (  # noqa: E402
    assert_writable_projection,
    file_sha256,
    is_managed,
)


PACKAGE_NAME = "sitter"
EXCLUDE_BEGIN = f"# BEGIN {PACKAGE_NAME} managed projections"
EXCLUDE_END = f"# END {PACKAGE_NAME} managed projections"
LOCAL_MODEL_CONFIG = f".harness/{PACKAGE_NAME}.models.local.yaml"


def git_path(project: Path, relative: str) -> Path:
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--git-path", relative],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(f"project is not a Git worktree: {project}")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else project / path


def git_root(project: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(f"project is not a Git worktree: {project}")
    return Path(result.stdout.strip()).resolve()


def manifest() -> dict:
    data = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("package") != PACKAGE_NAME:
        raise ValueError("invalid package manifest")
    return data


def package_copy_ignore(project: Path):
    """Prevent generated mirrors or an in-tree target project from being recopied."""
    base_ignore = shutil.ignore_patterns(".git", ".harness", "__pycache__", "*.pyc")
    project = project.resolve()
    try:
        relative_project = project.relative_to(ROOT)
    except ValueError:
        relative_project = None

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(base_ignore(directory, names))
        directory_path = Path(directory).resolve()
        if relative_project is not None and relative_project.parts and directory_path == ROOT:
            ignored.add(relative_project.parts[0])
        return ignored

    return ignore


def provider_context(project: Path) -> ProjectContext:
    return ProjectContext(ROOT, project, ROOT / "adapters" / "default")


def installed_manifest(project: Path) -> dict | None:
    lock = project / ".harness" / PACKAGE_NAME / "manifest-lock.yaml"
    if not lock.is_file():
        return None
    try:
        data = yaml.safe_load(lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f"invalid installed Harness manifest: {lock}") from error
    if not isinstance(data, dict) or data.get("package") != PACKAGE_NAME:
        raise ValueError(f"installed Harness manifest is not owned by {PACKAGE_NAME}: {lock}")
    projections = data.get("projections")
    if not isinstance(projections, dict):
        raise ValueError(f"installed Harness manifest has no projection inventory: {lock}")
    return data


def installed_provider_ids(project: Path) -> tuple[str, ...] | None:
    data = installed_manifest(project)
    if data is None:
        return None
    values = data.get("enabled_providers")
    if values is None:
        # Pre-Provider releases (including V4.1) were Codex-only. They also did
        # not write projection_owners. Treat only that verified legacy shape as
        # Codex; a modern lock that lost enabled_providers is corruption.
        if data.get("projection_owners") is None:
            return ("codex",)
        lock = project / ".harness" / PACKAGE_NAME / "manifest-lock.yaml"
        raise ValueError(f"installed Harness manifest has no enabled providers: {lock}")
    if not isinstance(values, list) or not values:
        lock = project / ".harness" / PACKAGE_NAME / "manifest-lock.yaml"
        raise ValueError(f"installed Harness manifest has no enabled providers: {lock}")
    result = tuple(str(value) for value in values)
    for provider_id in result:
        get_provider(provider_id)
    return result


def resolve_provider_ids(
    project: Path,
    provider_ids: tuple[str, ...] | None,
    enable_provider_ids: tuple[str, ...],
) -> tuple[str, ...]:
    installed = installed_provider_ids(project)
    if provider_ids:
        selected = list(dict.fromkeys(provider_ids))
        if installed:
            removed = [value for value in installed if value not in selected]
            if removed:
                raise ValueError(
                    "disabling installed runtime providers is not supported in V5-B: "
                    + ", ".join(removed)
                )
    else:
        selected = list(installed or ("codex",))

    for value in enable_provider_ids:
        if value not in selected:
            selected.append(value)
    if not selected:
        raise ValueError("at least one runtime provider must be enabled")
    for provider_id in selected:
        get_provider(provider_id)
    return tuple(selected)


def provider_plans(
    project: Path,
    provider_ids: tuple[str, ...] | None = None,
) -> tuple[ProjectionPlan, ...]:
    context = provider_context(project)
    selected = provider_ids or ("codex",)
    return tuple(
        get_provider(provider_id).projection_plan(context)
        for provider_id in selected
    )


def desired_projections(
    project: Path,
    provider_ids: tuple[str, ...] | None = None,
) -> tuple[Projection, ...]:
    return merge_projection_plans(provider_plans(project, provider_ids))


def projection_targets(
    project: Path,
    provider_ids: tuple[str, ...] | None = None,
) -> list[Path]:
    return [
        item.target(project)
        for item in desired_projections(project, provider_ids)
    ]


def assert_managed_mirror(mirror: Path) -> None:
    if not mirror.exists():
        return
    if not mirror.is_dir():
        raise ValueError(f"refusing to replace non-directory Harness mirror: {mirror}")
    lock = mirror / "manifest-lock.yaml"
    if not lock.is_file():
        raise ValueError(f"refusing to delete unverified Harness mirror: {mirror}")
    try:
        data = yaml.safe_load(lock.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"invalid installed Harness manifest: {lock}") from error
    if not isinstance(data, dict) or data.get("package") != PACKAGE_NAME:
        raise ValueError(f"refusing to delete mirror not owned by {PACKAGE_NAME}: {mirror}")


def _installed_projection_path(project: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("installed Harness manifest contains an invalid projection path")
    normalized = relative.replace("\\", "/").strip()
    if (
        normalized.startswith("/")
        or normalized.startswith("~")
        or (len(normalized) >= 2 and normalized[1] == ":")
    ):
        raise ValueError(f"installed projection path is not project-relative: {relative}")
    candidate = (project / Path(normalized)).resolve()
    try:
        candidate.relative_to(project.resolve())
    except ValueError as error:
        raise ValueError(f"installed projection path escapes project: {relative}") from error
    return candidate


def installed_projection_paths(project: Path) -> tuple[Path, ...]:
    data = installed_manifest(project)
    if data is None:
        return ()
    projections = data["projections"]
    paths: list[Path] = []
    for relative, expected_hash in projections.items():
        if not isinstance(expected_hash, str) or not expected_hash:
            raise ValueError(
                f"installed Harness manifest contains an invalid projection hash: {relative}"
            )
        target = _installed_projection_path(project, relative)
        if target.exists():
            if not target.is_file():
                raise ValueError(
                    f"installed Harness projection is not a file: {target}"
                )
            actual_hash = file_sha256(target)
            if actual_hash != expected_hash and not is_managed(target):
                raise ValueError(
                    "installed Harness projection was modified and is no longer "
                    f"provably Harness-managed; refusing transactional replace: {target}"
                )
        paths.append(target)
    return tuple(dict.fromkeys(paths))


def reinstall_cleanup_targets(
    project: Path,
    plans: tuple[ProjectionPlan, ...],
) -> list[Path]:
    """Compatibility cleanup for marker-managed residue not present in old locks.

    Normal upgrades are manifest-driven. --reinstall remains accepted for old
    automation and may additionally remove verified sitter-* residue discovered
    by the current Provider implementations.
    """
    context = provider_context(project)
    stale: list[Path] = []
    for plan in plans:
        stale.extend(
            get_provider(plan.provider).stale_projection_candidates(context, plan)
        )
    mirror = project / ".harness" / PACKAGE_NAME
    assert_managed_mirror(mirror)
    return [mirror, *stale]


def write_exclude(project: Path, projections: tuple[Projection, ...]) -> None:
    exclude = git_path(project, "info/exclude")
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if EXCLUDE_BEGIN in existing:
        before = existing.split(EXCLUDE_BEGIN, 1)[0].rstrip()
        after = existing.split(EXCLUDE_END, 1)[1].lstrip() if EXCLUDE_END in existing else ""
        existing = "\n".join(part for part in (before, after) if part)
    repository = git_root(project)
    try:
        project_relative = project.resolve().relative_to(repository)
    except ValueError as error:
        raise ValueError(f"project is outside its Git worktree: {project}") from error
    prefix = "/" if project_relative == Path(".") else f"/{project_relative.as_posix()}/"
    projection_lines = [
        f"{prefix}{item.relative_path.as_posix()}"
        for item in sorted(projections, key=lambda item: item.relative_path.as_posix())
    ]
    block = "\n".join((
        EXCLUDE_BEGIN,
        f"{prefix}.harness/{PACKAGE_NAME}/",
        f"{prefix}{LOCAL_MODEL_CONFIG}",
        *projection_lines,
        f"{prefix}.agent-work/",
        f"{prefix}changes/",
        EXCLUDE_END,
    ))
    exclude.write_text((existing.rstrip() + "\n\n" + block + "\n").lstrip(), encoding="utf-8")


def stage_package_mirror(project: Path, mirror: Path) -> Path:
    mirror.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{PACKAGE_NAME}.staging-", dir=mirror.parent))
    try:
        shutil.copytree(ROOT, staging, dirs_exist_ok=True, ignore=package_copy_ignore(project))
        (staging / "source.yaml").write_text(
            yaml.safe_dump({"source_root": str(ROOT.resolve())}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def remove_projection(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def snapshot_files(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def restore_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _prune_empty_projection_parents(project: Path, paths: tuple[Path, ...]) -> None:
    root = project.resolve()
    for path in paths:
        parent = path.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def install(
    project: Path,
    *,
    dry_run: bool,
    adopt_existing: bool = False,
    reinstall: bool = False,
    trust_project: bool = False,
    force_trust_project: bool = False,
    codex_home: Path | None = None,
    provider_ids: tuple[str, ...] | None = None,
    enable_provider_ids: tuple[str, ...] = (),
) -> None:
    project = project.resolve()
    exclude_path = git_path(project, "info/exclude")
    package_manifest = manifest()

    # Validate the old installation before computing the desired state. The
    # projection inventory is the uninstall contract across versions.
    installed_paths = installed_projection_paths(project)
    installed_set = {path.resolve() for path in installed_paths}

    selected_provider_ids = resolve_provider_ids(
        project,
        provider_ids,
        enable_provider_ids,
    )
    plans = provider_plans(project, selected_provider_ids)
    projections = merge_projection_plans(plans)
    targets = [item.target(project) for item in projections]

    unmanaged = [
        target
        for target in targets
        if target.exists()
        and target.resolve() not in installed_set
        and not is_managed(target)
    ]
    if unmanaged and not adopt_existing:
        assert_writable_projection(unmanaged[0])

    compatibility_cleanup = (
        reinstall_cleanup_targets(project, plans) if reinstall else []
    )
    compatibility_cleanup = [
        path
        for path in compatibility_cleanup
        if path != project / ".harness" / PACKAGE_NAME
        and path.resolve() not in installed_set
    ]

    trust_state = None
    if (trust_project or force_trust_project) and "codex" not in selected_provider_ids:
        raise ValueError(
            "Codex trust can only be configured when the codex provider is enabled"
        )
    if trust_project or force_trust_project:
        trust_state = project_trust_state(project, codex_home=codex_home)
        if trust_state.status == UNTRUSTED and not force_trust_project:
            raise ValueError(
                f"project is explicitly untrusted in {trust_state.config_path}; "
                "use --force-trust-project to override that prior decision"
            )

    mirror = project / ".harness" / PACKAGE_NAME
    if mirror.exists():
        assert_managed_mirror(mirror)

    if dry_run:
        for path in installed_paths:
            if path.exists():
                print(f"would remove installed managed projection: {path}")
        for path in compatibility_cleanup:
            if path.exists():
                print(f"would remove managed stale projection: {path}")
        for path in [mirror, *targets, exclude_path]:
            print(f"would generate: {path}")
        for path in unmanaged:
            print(f"would back up unmanaged projection: {path}")
        if trust_state is not None:
            print(
                f"would trust Codex project root: {trust_state.trust_root} "
                f"in {trust_state.config_path}"
            )
        return

    staged_mirror: Path | None = None
    previous_mirror: Path | None = None
    mirror_replaced = False
    install_succeeded = False

    # Old managed projections, new desired projections and the local exclude
    # block are one rollback unit. Durable project state is deliberately absent.
    file_snapshot = snapshot_files(
        list(dict.fromkeys([*installed_paths, *targets, exclude_path]))
    )

    try:
        staged_mirror = stage_package_mirror(project, mirror)
        if mirror.exists():
            candidate = mirror.with_name(f".{PACKAGE_NAME}.previous")
            if candidate.exists():
                raise ValueError(
                    f"stale Harness replacement backup requires manual review: {candidate}"
                )
            mirror.rename(candidate)
            previous_mirror = candidate
        staged_mirror.rename(mirror)
        staged_mirror = None
        mirror_replaced = True

        # Transactional replace: uninstall the previous generated projection
        # layer first, then materialize only the current desired state.
        for path in installed_paths:
            if path.is_file() or path.is_symlink():
                path.unlink()

        for target in unmanaged:
            backup = mirror / "legacy-backup" / target.relative_to(project)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)

        for projection in projections:
            target = projection.target(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(projection.content, encoding="utf-8")

        generated = {
            item.relative_path.as_posix(): file_sha256(item.target(project))
            for item in projections
        }
        owners = {
            item.relative_path.as_posix(): item.owner
            for item in projections
        }
        lock = mirror / "manifest-lock.yaml"
        lock.write_text(
            yaml.safe_dump(
                {
                    "package": PACKAGE_NAME,
                    "format_version": package_manifest["format_version"],
                    "version": package_manifest["version"],
                    "installation_strategy": "transactional-replace",
                    "enabled_providers": list(selected_provider_ids),
                    "projections": generated,
                    "projection_owners": owners,
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        write_exclude(project, projections)

        if trust_project or force_trust_project:
            trusted = ensure_project_trusted(
                project,
                codex_home=codex_home,
                force=force_trust_project,
            )
            print(f"trusted Codex project root {trusted.trust_root} in {trusted.config_path}")

        # Legacy --reinstall compatibility cleanup remains deliberately
        # supplemental. Normal version replacement never depends on file-name
        # knowledge from historical releases.
        for path in compatibility_cleanup:
            if not path.exists():
                continue
            remove_projection(path)

        install_succeeded = True
    finally:
        if staged_mirror is not None and staged_mirror.exists():
            shutil.rmtree(staged_mirror, ignore_errors=True)
        if install_succeeded:
            _prune_empty_projection_parents(project, installed_paths)
            if previous_mirror is not None and previous_mirror.exists():
                shutil.rmtree(previous_mirror)
        else:
            restore_files(file_snapshot)
            if mirror_replaced and mirror.exists():
                shutil.rmtree(mirror, ignore_errors=True)
            if previous_mirror is not None and previous_mirror.exists():
                previous_mirror.rename(mirror)

    print(f"installed {PACKAGE_NAME} into {project}")
    if "codex" in selected_provider_ids and not (
        trust_project or force_trust_project
    ):
        print(
            "NOTE: project-local Codex config requires project trust; "
            "rerun with --trust-project or approve the project in Codex, then start a new session."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the transactional replacement plan without writing",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="compatibility alias; existing installations are always replaced transactionally",
    )
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help=(
            "compatibility alias that also scans verified legacy sitter-* residue; "
            "ordinary installs already replace the managed installation transactionally"
        ),
    )
    parser.add_argument("--adopt-existing", action="store_true")
    parser.add_argument(
        "--trust-project",
        action="store_true",
        help="explicitly trust the Git common root in the user-level Codex config",
    )
    parser.add_argument(
        "--force-trust-project",
        action="store_true",
        help="override an existing explicit untrusted entry; implies --trust-project",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        help="override CODEX_HOME (primarily for controlled installation and tests)",
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=registered_providers(),
        help="enable exactly this runtime provider; repeat for multiple providers",
    )
    parser.add_argument(
        "--enable-provider",
        action="append",
        default=[],
        choices=registered_providers(),
        help="add one provider to the currently installed provider set",
    )
    args = parser.parse_args()
    try:
        install(
            args.project,
            dry_run=args.dry_run,
            adopt_existing=args.adopt_existing,
            reinstall=args.reinstall,
            trust_project=args.trust_project or args.force_trust_project,
            force_trust_project=args.force_trust_project,
            codex_home=args.codex_home,
            provider_ids=tuple(args.provider) if args.provider else None,
            enable_provider_ids=tuple(args.enable_provider),
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
