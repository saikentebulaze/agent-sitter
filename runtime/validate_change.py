"""Compatibility facade for Change validation with V6.2 runtime-evidence proof."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import _validate_change_impl as _impl
from _validate_change_impl import *  # noqa: F401,F403
from review_evidence_guard import (
    ReviewEvidenceError,
    validate_current_protocol2_review,
)


def main() -> None:
    # Preserve the existing validator byte-for-byte behind this facade. Buffer
    # its success output so a Protocol-2 evidence failure can never print a
    # misleading "change_state: valid" first.
    if len(sys.argv) < 2:
        _impl.main()
        return

    path = Path(sys.argv[1])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        _impl.main()

    data = _impl.load_json_or_yaml_like(path / "change.yaml")
    review = data.get("review") or {}
    execution = review.get("execution") or {}
    if int(execution.get("review_protocol") or 1) == 2:
        try:
            validate_current_protocol2_review(path, data)
        except ReviewEvidenceError as error:
            _impl.fail(str(error))

    print(output.getvalue(), end="")


if __name__ == "__main__":
    main()
