from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


TRUSTED = "trusted"
UNTRUSTED = "untrusted"
TABLE_HEADER_RE = re.compile(r"^\s*\[{1,2}.*\]{1,2}\s*(?:#.*)?$")
TRUST_ASSIGNMENT_RE = re.compile(r"^(?P<indent>\s*)trust_level\s*=.*$")


@dataclass(frozen=True)
class ProjectTrustState:
    trust_root: Path
    config_path: Path
    status: str
    configured_key: str | None = None
    configured_keys: tuple[str, ...] = ()


def _run_git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", *args],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(f"project is not a Git worktree: {project}")
    return result.stdout.strip()


def _strip_windows_extended_prefix(value: str) -> str:
    return value[4:] if value.startswith("\\\\?\\") else value


def canonical_path(path: Path) -> Path:
    return Path(_strip_windows_extended_prefix(str(path.resolve())))


def normalized_path_key(value: str | Path) -> str:
    text = _strip_windows_extended_prefix(str(value))
    return os.path.normcase(os.path.normpath(text))


def resolve_trust_root(project: Path) -> Path:
    project = canonical_path(project)
    common_dir_text = _run_git(project, "--git-common-dir")
    common_dir = Path(common_dir_text)
    if not common_dir.is_absolute():
        common_dir = project / common_dir
    common_dir = canonical_path(common_dir)
    if common_dir.name.lower() != ".git":
        raise ValueError(f"cannot derive Codex trust root from Git common dir: {common_dir}")
    return canonical_path(common_dir.parent)


def resolve_codex_home(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return canonical_path(explicit)
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return canonical_path(Path(configured))
    return canonical_path(Path.home() / ".codex")


def _parse_config(text: str, config_path: Path) -> dict:
    try:
        parsed = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"invalid Codex user config: {config_path}: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"invalid Codex user config root: {config_path}")
    return parsed


def _matching_project_entries(parsed: dict, trust_root: Path) -> list[tuple[str, dict]]:
    projects = parsed.get("projects", {})
    if projects is None:
        return []
    if not isinstance(projects, dict):
        raise ValueError("Codex user config [projects] must be a table")
    expected = normalized_path_key(trust_root)
    matches: list[tuple[str, dict]] = []
    for key, value in projects.items():
        if not isinstance(key, str) or normalized_path_key(key) != expected:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Codex project trust entry is not a table: {key}")
        matches.append((key, value))
    return matches


def _matching_status(
    matches: list[tuple[str, dict]],
    trust_root: Path,
    *,
    allow_conflict: bool = False,
) -> str:
    levels = {entry.get("trust_level") for _, entry in matches}
    if TRUSTED in levels and UNTRUSTED in levels:
        if allow_conflict:
            return "conflict"
        aliases = ", ".join(key for key, _ in matches)
        raise ValueError(
            f"conflicting Codex trust entries resolve to the same project: "
            f"{trust_root}: {aliases}"
        )
    if UNTRUSTED in levels:
        return UNTRUSTED
    if TRUSTED in levels:
        return TRUSTED
    return "unset"


def project_trust_state(project: Path, *, codex_home: Path | None = None) -> ProjectTrustState:
    trust_root = resolve_trust_root(project)
    config_path = resolve_codex_home(codex_home) / "config.toml"
    if not config_path.exists():
        return ProjectTrustState(trust_root, config_path, "missing")
    text = config_path.read_text(encoding="utf-8")
    parsed = _parse_config(text, config_path)
    matches = _matching_project_entries(parsed, trust_root)
    if not matches:
        return ProjectTrustState(trust_root, config_path, "missing")
    keys = tuple(key for key, _ in matches)
    status = _matching_status(matches, trust_root)
    return ProjectTrustState(trust_root, config_path, status, keys[0], keys)


def _project_key_from_header(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or stripped.startswith("[["):
        return None
    try:
        parsed = tomllib.loads(stripped + "\n")
    except tomllib.TOMLDecodeError:
        return None
    projects = parsed.get("projects") if isinstance(parsed, dict) else None
    if not isinstance(projects, dict) or len(projects) != 1:
        return None
    key = next(iter(projects))
    return key if isinstance(key, str) else None


def _replace_or_insert_trust_level(text: str, configured_key: str) -> str:
    lines = text.splitlines(keepends=True)
    section_start: int | None = None
    for index, line in enumerate(lines):
        if _project_key_from_header(line) == configured_key:
            section_start = index
            break
    if section_start is None:
        raise ValueError(f"cannot locate Codex project trust table for: {configured_key}")

    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        if TABLE_HEADER_RE.match(lines[index].strip()):
            section_end = index
            break

    for index in range(section_start + 1, section_end):
        line_without_newline = lines[index].rstrip("\r\n")
        match = TRUST_ASSIGNMENT_RE.match(line_without_newline)
        if match:
            newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
            lines[index] = f'{match.group("indent")}trust_level = "trusted"{newline}'
            return "".join(lines)

    newline = "\r\n" if "\r\n" in text else "\n"
    lines.insert(section_start + 1, f'trust_level = "trusted"{newline}')
    return "".join(lines)


def _set_all_matching_entries_trusted(text: str, keys: tuple[str, ...]) -> str:
    updated = text
    for key in keys:
        updated = _replace_or_insert_trust_level(updated, key)
    return updated


def render_trusted_config(
    text: str,
    *,
    config_path: Path,
    trust_root: Path,
    force: bool = False,
) -> tuple[str, bool]:
    parsed = _parse_config(text, config_path)
    matches = _matching_project_entries(parsed, trust_root)
    if matches:
        status = _matching_status(matches, trust_root, allow_conflict=True)
        if status == "conflict" and not force:
            aliases = ", ".join(key for key, _ in matches)
            raise ValueError(
                f"conflicting Codex trust entries resolve to the same project: "
                f"{trust_root}: {aliases}; use --force-trust-project to set all aliases trusted"
            )
        if status == UNTRUSTED and not force:
            raise ValueError(
                f"project is explicitly untrusted in {config_path}; "
                "use --force-trust-project to override that prior decision"
            )
        keys = tuple(key for key, _ in matches)
        if all(entry.get("trust_level") == TRUSTED for _, entry in matches):
            return text, False
        updated = _set_all_matching_entries_trusted(text, keys)
    else:
        newline = "\r\n" if "\r\n" in text else "\n"
        prefix = text.rstrip("\r\n")
        separator = newline * 2 if prefix else ""
        project_key = json.dumps(str(trust_root), ensure_ascii=False)
        updated = (
            f"{prefix}{separator}[projects.{project_key}]{newline}"
            f'trust_level = "trusted"{newline}'
        )

    reparsed = _parse_config(updated, config_path)
    verified = _matching_project_entries(reparsed, trust_root)
    if not verified or any(entry.get("trust_level") != TRUSTED for _, entry in verified):
        raise ValueError(f"failed to verify Codex project trust update: {trust_root}")
    return updated, updated != text


def ensure_project_trusted(
    project: Path,
    *,
    codex_home: Path | None = None,
    force: bool = False,
) -> ProjectTrustState:
    trust_root = resolve_trust_root(project)
    config_path = resolve_codex_home(codex_home) / "config.toml"
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated, changed = render_trusted_config(
        original,
        config_path=config_path,
        trust_root=trust_root,
        force=force,
    )
    if not changed:
        state = project_trust_state(project, codex_home=codex_home)
        if state.status != TRUSTED:
            raise ValueError(f"Codex project trust did not persist: {trust_root}")
        return state

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = config_path.with_name(f"{config_path.name}.bak.{stamp}")
        counter = 1
        while backup.exists():
            backup = config_path.with_name(f"{config_path.name}.bak.{stamp}.{counter}")
            counter += 1
        shutil.copy2(config_path, backup)

    temporary = config_path.with_name(f".{config_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(updated, encoding="utf-8")
        _parse_config(temporary.read_text(encoding="utf-8"), temporary)
        os.replace(temporary, config_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    state = project_trust_state(project, codex_home=codex_home)
    if state.status != TRUSTED:
        raise ValueError(f"Codex project trust did not persist: {trust_root}")
    return state
