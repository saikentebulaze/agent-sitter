"""Compatibility facade for Sitter Learning with shared Task reference parsing."""

from __future__ import annotations

import _learning_impl as _impl
from _learning_impl import *  # noqa: F401,F403
from learning_ref_compat import resolve_task_yaml


_impl.resolve_task = resolve_task_yaml


if __name__ == "__main__":
    _impl.main()
