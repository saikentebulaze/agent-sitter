"""Backward-compatible CLI for Codex delegation runtime operations."""

from providers.codex.delegation_runtime import (
    DelegationRuntimeError,
    _attempt,
    _entry,
    _existing_managed_artifacts,
    _load,
    _record,
    _runtime_packet,
    _runtime_paths,
    _write_runtime_artifacts,
    collect_native,
    delegation_message,
    fail,
    main,
    run_isolated,
    runtime_task_name,
    spawn_contract,
)

__all__ = [
    "DelegationRuntimeError",
    "_attempt",
    "_entry",
    "_existing_managed_artifacts",
    "_load",
    "_record",
    "_runtime_packet",
    "_runtime_paths",
    "_write_runtime_artifacts",
    "collect_native",
    "delegation_message",
    "fail",
    "main",
    "run_isolated",
    "runtime_task_name",
    "spawn_contract",
]


if __name__ == "__main__":
    main()
