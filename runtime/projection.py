"""Backward-compatible projection helpers during the V5 provider migration."""

from core.managed_projection import (
    MARKER,
    PACKAGE_NAME,
    assert_writable_projection,
    file_sha256,
    is_managed,
)
from providers.codex.projection import (
    entrypoint_text,
    skill_wrapper_text,
    toml_text,
)

__all__ = [
    "MARKER",
    "PACKAGE_NAME",
    "assert_writable_projection",
    "entrypoint_text",
    "file_sha256",
    "is_managed",
    "skill_wrapper_text",
    "toml_text",
]
