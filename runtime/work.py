"""Compatibility facade for governed Work commands with shared reference parsing."""

from __future__ import annotations

import work_graph as _work_graph
from reference_resolver import resolve_change_ref, resolve_task_ref


def _resolve_task_root(context, value):
    return resolve_task_ref(context, value).root


def _resolve_change_root(context, value):
    return resolve_change_ref(context, value).root


# Patch the shared Work Graph module before importing the preserved CLI. Modules
# imported by `_work_impl` therefore bind the same ID / directory / YAML-aware
# resolver instead of keeping different parsing rules per command.
_work_graph.resolve_task_root = _resolve_task_root
_work_graph.resolve_change_root = _resolve_change_root

import _work_impl as _impl  # noqa: E402
from _work_impl import *  # noqa: E402,F401,F403

_impl.resolve_task_root = _resolve_task_root


if __name__ == "__main__":
    _impl.main()
