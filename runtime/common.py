from __future__ import annotations
from pathlib import Path
import json
import subprocess
import sys

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required for Harness YAML artifacts; "
        "install runtime/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
# Compatibility alias for tools not yet converted to an explicit project context.
ROOT = PACKAGE_ROOT


def run_git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def load_json_or_yaml_like(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        fail(f"artifact root must be a mapping: {path}")
    return data


def fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)
