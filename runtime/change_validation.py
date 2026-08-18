from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path


class ChangeValidationError(ValueError):
    pass


def validate_change_in_process(change: str | Path) -> str:
    """Run the existing Change validator without spawning another Python process.

    `validate_change.py` remains the compatibility CLI and still owns the
    validation rules. This adapter only provides an in-process transaction seam
    for Harness code such as review recording, reducing Windows process-launch
    friction without duplicating validation logic.
    """

    import validate_change

    output = io.StringIO()
    errors = io.StringIO()
    previous_argv = sys.argv
    try:
        sys.argv = ["validate_change.py", str(Path(change))]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                validate_change.main()
            except SystemExit as exit_error:
                code = exit_error.code
                if code not in {None, 0}:
                    message = errors.getvalue().strip() or output.getvalue().strip()
                    raise ChangeValidationError(
                        message or f"change validation failed with exit code {code}"
                    ) from exit_error
    finally:
        sys.argv = previous_argv
    return output.getvalue().strip()
