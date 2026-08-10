"""Resolve the runtime provider attached to a governed request."""

from __future__ import annotations


DEFAULT_RUNTIME_PROVIDER = "codex"


def provider_id_from_packet(packet: dict) -> str:
    runtime = packet.get("runtime") or {}
    if not isinstance(runtime, dict):
        raise ValueError("runtime metadata must be a mapping")
    value = runtime.get("provider", DEFAULT_RUNTIME_PROVIDER)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("runtime provider must be a non-empty string")
    return value.strip()
