from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from production_snapshot import production_snapshot_sha256
from project_context import ProjectContext
from reference_resolver import resolve_change_ref
from review_transaction import atomic_write_yaml
from work_graph import now_iso


READINESS_STATUSES = {"pending", "pass", "fail", "stale"}
ASSURANCE_CLASSES = {"standard", "behavioral", "numerical"}
CRITERION_KINDS = {
    "build",
    "focused-test",
    "integration",
    "representative-case",
    "benchmark",
    "analytical-check",
    "invariant",
    "other",
}
RESULTS = {"pass", "fail"}
EXTERNAL_BEHAVIOR_KINDS = {"integration", "representative-case", "benchmark", "analytical-check"}
NUMERICAL_KINDS = {"representative-case", "benchmark", "analytical-check"}
FREEZE_STATUSES = {"proposed", "designed", "approved"}


class ReadinessError(ValueError):
    pass


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ReadinessError(f"expected YAML mapping: {path}")
    return data


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_readiness_contract(data: dict) -> None:
    if data.get("candidate_readiness_protocol") != 1:
        return
    readiness = data.get("readiness")
    if not isinstance(readiness, dict):
        raise ReadinessError("readiness must be a mapping for candidate_readiness_protocol 1")
    assurance = str(readiness.get("assurance_class") or "")
    if assurance not in ASSURANCE_CLASSES:
        raise ReadinessError(f"invalid readiness.assurance_class: {assurance}")
    status = str(readiness.get("status") or "pending")
    if status not in READINESS_STATUSES:
        raise ReadinessError(f"invalid readiness.status: {status}")
    criteria = readiness.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ReadinessError("readiness.criteria must contain at least one criterion")
    ids: set[str] = set()
    kinds: set[str] = set()
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise ReadinessError(f"readiness.criteria[{index}] must be a mapping")
        criterion_id = str(criterion.get("id") or "").strip()
        kind = str(criterion.get("kind") or "").strip()
        description = str(criterion.get("description") or "").strip()
        if not criterion_id or not description:
            raise ReadinessError(f"readiness.criteria[{index}] requires id and description")
        if criterion_id in ids:
            raise ReadinessError(f"duplicate readiness criterion id: {criterion_id}")
        if kind not in CRITERION_KINDS:
            raise ReadinessError(f"invalid readiness criterion kind: {kind}")
        if not isinstance(criterion.get("required", True), bool):
            raise ReadinessError(f"readiness.criteria[{index}].required must be boolean")
        ids.add(criterion_id)
        kinds.add(kind)
    if assurance == "behavioral" and not (kinds & EXTERNAL_BEHAVIOR_KINDS):
        raise ReadinessError("behavioral readiness requires integration or representative external-behavior evidence")
    if assurance == "numerical" and not (kinds & NUMERICAL_KINDS):
        raise ReadinessError("numerical readiness requires representative-case, benchmark, or analytical-check evidence")
    results = readiness.get("latest_results") or []
    if not isinstance(results, list):
        raise ReadinessError("readiness.latest_results must be a list")
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ReadinessError(f"readiness.latest_results[{index}] must be a mapping")
        if str(result.get("criterion_id") or "") not in ids:
            raise ReadinessError(f"readiness result references unknown criterion: {result.get('criterion_id')}")
        if str(result.get("result") or "") not in RESULTS:
            raise ReadinessError(f"invalid readiness result: {result.get('result')}")
        for key in ("command_or_entry", "checked_at", "evidence", "production_snapshot_sha256"):
            if not str(result.get(key) or "").strip():
                raise ReadinessError(f"readiness.latest_results[{index}].{key} is required")


def readiness_contract_digest(data: dict) -> str:
    readiness = data.get("readiness") or {}
    return _digest({
        "assurance_class": readiness.get("assurance_class"),
        "criteria": readiness.get("criteria") or [],
    })


def readiness_evidence_digest(data: dict) -> str:
    readiness = data.get("readiness") or {}
    return _digest(readiness.get("latest_results") or [])


def _require_frozen_contract(data: dict) -> str:
    readiness = data.get("readiness") or {}
    expected = str(readiness.get("contract_sha256") or "").strip()
    if not expected:
        raise ReadinessError("Readiness Contract is not frozen; run freeze-readiness before implementation evidence")
    actual = readiness_contract_digest(data)
    if expected != actual:
        raise ReadinessError("Readiness Contract changed after it was frozen")
    return expected


def freeze_readiness_contract(context: ProjectContext, change_value: str | Path) -> str:
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    protocol = data.get("candidate_readiness_protocol")
    if protocol not in {None, 1}:
        raise ReadinessError("unsupported candidate_readiness_protocol")
    status = str(data.get("status") or "")
    if status not in FREEZE_STATUSES:
        raise ReadinessError("Readiness Contract must be frozen before implementation begins")
    data["candidate_readiness_protocol"] = 1
    validate_readiness_contract(data)
    readiness = data["readiness"]
    digest = readiness_contract_digest(data)
    existing = str(readiness.get("contract_sha256") or "").strip()
    if existing and existing != digest:
        raise ReadinessError("Readiness Contract already has a different frozen digest")
    readiness["contract_sha256"] = digest
    if not str(readiness.get("frozen_at") or "").strip():
        readiness["frozen_at"] = now_iso()
    atomic_write_yaml(ref.yaml_path, data)
    return digest


def record_readiness(
    context: ProjectContext,
    change_value: str | Path,
    *,
    criterion_id: str,
    result: str,
    command_or_entry: str,
    evidence: str,
    observed: str | None = None,
) -> None:
    if result not in RESULTS:
        raise ReadinessError("readiness result must be pass or fail")
    if not command_or_entry.strip() or not evidence.strip():
        raise ReadinessError("command_or_entry and evidence are required")
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    validate_readiness_contract(data)
    if data.get("candidate_readiness_protocol") != 1:
        raise ReadinessError("Change does not use candidate_readiness_protocol 1")
    _require_frozen_contract(data)
    readiness = data["readiness"]
    criteria = {str(item["id"]): item for item in readiness["criteria"]}
    if criterion_id not in criteria:
        raise ReadinessError(f"unknown readiness criterion: {criterion_id}")
    snapshot = production_snapshot_sha256(context.project_root)
    entry = {
        "criterion_id": criterion_id,
        "result": result,
        "command_or_entry": command_or_entry.strip(),
        "observed": observed.strip() if isinstance(observed, str) and observed.strip() else None,
        "checked_at": now_iso(),
        "evidence": evidence.strip(),
        "production_snapshot_sha256": snapshot,
    }
    previous = [
        item for item in readiness.get("latest_results") or []
        if str(item.get("criterion_id") or "") != criterion_id
    ]
    readiness["latest_results"] = [*previous, entry]
    readiness["status"] = "pending" if result == "pass" else "fail"
    readiness["evidence_sha256"] = readiness_evidence_digest(data)
    readiness["production_snapshot"] = {"sha256": snapshot, "captured_at": now_iso()}
    readiness["achieved_at"] = None
    completion = data.setdefault("completion", {})
    completion["implementation_complete"] = False
    completion["ready_for_user_review"] = False
    atomic_write_yaml(ref.yaml_path, data)


def finalize_readiness(context: ProjectContext, change_value: str | Path) -> dict:
    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    validate_readiness_contract(data)
    if data.get("candidate_readiness_protocol") != 1:
        raise ReadinessError("Change does not use candidate_readiness_protocol 1")
    _require_frozen_contract(data)
    readiness = data["readiness"]
    current_snapshot = production_snapshot_sha256(context.project_root)
    results = {str(item.get("criterion_id")): item for item in readiness.get("latest_results") or []}
    missing: list[str] = []
    stale: list[str] = []
    failed: list[str] = []
    for criterion in readiness["criteria"]:
        if not criterion.get("required", True):
            continue
        criterion_id = str(criterion["id"])
        item = results.get(criterion_id)
        if item is None:
            missing.append(criterion_id)
            continue
        if item.get("production_snapshot_sha256") != current_snapshot:
            stale.append(criterion_id)
        if item.get("result") != "pass":
            failed.append(criterion_id)
    if missing or stale or failed:
        readiness["status"] = "stale" if stale else "fail" if failed else "pending"
        atomic_write_yaml(ref.yaml_path, data)
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if stale:
            parts.append("stale: " + ", ".join(stale))
        if failed:
            parts.append("failed: " + ", ".join(failed))
        raise ReadinessError("Candidate Readiness incomplete; " + "; ".join(parts))
    readiness["status"] = "pass"
    readiness["evidence_sha256"] = readiness_evidence_digest(data)
    readiness["production_snapshot"] = {"sha256": current_snapshot, "captured_at": now_iso()}
    readiness["achieved_at"] = now_iso()
    completion = data.setdefault("completion", {})
    completion["implementation_complete"] = True
    completion["ready_for_user_review"] = False
    atomic_write_yaml(ref.yaml_path, data)
    return {
        "status": "pass",
        "production_snapshot_sha256": current_snapshot,
        "criteria": sorted(results),
    }
