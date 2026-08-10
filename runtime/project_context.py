from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


PACKAGE_NAME = "sitter"
FORMAT_VERSION = 1
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ProjectContext:
    package_root: Path
    project_root: Path
    adapter_root: Path

    def __post_init__(self) -> None:
        # Callers frequently construct ProjectContext directly in tests and
        # runtime helpers. Normalize once at the boundary so Windows path case,
        # short-name expansion, and relative segments cannot make a valid task
        # appear outside its own project root.
        object.__setattr__(self, "package_root", self.package_root.resolve())
        object.__setattr__(self, "project_root", self.project_root.resolve())
        object.__setattr__(self, "adapter_root", self.adapter_root.resolve())


def load_mapping(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"missing manifest-lock: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest-lock must be a mapping: {path}")
    return data


def resolve_project_context(project_root: Path, *, package_root: Path | None = None) -> ProjectContext:
    resolved_project = project_root.resolve()
    if not (resolved_project / ".git").exists():
        raise ValueError(f"project is not a Git worktree: {resolved_project}")

    resolved_package = (package_root or PACKAGE_ROOT).resolve()
    manifest = resolved_package / "manifest.yaml"
    package = load_mapping(manifest)
    if package.get("package") != PACKAGE_NAME or package.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported package manifest: {manifest}")

    lock = resolved_project / ".harness" / PACKAGE_NAME / "manifest-lock.yaml"
    lock_data = load_mapping(lock)
    if lock_data.get("package") != PACKAGE_NAME or lock_data.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported manifest-lock: {lock}")

    adapter_root = resolved_package / "adapters" / "default"
    if not adapter_root.is_dir():
        raise ValueError(f"missing default adapter: {adapter_root}")
    return ProjectContext(resolved_package, resolved_project, adapter_root)
