from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = ROOT / "scripts" / "acceptance" / "v6-ab-benchmark.py"
SPEC = importlib.util.spec_from_file_location("v6_ab_common", COMMON_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load shared A/B helpers: {COMMON_PATH}")
COMMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMON)

DEFAULT_BASELINE_REF = COMMON.DEFAULT_BASELINE_REF
CONTROL_NAME = "control.json"
PROMPT_REF = Path(".v6-fast-path/PROMPT.md")
RESULT_REF = Path(".v6-fast-path/result.json")
MUTABLE_TARGET = "src/fast_path.py"
EXPECTED_SOURCE = "def size(items):\n    count = len(items)\n    return count\n"


def _safe_root(destination: Path, force: bool) -> Path:
    root = destination.expanduser().resolve()
    if root.exists():
        if not force:
            raise RuntimeError(f"destination already exists: {root}; use --force to replace it")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _fixture_payloads() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {
        MUTABLE_TARGET: b"def size(items):\n    x = len(items)\n    return x\n",
        "tests/test_fast_path.py": (
            b"import sys\n"
            b"from pathlib import Path\n\n"
            b"sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            b"from src.fast_path import size\n\n"
            b"assert size([1, 2, 3]) == 3\n"
            b"print('fast_path: pass')\n"
        ),
        ".agent-work/_context/active-tasks.yaml": yaml.safe_dump(
            {
                "version": 1,
                "tasks": [
                    {
                        "id": "unrelated-active-one",
                        "title": "Unrelated nonlinear solver investigation",
                        "provider": "codex",
                        "registered_at": "2000-01-01T00:00:00+00:00",
                    },
                    {
                        "id": "unrelated-active-two",
                        "title": "Unrelated result convention review",
                        "provider": "codex",
                        "registered_at": "2000-01-01T00:00:00+00:00",
                    },
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8"),
        ".agent-work/_archive/archive-index.yaml": yaml.safe_dump(
            {
                "version": 1,
                "tasks": [f"archived-task-{index:04d}" for index in range(1000)],
            },
            sort_keys=False,
        ).encode("utf-8"),
        "knowledge/history.md": (
            b"# Historical local rename notes\n\n"
            b"These old notes intentionally share words with the new LOW task. "
            b"They are historical context, not a reason to resume old governed work.\n"
        ),
    }
    knowledge_entries = []
    for index in range(100):
        knowledge_entries.append(
            {
                "id": f"FAST-HIST-{index:03d}",
                "title": f"Historical local rename note {index}",
                "type": "fact",
                "evidence_status": "verified",
                "architecture_status": "legacy",
                "path": "knowledge/history.md",
                "domains": ["local-refactor"],
                "keywords": ["rename", "count", "local", "variable", "history"],
                "related": [],
                "memory_key": f"fast-history-{index:03d}",
            }
        )
    payloads["knowledge/index.yaml"] = yaml.safe_dump(
        {"version": 1, "entries": knowledge_entries},
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    return payloads


def _fixture_hash(project: Path) -> str:
    digest = hashlib.sha256()
    for relative in sorted(_fixture_payloads()):
        path = project / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _immutable_fixture_valid(project: Path) -> bool:
    for relative, expected in _fixture_payloads().items():
        if relative == MUTABLE_TARGET:
            continue
        path = project / relative
        if not path.is_file() or path.read_bytes() != expected:
            return False
    return True


def _write_fixture(project: Path) -> str:
    for relative, content in _fixture_payloads().items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return _fixture_hash(project)


def _git_init(project: Path) -> str:
    COMMON._run(["git", "init"], cwd=project)
    COMMON._run(["git", "config", "user.email", "v6-fast@example.invalid"], cwd=project)
    COMMON._run(["git", "config", "user.name", "V6 Fast Path"], cwd=project)
    COMMON._run(["git", "add", "-A"], cwd=project)
    COMMON._run(["git", "commit", "-m", "Create LOW Fast Path fixture"], cwd=project)
    return COMMON._run(["git", "rev-parse", "HEAD"], cwd=project).stdout.strip()


def _prompt(model_label: str) -> str:
    return f"""Rename the local variable `x` to `count` in `src/fast_path.py` without changing behavior. Make the smallest patch and run `python tests/test_fast_path.py`. Do not modify unrelated project source or documentation.

At the end, write `.v6-fast-path/result.json` containing exactly:

```json
{{
  "schema_version": 1,
  "parent_model_label": "{model_label}",
  "test_passed": true,
  "changed_source": "src/fast_path.py"
}}
```
"""


def _file_set(project: Path) -> list[str]:
    result = []
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project).as_posix()
        if relative.startswith(".git/"):
            continue
        if "__pycache__/" in relative or relative.endswith(".pyc"):
            continue
        result.append(relative)
    return sorted(result)


def _prepare_side(root: Path, name: str, harness_source: Path, prompt: bytes) -> dict:
    project = root / name / "project"
    project.mkdir(parents=True)
    fixture_hash = _write_fixture(project)
    fixture_commit = _git_init(project)
    COMMON._install(harness_source, project)
    prompt_path = project / PROMPT_REF
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_bytes(prompt)
    return {
        "project": str(project),
        "fixture_sha256": fixture_hash,
        "fixture_commit": fixture_commit,
        "prompt_sha256": COMMON._sha256_bytes(prompt),
        "prompt": str(prompt_path),
        "result": str(project / RESULT_REF),
        "pre_files": _file_set(project),
    }


def prepare(
    destination: Path,
    *,
    baseline_ref: str,
    candidate_ref: str,
    model_label: str,
    force: bool,
) -> dict:
    if not model_label.strip():
        raise RuntimeError("--model-label is required")
    root = _safe_root(destination, force)
    sources = root / "harness-snapshots"
    baseline_source = sources / "baseline"
    candidate_source = sources / "candidate"
    baseline_sha = COMMON._materialize_ref(baseline_ref, baseline_source)
    candidate_sha = COMMON._materialize_ref(candidate_ref, candidate_source)
    prompt = _prompt(model_label.strip()).encode("utf-8")
    baseline = _prepare_side(root, "baseline", baseline_source, prompt)
    candidate = _prepare_side(root, "candidate", candidate_source, prompt)
    if baseline["fixture_sha256"] != candidate["fixture_sha256"]:
        raise RuntimeError("Fast Path A/B fixture differs before model execution")
    if baseline["prompt_sha256"] != candidate["prompt_sha256"]:
        raise RuntimeError("Fast Path A/B prompt differs before model execution")
    control = {
        "schema_version": 1,
        "baseline_ref": baseline_ref,
        "baseline_sha": baseline_sha,
        "candidate_ref": candidate_ref,
        "candidate_sha": candidate_sha,
        "model_label": model_label.strip(),
        "fixture_sha256": baseline["fixture_sha256"],
        "prompt_sha256": baseline["prompt_sha256"],
        "baseline": baseline,
        "candidate": candidate,
    }
    (root / CONTROL_NAME).write_text(json.dumps(control, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PREPARED_NOT_RUN",
        "root": str(root),
        "baseline_project": baseline["project"],
        "candidate_project": candidate["project"],
        "model_label": model_label.strip(),
        "next": (
            "Launch two genuinely fresh Codex sessions with the same model/configuration, one in each project, "
            "and give each .v6-fast-path/PROMPT.md. Then run score."
        ),
    }


def _normal_task_dirs(project: Path) -> list[str]:
    root = project / ".agent-work"
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )


def _count_dirs(project: Path, name: str) -> int:
    return sum(1 for path in project.rglob(name) if path.is_dir())


def _active_changes(project: Path) -> list[str]:
    root = project / "changes" / "active"
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _score_side(project: Path, side: dict, model_label: str) -> dict:
    result_path = project / RESULT_REF
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    test = COMMON._run([sys.executable, "tests/test_fast_path.py"], cwd=project, check=False)
    source = project / MUTABLE_TARGET
    source_text = source.read_text(encoding="utf-8") if source.is_file() else ""
    diff = COMMON._run(["git", "diff", "--name-only"], cwd=project, check=False)
    tracked_diff = sorted(line.strip().replace("\\", "/") for line in diff.stdout.splitlines() if line.strip())
    current_files = set(_file_set(project))
    pre_files = set(side.get("pre_files") or [])
    new_files = sorted(current_files - pre_files)
    unexpected_new_files = [value for value in new_files if value != RESULT_REF.as_posix()]
    tasks = _normal_task_dirs(project)
    changes = _active_changes(project)
    delegation_dirs = _count_dirs(project, "delegations")
    memory_recall_dirs = _count_dirs(project, "_memory-recalls")
    investigation_dirs = _count_dirs(project, "investigations")
    governance_artifacts = len(tasks) + len(changes) + delegation_dirs + memory_recall_dirs + investigation_dirs
    checks = {
        "model_label_matches_control": result.get("parent_model_label") == model_label,
        "receipt_reports_test_pass": result.get("test_passed") is True,
        "receipt_reports_only_source": result.get("changed_source") == MUTABLE_TARGET,
        "source_is_minimal_rename": source_text == EXPECTED_SOURCE,
        "existing_test_passes": test.returncode == 0,
        "tracked_diff_only_source": tracked_diff == [MUTABLE_TARGET],
        "immutable_fixture_unchanged": _immutable_fixture_valid(project),
        "no_new_governed_task": tasks == [],
        "no_change_object": changes == [],
        "no_delegation": delegation_dirs == 0,
        "no_memory_recall": memory_recall_dirs == 0,
        "no_investigation": investigation_dirs == 0,
        "no_extra_plan_or_artifact": unexpected_new_files == [],
    }
    return {
        "absolute_pass": all(bool(value) for value in checks.values()),
        "checks": checks,
        "governance_artifact_count": governance_artifacts,
        "new_files": new_files,
        "unexpected_new_files": unexpected_new_files,
        "tracked_diff": tracked_diff,
        "task_dirs": tasks,
        "active_changes": changes,
        "delegation_dirs": delegation_dirs,
        "memory_recall_dirs": memory_recall_dirs,
        "investigation_dirs": investigation_dirs,
    }


def score(root: Path) -> dict:
    root = root.expanduser().resolve()
    control = json.loads((root / CONTROL_NAME).read_text(encoding="utf-8"))
    baseline_project = Path(control["baseline"]["project"]).resolve()
    candidate_project = Path(control["candidate"]["project"]).resolve()
    controls_valid = (
        _immutable_fixture_valid(baseline_project)
        and _immutable_fixture_valid(candidate_project)
        and COMMON._sha256_file(baseline_project / PROMPT_REF) == control["prompt_sha256"]
        and COMMON._sha256_file(candidate_project / PROMPT_REF) == control["prompt_sha256"]
    )
    baseline = _score_side(baseline_project, control["baseline"], control["model_label"])
    candidate = _score_side(candidate_project, control["candidate"], control["model_label"])
    no_overhead_regression = (
        candidate["governance_artifact_count"] <= baseline["governance_artifact_count"]
        and len(candidate["unexpected_new_files"]) <= len(baseline["unexpected_new_files"])
    )
    passed = bool(controls_valid and candidate["absolute_pass"] and no_overhead_regression)
    return {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "controls_valid": controls_valid,
        "model_label": control["model_label"],
        "baseline": baseline,
        "candidate": candidate,
        "no_overhead_regression": no_overhead_regression,
        "fast_path_overhead_delta": {
            "governance_artifacts": candidate["governance_artifact_count"] - baseline["governance_artifact_count"],
            "unexpected_new_files": len(candidate["unexpected_new_files"]) - len(baseline["unexpected_new_files"]),
        },
        "note": (
            "The fixture contains two unrelated active Task hints, 1000 archived Task references, and 100 keyword-similar "
            "Knowledge entries. PASS requires the V6 candidate to perform only the local rename with no Task, Change, "
            "Investigation, delegation, Memory recall, or extra plan artifact, and to add no more observable overhead than baseline."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V6 same-model LOW Fast Path A/B")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = subparsers.add_parser("prepare")
    prepare_cmd.add_argument("destination", type=Path)
    prepare_cmd.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    prepare_cmd.add_argument("--candidate-ref", default="HEAD")
    prepare_cmd.add_argument("--model-label", required=True)
    prepare_cmd.add_argument("--force", action="store_true")
    score_cmd = subparsers.add_parser("score")
    score_cmd.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            value = prepare(
                args.destination,
                baseline_ref=args.baseline_ref,
                candidate_ref=args.candidate_ref,
                model_label=args.model_label,
                force=args.force,
            )
        else:
            value = score(args.root)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
