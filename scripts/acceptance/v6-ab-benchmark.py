from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml


HARNESS_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE_REF = "f179c2ece4f5e428bfcd33d375c67f87a289e6cb"
RESULT_REF = Path(".v6-benchmark/result.json")
PROMPT_REF = Path(".v6-benchmark/PROMPT.md")
CONTROL_NAME = "control.json"
EXPLORATION_ROLES = {"source_locator", "context_scout", "test_scout", "framework_scout"}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


_FIXTURE_PATH = HARNESS_ROOT / "scripts" / "acceptance" / "context-coverage-fixture.py"
_SPEC = importlib.util.spec_from_file_location("v6_context_coverage_fixture", _FIXTURE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load context coverage fixture: {_FIXTURE_PATH}")
FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(FIXTURE)


# Acceptance must independently reject a child that semantically asks for more
# context even if a runtime bug incorrectly placed it in delegation.completed.
# Keep this parser independent from runtime/delegate_once.py so the scorer does
# not reproduce the same inference bug it is supposed to detect.
_ACCEPTANCE_NEED_CONTEXT = re.compile(
    r"(?mi)^\s*(?:#{1,6}\s*)?(?:\*\*|__|\*|_)?NEED_CONTEXT(?=(?:\*\*|__|\*|_)?(?:\s|$|[:\-]))"
)
_ACCEPTANCE_NEED_CONTEXT_STATUS = re.compile(
    r"""(?mix)
    ^\s*
    (?:[-*+]\s*)?
    \{?\s*
    (?:\*\*|__|\*|_)?
    ["'`]?
    status
    ["'`]?
    (?:\*\*|__|\*|_)?
    \s*[:=]\s*
    (?:\*\*|__|\*|_)?
    ["'`]?
    NEED_CONTEXT
    ["'`]?
    (?:\*\*|__|\*|_)?
    \s*
    [,;]?
    \s*
    \}?
    \s*$
    """
)


def _acceptance_reports_need_context(text: str) -> bool:
    return bool(
        _ACCEPTANCE_NEED_CONTEXT.search(text)
        or _ACCEPTANCE_NEED_CONTEXT_STATUS.search(text)
    )


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(command)}\n{message}")
    return result


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _safe_destination(destination: Path, force: bool) -> Path:
    path = destination.expanduser().resolve()
    if path.exists():
        if not force:
            raise RuntimeError(f"destination already exists: {path}; use --force to replace it")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _materialize_ref(ref: str, destination: Path) -> str:
    resolved = _run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=HARNESS_ROOT,
        check=False,
    )
    if resolved.returncode:
        raise RuntimeError(
            f"Harness ref is not available locally: {ref}. Fetch repository history before preparing the A/B run."
        )
    sha = resolved.stdout.strip()
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / f".{destination.name}-{sha[:12]}.zip"
    _run(
        ["git", "archive", "--format=zip", "--output", str(archive), sha],
        cwd=HARNESS_ROOT,
    )
    destination.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
    finally:
        archive.unlink(missing_ok=True)
    return sha


def _write_fixture(project: Path) -> str:
    for relative, content in FIXTURE.FILES.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return _fixture_hash(project)


def _fixture_hash(project: Path) -> str:
    digest = hashlib.sha256()
    for relative in sorted(FIXTURE.FILES):
        path = project / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_init_fixture(project: Path) -> str:
    _run(["git", "init"], cwd=project)
    _run(["git", "config", "user.email", "v6-ab@example.invalid"], cwd=project)
    _run(["git", "config", "user.name", "V6 A B Fixture"], cwd=project)
    _run(["git", "add", "-A"], cwd=project)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2000-01-01T00:00:00Z"
    env["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00Z"
    _run(["git", "commit", "-m", "V6 C1 context coverage fixture"], cwd=project, env=env)
    return _run(["git", "rev-parse", "HEAD"], cwd=project).stdout.strip()


def _install(harness_source: Path, project: Path) -> None:
    _run(
        [
            sys.executable,
            str(harness_source / "install.py"),
            "--project",
            str(project),
        ],
        cwd=harness_source,
    )


def _prompt_text(model_label: str) -> str:
    return f"""# C1 Context Coverage A/B run

Run control: use the same parent model/configuration for both A and B. The declared control label is `{model_label}`.

The incremental negative-value case returns 2 but the expected result is 8. Investigate the root cause before proposing any production change. The visible symptom is in the solver, but do not assume the solver owns the defect.

Follow the Harness installed in this project exactly as it applies to this request. This is an investigation-only benchmark: do not modify production source files. Do not inspect any sibling A/B project or benchmark controller outside this project.

At the end, write `.v6-benchmark/result.json` with exactly this JSON shape:

```json
{{
  "schema_version": 1,
  "parent_model_label": "{model_label}",
  "selected_files": ["project-relative files that materially informed the final root-cause reasoning"],
  "root_cause_files": ["project-relative files you believe actually own the defect"],
  "conclusion_before_independent_exploration": false,
  "independent_exploration_completed": false,
  "governed_task_id": null,
  "summary": "compact root-cause conclusion"
}}
```

`selected_files` is not a dump of every file opened: list the context that materially informed the conclusion. Report independent exploration truthfully; the scorer cross-checks it against recorded Harness delegation state and re-validates runtime attestation instead of trusting this field alone.
"""


def _prepare_side(root: Path, name: str, harness_source: Path, prompt: bytes) -> dict:
    side = root / name
    project = side / "project"
    project.mkdir(parents=True)
    fixture_hash = _write_fixture(project)
    fixture_commit = _git_init_fixture(project)
    _install(harness_source, project)
    prompt_path = project / PROMPT_REF
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_bytes(prompt)
    return {
        "project": str(project),
        "harness_source": str(harness_source),
        "fixture_sha256": fixture_hash,
        "fixture_commit": fixture_commit,
        "prompt_sha256": _sha256_bytes(prompt),
        "prompt": str(prompt_path),
        "result": str(project / RESULT_REF),
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
        raise RuntimeError("--model-label is required so the same-model control is explicit")
    root = _safe_destination(destination, force)
    sources = root / "harness-snapshots"
    baseline_source = sources / "baseline"
    candidate_source = sources / "candidate"
    baseline_sha = _materialize_ref(baseline_ref, baseline_source)
    candidate_sha = _materialize_ref(candidate_ref, candidate_source)

    prompt = _prompt_text(model_label.strip()).encode("utf-8")
    baseline = _prepare_side(root, "baseline", baseline_source, prompt)
    candidate = _prepare_side(root, "candidate", candidate_source, prompt)
    if baseline["fixture_sha256"] != candidate["fixture_sha256"]:
        raise RuntimeError("A/B fixture content differs before model execution")
    if baseline["prompt_sha256"] != candidate["prompt_sha256"]:
        raise RuntimeError("A/B prompts differ before model execution")

    control = {
        "schema_version": 1,
        "baseline_ref": baseline_ref,
        "baseline_sha": baseline_sha,
        "candidate_ref": candidate_ref,
        "candidate_sha": candidate_sha,
        "model_label": model_label.strip(),
        "fixture_sha256": baseline["fixture_sha256"],
        "prompt_sha256": baseline["prompt_sha256"],
        "oracle": FIXTURE.manifest(),
        "baseline": baseline,
        "candidate": candidate,
    }
    (root / CONTROL_NAME).write_text(
        json.dumps(control, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "PREPARED_NOT_RUN",
        "root": str(root),
        "baseline_project": baseline["project"],
        "candidate_project": candidate["project"],
        "prompt_sha256": control["prompt_sha256"],
        "fixture_sha256": control["fixture_sha256"],
        "model_label": control["model_label"],
        "next": (
            "Launch two genuinely fresh Codex sessions, one from each project, with the same model/configuration. "
            "Give each the local .v6-benchmark/PROMPT.md. Do not use resume/fork. After both result.json files exist, run score."
        ),
    }


def _load_result(project: Path) -> dict:
    path = project / RESULT_REF
    if not path.is_file():
        raise RuntimeError(f"missing model result: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError(f"invalid model result: {path}")
    return value


def _task_roots(project: Path) -> list[Path]:
    root = project / ".agent-work"
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_") and (path / "task.yaml").is_file()
    )


def _validate_completed_attestation(project: Path, completed: dict) -> tuple[bool, dict]:
    request_ref = str((completed.get("context") or {}).get("request_ref") or "")
    record_ref = str(completed.get("record_ref") or "")
    completed_output_ref = str(completed.get("output_ref") or "")
    if not request_ref or not record_ref:
        return False, {"error": "completed exploration lacks request_ref or record_ref"}
    request = project / request_ref
    record = project / record_ref
    runtime = project / ".harness" / "sitter" / "runtime"
    if not request.is_file() or not record.is_file() or not runtime.is_dir():
        return False, {"error": "exploration request/record/runtime is missing"}

    try:
        record_data = yaml.safe_load(record.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "error": f"cannot read exploration record: {error}",
        }
    if not isinstance(record_data, dict):
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "error": "exploration record is not a mapping",
        }
    if str(record_data.get("outcome") or "") != "completed":
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "recorded_outcome": record_data.get("outcome"),
            "error": "exploration record outcome is not completed",
        }
    requested_outcome = str(record_data.get("requested_outcome") or "")
    if requested_outcome and requested_outcome != "completed":
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "requested_outcome": requested_outcome,
            "error": "exploration requested_outcome is not completed",
        }
    if str(record_data.get("request_ref") or "") != request_ref:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "error": "exploration record request_ref does not match the completed entry",
        }

    output_ref = str(record_data.get("output_ref") or "")
    if not output_ref:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "error": "completed exploration record has no output_ref",
        }
    if completed_output_ref and completed_output_ref != output_ref:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "error": "exploration record output_ref does not match the completed entry",
        }
    output = (project / output_ref).resolve()
    try:
        output.relative_to(project.resolve())
    except ValueError:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "error": "exploration output_ref escapes the benchmark project",
        }
    if not output.is_file():
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "error": "completed exploration output is missing",
        }
    try:
        output_text = output.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "error": f"cannot read completed exploration output: {error}",
        }
    if _acceptance_reports_need_context(output_text):
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "recorded_outcome": "completed",
            "semantic_status": "need-context",
            "error": "exploration output reports NEED_CONTEXT and cannot count as completed independent exploration",
        }

    validator = r'''
import json
import sys
import yaml
sys.path.insert(0, sys.argv[1])
from provider_attestation import validate_provider_attestation
packet = yaml.safe_load(open(sys.argv[2], encoding="utf-8"))
record = yaml.safe_load(open(sys.argv[3], encoding="utf-8"))
attestation = record.get("attestation")
if not isinstance(attestation, dict):
    raise ValueError("record has no attestation")
evidence = validate_provider_attestation(packet, attestation)
print(json.dumps({
    "provider": evidence.provider,
    "role_id": evidence.role_id,
    "context_isolation": evidence.contract.context_isolation,
    "write_isolation": evidence.contract.write_isolation,
    "attestation_strength": evidence.contract.attestation_strength,
}))
'''
    result = _run(
        [
            sys.executable,
            "-c",
            validator,
            str(runtime),
            str(request),
            str(record),
        ],
        cwd=project,
        check=False,
    )
    if result.returncode:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "error": result.stderr.strip() or result.stdout.strip() or "attestation validation failed",
        }
    try:
        details = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "error": "attestation validator returned invalid JSON",
        }
    details.update(
        {
            "request_ref": request_ref,
            "record_ref": record_ref,
            "output_ref": output_ref,
            "recorded_outcome": "completed",
            "semantic_status": "completed",
        }
    )
    return True, details


def _exploration_requirement(task: dict) -> tuple[str, bool]:
    """Mirror the frozen G1 boundary without importing candidate runtime code.

    C1 is a context-quality benchmark, not a second risk router. A missing Scout
    is premature only when this recorded Task state actually makes G1 mandatory.
    Legacy Tasks without V6 work_risk have no such obligation.
    """

    work_risk = task.get("work_risk")
    if not isinstance(work_risk, dict):
        return "legacy", False
    current = work_risk.get("current")
    if not isinstance(current, dict):
        return "invalid", True
    semantic = str(current.get("semantic") or "").strip().lower()
    repository = str(current.get("repository_change") or "").strip().lower()
    if semantic not in RISK_ORDER or repository not in RISK_ORDER:
        return "invalid", True
    maximum = max(RISK_ORDER[semantic], RISK_ORDER[repository])
    label = max((semantic, repository), key=lambda value: RISK_ORDER[value])
    return label, maximum >= RISK_ORDER["high"]


def _actual_exploration(project: Path) -> dict:
    roles: set[str] = set()
    completed_ids: set[str] = set()
    task_ids: list[str] = []
    attested: list[dict] = []
    rejected: list[dict] = []
    governed_final_truth_without_exploration = False
    exploration_required_task_ids: list[str] = []
    task_risks: dict[str, dict] = {}
    for task_root in _task_roots(project):
        task = yaml.safe_load((task_root / "task.yaml").read_text(encoding="utf-8"))
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task_root.name)
        task_ids.append(task_id)
        risk_label, exploration_required = _exploration_requirement(task)
        task_risks[task_id] = {
            "current": risk_label,
            "g1_exploration_required": exploration_required,
        }
        if exploration_required:
            exploration_required_task_ids.append(task_id)

        delegation = task.get("delegation") or {}
        completed_entries = {
            str(item.get("id")): item
            for item in delegation.get("completed") or []
            if isinstance(item, dict) and item.get("id")
        }
        planned = {
            str(item.get("id")): str(item.get("agent") or "")
            for item in delegation.get("planned") or []
            if isinstance(item, dict) and item.get("id")
        }
        task_valid_ids: set[str] = set()
        for delegation_id, completed in completed_entries.items():
            role = planned.get(delegation_id, "")
            if role not in EXPLORATION_ROLES:
                continue
            valid, evidence = _validate_completed_attestation(project, completed)
            row = {
                "task_id": task_id,
                "delegation_id": delegation_id,
                "role": role,
                **evidence,
            }
            if valid:
                task_valid_ids.add(delegation_id)
                completed_ids.add(delegation_id)
                roles.add(role)
                attested.append(row)
            else:
                rejected.append(row)

        has_final_truth = False
        investigations = task_root / "investigations"
        if investigations.is_dir():
            for inv in investigations.glob("*.yaml"):
                data = yaml.safe_load(inv.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                accepted = any(
                    item.get("status") == "accepted"
                    for item in (data.get("decisions") or [])
                    if isinstance(item, dict)
                )
                concluded = data.get("status") in {"concluded", "closed"}
                if accepted or concluded:
                    has_final_truth = True
        if has_final_truth and exploration_required and not task_valid_ids:
            governed_final_truth_without_exploration = True

    return {
        "completed": bool(completed_ids),
        "delegation_ids": sorted(completed_ids),
        "roles": sorted(roles),
        "task_ids": task_ids,
        "attested": attested,
        "rejected_unattested": rejected,
        "exploration_required_task_ids": sorted(exploration_required_task_ids),
        "task_risks": task_risks,
        "governed_final_truth_without_exploration": governed_final_truth_without_exploration,
    }


def _mentioned_fixture_files(project: Path, result: dict) -> set[str]:
    selected = {
        str(value).replace("\\", "/")
        for value in result.get("selected_files") or []
        if isinstance(value, str)
    }
    texts = [json.dumps(result, ensure_ascii=False)]
    for task_root in _task_roots(project):
        for pattern in ("delegations/**/attempt-*.result.md", "investigations/*.md"):
            for path in task_root.glob(pattern):
                if path.is_file():
                    try:
                        texts.append(path.read_text(encoding="utf-8"))
                    except UnicodeError:
                        continue
    corpus = "\n".join(texts).replace("\\", "/")
    for relative in FIXTURE.FILES:
        if relative in corpus:
            selected.add(relative)
    return selected


def _score_side(project: Path, expected_model_label: str) -> dict:
    result = _load_result(project)
    actual = _actual_exploration(project)
    selected = sorted(_mentioned_fixture_files(project, result))
    premature = bool(result.get("conclusion_before_independent_exploration", False))
    if actual["governed_final_truth_without_exploration"]:
        premature = True
    normalized = dict(result)
    normalized["selected_files"] = selected
    normalized["independent_exploration_completed"] = actual["completed"]
    normalized["conclusion_before_independent_exploration"] = premature
    score = FIXTURE.score_result(normalized)
    root_cause = {
        str(value).replace("\\", "/")
        for value in result.get("root_cause_files") or []
        if isinstance(value, str)
    }
    expected_root = set(FIXTURE.manifest()["expected_root_cause"])
    score.update(
        {
            "root_cause_correct": expected_root.issubset(root_cause),
            "root_cause_reported": sorted(root_cause),
            "actual_exploration": actual,
            "model_label_matches_control": result.get("parent_model_label") == expected_model_label,
            "selected_files_verified_union": selected,
        }
    )
    score["meets_v6_target"] = bool(
        score["meets_v6_target"]
        and score["root_cause_correct"]
        and score["model_label_matches_control"]
    )
    return score


def score(root: Path) -> dict:
    root = root.expanduser().resolve()
    control = json.loads((root / CONTROL_NAME).read_text(encoding="utf-8"))
    baseline_project = Path(control["baseline"]["project"]).resolve()
    candidate_project = Path(control["candidate"]["project"]).resolve()

    current_controls = {
        "baseline_fixture_sha256": _fixture_hash(baseline_project),
        "candidate_fixture_sha256": _fixture_hash(candidate_project),
        "baseline_prompt_sha256": _sha256_file(baseline_project / PROMPT_REF),
        "candidate_prompt_sha256": _sha256_file(candidate_project / PROMPT_REF),
    }
    controls_valid = (
        current_controls["baseline_fixture_sha256"] == control["fixture_sha256"]
        and current_controls["candidate_fixture_sha256"] == control["fixture_sha256"]
        and current_controls["baseline_prompt_sha256"] == control["prompt_sha256"]
        and current_controls["candidate_prompt_sha256"] == control["prompt_sha256"]
    )

    baseline = _score_side(baseline_project, control["model_label"])
    candidate = _score_side(candidate_project, control["model_label"])
    recall_delta = candidate["required_context_recall"] - baseline["required_context_recall"]
    pollution_delta = candidate["context_pollution"] - baseline["context_pollution"]
    strict_improvement = bool(
        recall_delta > 0
        or pollution_delta < 0
        or (
            baseline["premature_convergence"]
            and not candidate["premature_convergence"]
        )
        or (
            not baseline["root_cause_correct"]
            and candidate["root_cause_correct"]
        )
    )
    baseline_at_ceiling = bool(
        baseline["required_context_recall"] == 1.0
        and baseline["context_pollution"] == 0.0
        and not baseline["premature_convergence"]
        and baseline["root_cause_correct"]
    )
    no_regression = bool(
        candidate["required_context_recall"] >= baseline["required_context_recall"]
        and candidate["context_pollution"] <= baseline["context_pollution"]
        and not candidate["premature_convergence"]
    )
    comparison_requirement_met = bool(strict_improvement or baseline_at_ceiling)
    if strict_improvement:
        comparison_mode = "strict-improvement"
    elif baseline_at_ceiling:
        comparison_mode = "non-regressive-at-ceiling"
    else:
        comparison_mode = "improvement-required"
    passed = bool(
        controls_valid
        and baseline["model_label_matches_control"]
        and candidate["model_label_matches_control"]
        and candidate["meets_v6_target"]
        and no_regression
        and comparison_requirement_met
    )
    return {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "baseline_ref": control["baseline_ref"],
        "baseline_sha": control["baseline_sha"],
        "candidate_ref": control["candidate_ref"],
        "candidate_sha": control["candidate_sha"],
        "model_label": control["model_label"],
        "controls_valid": controls_valid,
        "controls": current_controls,
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            "required_context_recall": recall_delta,
            "context_pollution": pollution_delta,
            "strict_improvement": strict_improvement,
            "baseline_at_ceiling": baseline_at_ceiling,
            "comparison_requirement_met": comparison_requirement_met,
            "comparison_mode": comparison_mode,
            "no_regression": no_regression,
        },
        "success_metrics": {
            "context_recall_up": recall_delta > 0,
            "context_pollution_down": pollution_delta < 0,
            "candidate_human_authority": "covered separately by H1/H2 deterministic + black-box cases",
            "fast_path_overhead": "covered separately by H3/P2 deterministic cases",
        },
        "note": (
            "C1 requires the candidate to meet its absolute target and avoid regression. A strict behavioral "
            "improvement is required only while the baseline still has measurable C1 headroom; when baseline "
            "already has recall=1, pollution=0, correct root cause, and no premature convergence, an equally "
            "correct candidate passes as non-regressive at ceiling. Independent exploration is reported but is "
            "not itself a C1 improvement signal; missing exploration is premature only when the recorded Task "
            "risk makes the separate G1 HIGH/CRITICAL gate mandatory. Any counted child must still be semantically "
            "completed, must not report NEED_CONTEXT, and must have a valid installed-Provider attestation."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V6 same-model same-snapshot C1 A/B benchmark")
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
