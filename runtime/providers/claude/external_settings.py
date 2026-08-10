"""Repository-shared Claude settings projection with explicit ownership."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from project_context import ProjectContext
from providers.claude.settings_anchor import (
    ClaudeSettingsAnchor,
    resolve_settings_anchor,
)


PACKAGE_NAME = "sitter"
SIDECAR_NAME = "sitter.settings-owner.json"


class ClaudeExternalSettingsError(ValueError):
    pass


@dataclass(frozen=True)
class ExternalSettingsProjection:
    anchor: ClaudeSettingsAnchor
    content: str
    content_sha256: str
    sidecar_path: Path


@dataclass(frozen=True)
class ExternalSettingsSnapshot:
    settings: bytes | None
    sidecar: bytes | None


def _canonical_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _text_sha256(value: str) -> str:
    return hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()


def desired_projection(
    context: ProjectContext,
    settings_content: str,
) -> ExternalSettingsProjection:
    anchor = resolve_settings_anchor(context.project_root)
    content = _canonical_text(settings_content)
    return ExternalSettingsProjection(
        anchor=anchor,
        content=content,
        content_sha256=_text_sha256(content),
        sidecar_path=anchor.settings_path.with_name(SIDECAR_NAME),
    )


def snapshot(projection: ExternalSettingsProjection) -> ExternalSettingsSnapshot:
    settings = projection.anchor.settings_path
    sidecar = projection.sidecar_path
    return ExternalSettingsSnapshot(
        settings=settings.read_bytes() if settings.is_file() else None,
        sidecar=sidecar.read_bytes() if sidecar.is_file() else None,
    )


def restore(
    projection: ExternalSettingsProjection,
    value: ExternalSettingsSnapshot,
) -> None:
    for path, content in (
        (projection.anchor.settings_path, value.settings),
        (projection.sidecar_path, value.sidecar),
    ):
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.restore")
            temporary.write_bytes(content)
            temporary.replace(path)


def _sidecar(projection: ExternalSettingsProjection) -> dict:
    return {
        "package": PACKAGE_NAME,
        "schema_version": 1,
        "settings_path": str(projection.anchor.settings_path),
        "settings_sha256": projection.content_sha256,
    }


def assert_writable(projection: ExternalSettingsProjection) -> None:
    settings = projection.anchor.settings_path
    sidecar = projection.sidecar_path
    if settings.is_symlink() or sidecar.is_symlink():
        raise ClaudeExternalSettingsError(
            "Claude shared settings or ownership sidecar must not be a symlink"
        )
    if not settings.exists() and not sidecar.exists():
        return
    if not settings.is_file() or not sidecar.is_file():
        raise ClaudeExternalSettingsError(
            "Claude shared settings ownership is incomplete"
        )
    try:
        owner = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClaudeExternalSettingsError(
            f"invalid Claude shared settings sidecar: {sidecar}"
        ) from error
    if not isinstance(owner, dict) or owner.get("package") != PACKAGE_NAME:
        raise ClaudeExternalSettingsError(
            f"Claude shared settings are unmanaged: {settings}"
        )
    recorded = str(owner.get("settings_sha256") or "")
    actual = _text_sha256(settings.read_text(encoding="utf-8"))
    if not recorded or recorded != actual:
        raise ClaudeExternalSettingsError(
            f"Claude shared settings were modified outside the Harness: {settings}"
        )


def apply(projection: ExternalSettingsProjection) -> None:
    assert_writable(projection)
    settings = projection.anchor.settings_path
    sidecar = projection.sidecar_path
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings_temporary = settings.with_name(f".{settings.name}.staging")
    sidecar_temporary = sidecar.with_name(f".{sidecar.name}.staging")
    settings_temporary.write_text(
        projection.content,
        encoding="utf-8",
        newline="",
    )
    sidecar_temporary.write_text(
        json.dumps(_sidecar(projection), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    settings_temporary.replace(settings)
    sidecar_temporary.replace(sidecar)


def validate_installed(projection: ExternalSettingsProjection) -> None:
    assert_writable(projection)
    settings = projection.anchor.settings_path
    sidecar = projection.sidecar_path
    if not settings.is_file() or not sidecar.is_file():
        raise ClaudeExternalSettingsError(
            "Claude shared settings projection is missing"
        )
    if _canonical_text(settings.read_text(encoding="utf-8")) != projection.content:
        raise ClaudeExternalSettingsError(
            "Claude shared settings projection is stale"
        )
    owner = json.loads(sidecar.read_text(encoding="utf-8"))
    if owner.get("settings_sha256") != projection.content_sha256:
        raise ClaudeExternalSettingsError(
            "Claude shared settings sidecar has a stale hash"
        )
