from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from project_context import ProjectContext


TASK_STATUSES = {"intake", "active", "blocked", "completed"}
FOCUS_TYPES = {"investigation", "change", "none"}
INVESTIGATION_STATUSES = {
    "intake", "investigating", "evidence-review", "concluded", "closed", "blocked"
}
INVESTIGATION_EXECUTION_STATES = {"active", "paused", "blocked"}
INVESTIGATION_DISPOSITIONS = {
    "pending",
    "no-change-required",
    "resume-change",
    "revise-change",
    "create-change",
    "supersede-change",
    "follow-up-investigation",
    "inconclusive",
}
CHANGE_EXECUTION_STATES = {"active", "paused", "abandoned"}
ESCALATION_LEVELS = {"none", "stronger-model", "human-checkpoint", "blocked"}
MODEL_REVIEW_STATUSES = {"not-required", "pending", "completed", "inconclusive", "blocked"}
HUMAN_CHECKPOINT_STATUSES = {"not-required", "pending", "resolved"}
CLAIM_STATUSES = {"open", "supported", "refuted", "inconclusive", "superseded"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
DECISION_STATUSES = {"proposed", "accepted", "rejected", "superseded"}
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")


class WorkGraphError(ValueError):
    pass


@dataclass(frozen=True)
class WorkGraph:
    task_root: Path
    task: dict
    investigations: dict[str, dict]
    changes: dict[str, tuple[Path, dict]]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise WorkGraphError(f"{label} must be a mapping")
    return value


def require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise WorkGraphError(f"{label} must be a list")
    return value


def non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkGraphError(f"{label} must be a non-empty string")
    return value.strip()


def valid_id(value: object, label: str) -> str:
    text = non_empty(value, label)
    if not ID_PATTERN.fullmatch(text):
        raise WorkGraphError(f"{label} must contain only lowercase letters, digits, and hyphens")
    return text


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise WorkGraphError(f"missing file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise WorkGraphError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(data, dict):
        raise WorkGraphError(f"expected YAML mapping: {path}")
    return data


def dump_yaml(data: dict) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def project_relative(context: ProjectContext, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.project_root).as_posix()
    except ValueError as error:
        raise WorkGraphError(f"path is outside project: {path}") from error


def resolve_task_root(context: ProjectContext, value: str | Path) -> Path:
    raw = Path(value)
    if raw.is_absolute() or len(raw.parts) > 1:
        candidates = [raw]
    else:
        candidates = [context.project_root / ".agent-work" / raw]
    for candidate in candidates:
        root = candidate.resolve()
        try:
            root.relative_to(context.project_root)
        except ValueError:
            continue
        if (root / "task.yaml").is_file():
            return root
    raise WorkGraphError(f"task not found: {value}")


def resolve_change_root(context: ProjectContext, value: str | Path) -> Path:
    raw = Path(value)
    candidates: list[Path]
    if raw.is_absolute() or len(raw.parts) > 1:
        candidates = [raw]
    else:
        candidates = [
            context.project_root / "changes" / "active" / raw,
            context.project_root / "changes" / "archive" / raw,
        ]
    for candidate in candidates:
        root = candidate.resolve()
        try:
            root.relative_to(context.project_root)
        except ValueError:
            continue
        if (root / "change.yaml").is_file():
            return root
    raise WorkGraphError(f"change not found: {value}")


def investigation_path(task_root: Path, investigation_id: str) -> Path:
    return task_root / "investigations" / f"{investigation_id}.yaml"


def investigation_markdown_path(task_root: Path, investigation_id: str) -> Path:
    return task_root / "investigations" / f"{investigation_id}.md"


def next_investigation_id(task: dict) -> str:
    values = ((task.get("work_items") or {}).get("investigations") or [])
    maximum = 0
    for value in values:
        match = re.fullmatch(r"inv-(\d+)", str(value))
        if match:
            maximum = max(maximum, int(match.group(1)))
    return f"inv-{maximum + 1:03d}"


def _change_root_for_id(context: ProjectContext, change_id: str) -> Path | None:
    for parent in ("active", "archive"):
        root = context.project_root / "changes" / parent / change_id
        if (root / "change.yaml").is_file():
            return root
    return None


def _unique_ids(entries: Iterable[dict], label: str) -> set[str]:
    ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise WorkGraphError(f"{label}[{index}] must be a mapping")
        entry_id = valid_id(entry.get("id"), f"{label}[{index}].id")
        if entry_id in ids:
            raise WorkGraphError(f"duplicate {label} id: {entry_id}")
        ids.add(entry_id)
    return ids


def validate_task_shape(data: dict) -> None:
    if data.get("schema_version") != 4:
        raise WorkGraphError("task schema_version must be 4")
    valid_id(data.get("id"), "task.id")
    non_empty(data.get("title"), "task.title")
    status = str(data.get("status", ""))
    if status not in TASK_STATUSES:
        raise WorkGraphError(f"invalid task status: {status}")

    focus = require_mapping(data.get("current_focus") or {}, "task.current_focus")
    focus_type = str(focus.get("type", "none"))
    if focus_type not in FOCUS_TYPES:
        raise WorkGraphError(f"invalid current focus type: {focus_type}")
    if focus_type == "none":
        if focus.get("ref") not in {None, ""}:
            raise WorkGraphError("current_focus.ref must be empty when type is none")
    else:
        valid_id(focus.get("ref"), "task.current_focus.ref")

    items = require_mapping(data.get("work_items") or {}, "task.work_items")
    investigations = require_list(items.get("investigations") or [], "task.work_items.investigations")
    changes = require_list(items.get("changes") or [], "task.work_items.changes")
    for label, values in (("investigation", investigations), ("change", changes)):
        normalized = [valid_id(value, f"task.work_items.{label}s") for value in values]
        if len(normalized) != len(set(normalized)):
            raise WorkGraphError(f"task work_items contains duplicate {label} ids")

    require_list(data.get("timeline") or [], "task.timeline")

    control = require_mapping(data.get("pivot_control") or {}, "task.pivot_control")
    automatic = require_mapping(
        control.get("automatic_investigations_from_change") or {},
        "task.pivot_control.automatic_investigations_from_change",
    )
    used = automatic.get("used", 0)
    limit = automatic.get("limit", 1)
    if not isinstance(used, int) or used < 0:
        raise WorkGraphError("automatic pivot used count must be a non-negative integer")
    if not isinstance(limit, int) or limit < 0:
        raise WorkGraphError("automatic pivot limit must be a non-negative integer")
    signatures = require_mapping(
        control.get("repeated_signatures") or {},
        "task.pivot_control.repeated_signatures",
    )
    for signature, record in signatures.items():
        valid_id(signature, "problem signature")
        mapping = require_mapping(record, f"signature record {signature}")
        occurrences = mapping.get("occurrences", 0)
        if not isinstance(occurrences, int) or occurrences < 1:
            raise WorkGraphError(f"signature {signature} occurrences must be positive")
        refs = require_list(mapping.get("investigations") or [], f"signature {signature} investigations")
        for ref in refs:
            valid_id(ref, f"signature {signature} investigation ref")

    escalation = require_mapping(data.get("escalation") or {}, "task.escalation")
    level = str(escalation.get("level", "none"))
    if level not in ESCALATION_LEVELS:
        raise WorkGraphError(f"invalid escalation level: {level}")
    require_list(escalation.get("related_refs") or [], "task.escalation.related_refs")
    model = require_mapping(escalation.get("model_review") or {}, "task.escalation.model_review")
    model_status = str(model.get("status", "not-required"))
    if model_status not in MODEL_REVIEW_STATUSES:
        raise WorkGraphError(f"invalid model review status: {model_status}")
    human = require_mapping(
        escalation.get("human_checkpoint") or {},
        "task.escalation.human_checkpoint",
    )
    human_status = str(human.get("status", "not-required"))
    if human_status not in HUMAN_CHECKPOINT_STATUSES:
        raise WorkGraphError(f"invalid human checkpoint status: {human_status}")

    if level == "stronger-model":
        if not bool(model.get("required", False)) or model_status not in {"pending", "completed"}:
            raise WorkGraphError("stronger-model escalation requires a pending or completed model review")
    if level in {"human-checkpoint", "blocked"}:
        if not bool(human.get("required", False)) or human_status not in {"pending", "resolved"}:
            raise WorkGraphError("human escalation requires a pending or resolved human checkpoint")
    if human_status == "pending" and status != "blocked":
        raise WorkGraphError("task must be blocked while a human checkpoint is pending")


def validate_investigation_shape(data: dict) -> None:
    if data.get("schema_version") != 1:
        raise WorkGraphError("investigation schema_version must be 1")
    valid_id(data.get("id"), "investigation.id")
    valid_id(data.get("task_id"), "investigation.task_id")
    non_empty(data.get("title"), "investigation.title")
    status = str(data.get("status", ""))
    if status not in INVESTIGATION_STATUSES:
        raise WorkGraphError(f"invalid investigation status: {status}")
    execution = str(data.get("execution_state", ""))
    if execution not in INVESTIGATION_EXECUTION_STATES:
        raise WorkGraphError(f"invalid investigation execution_state: {execution}")

    source = require_mapping(data.get("source") or {}, "investigation.source")
    source_type = str(source.get("type", ""))
    if source_type not in {"task", "change", "investigation"}:
        raise WorkGraphError(f"invalid investigation source type: {source_type}")
    valid_id(source.get("ref"), "investigation.source.ref")

    problem = require_mapping(data.get("problem") or {}, "investigation.problem")
    non_empty(problem.get("question"), "investigation.problem.question")
    valid_id(problem.get("signature"), "investigation.problem.signature")
    require_mapping(problem.get("scope") or {}, "investigation.problem.scope")

    claims = require_list(data.get("claims") or [], "investigation.claims")
    evidence = require_list(data.get("evidence") or [], "investigation.evidence")
    experiments = require_list(data.get("experiments") or [], "investigation.experiments")
    decisions = require_list(data.get("decisions") or [], "investigation.decisions")
    claim_ids = _unique_ids(claims, "investigation.claims")
    evidence_ids = _unique_ids(evidence, "investigation.evidence")
    _unique_ids(experiments, "investigation.experiments")
    decision_ids = _unique_ids(decisions, "investigation.decisions")

    for claim in claims:
        claim_status = str(claim.get("status", "open"))
        if claim_status not in CLAIM_STATUSES:
            raise WorkGraphError(f"invalid claim status: {claim_status}")
        confidence = str(claim.get("confidence", "low"))
        if confidence not in CONFIDENCE_LEVELS:
            raise WorkGraphError(f"invalid claim confidence: {confidence}")
        non_empty(claim.get("statement"), "claim.statement")
        supporting = require_list(claim.get("supporting_evidence") or [], "claim.supporting_evidence")
        contradicting = require_list(
            claim.get("contradicting_evidence") or [], "claim.contradicting_evidence"
        )
        unknown = (set(map(str, supporting)) | set(map(str, contradicting))) - evidence_ids
        if unknown:
            raise WorkGraphError("claim references unknown evidence: " + ", ".join(sorted(unknown)))
        if claim_status in {"supported", "refuted"} and not supporting and not contradicting:
            raise WorkGraphError(f"claim {claim['id']} requires evidence for status {claim_status}")

    for item in evidence:
        non_empty(item.get("kind"), "evidence.kind")
        non_empty(item.get("source_ref"), "evidence.source_ref")
        non_empty(item.get("provenance"), "evidence.provenance")
        supports = require_list(item.get("supports") or [], "evidence.supports")
        contradicts = require_list(item.get("contradicts") or [], "evidence.contradicts")
        unknown = (set(map(str, supports)) | set(map(str, contradicts))) - claim_ids
        if unknown:
            raise WorkGraphError("evidence references unknown claims: " + ", ".join(sorted(unknown)))

    for decision in decisions:
        non_empty(decision.get("statement"), "decision.statement")
        decision_status = str(decision.get("status", "proposed"))
        if decision_status not in DECISION_STATUSES:
            raise WorkGraphError(f"invalid decision status: {decision_status}")
        basis = require_mapping(decision.get("basis") or {}, "decision.basis")
        basis_claims = set(map(str, require_list(basis.get("claims") or [], "decision.basis.claims")))
        basis_evidence = set(
            map(str, require_list(basis.get("evidence") or [], "decision.basis.evidence"))
        )
        if basis_claims - claim_ids:
            raise WorkGraphError("decision references unknown claims")
        if basis_evidence - evidence_ids:
            raise WorkGraphError("decision references unknown evidence")
        if decision_status == "accepted" and not basis_claims and not basis_evidence:
            raise WorkGraphError(f"accepted decision {decision['id']} requires evidence or claims")

    require_list(data.get("remaining_unknowns") or [], "investigation.remaining_unknowns")
    gain = require_mapping(data.get("discrimination_gain") or {}, "investigation.discrimination_gain")
    for key in ("new_data_sources", "new_experiments", "new_observability"):
        require_list(gain.get(key) or [], f"investigation.discrimination_gain.{key}")

    disposition = require_mapping(data.get("disposition") or {}, "investigation.disposition")
    disposition_type = str(disposition.get("type", "pending"))
    if disposition_type not in INVESTIGATION_DISPOSITIONS:
        raise WorkGraphError(f"invalid investigation disposition: {disposition_type}")
    if status in {"concluded", "closed"}:
        if disposition_type == "pending":
            raise WorkGraphError("concluded investigation requires a disposition")
        non_empty(disposition.get("rationale"), "investigation.disposition.rationale")
        if disposition_type in {"resume-change", "revise-change", "create-change", "supersede-change"}:
            valid_id(disposition.get("target"), "investigation.disposition.target")
            accepted = [item for item in decisions if item.get("status") == "accepted"]
            if not accepted:
                raise WorkGraphError("actionable investigation disposition requires an accepted decision")
        if disposition_type == "inconclusive" and not data.get("remaining_unknowns"):
            raise WorkGraphError("inconclusive investigation must record remaining_unknowns")

    if len(decision_ids) != len(decisions):
        raise WorkGraphError("duplicate investigation decision ids")


def validate_change_graph_shape(data: dict) -> None:
    if data.get("schema_version") != 4:
        raise WorkGraphError("change schema_version must be 4")
    valid_id(data.get("id"), "change.id")
    valid_id(data.get("task_id"), "change.task_id")
    execution = str(data.get("execution_state", ""))
    if execution not in CHANGE_EXECUTION_STATES:
        raise WorkGraphError(f"invalid change execution_state: {execution}")
    hold = require_mapping(data.get("hold") or {}, "change.hold")
    if execution == "paused":
        non_empty(hold.get("reason"), "change.hold.reason")
        valid_id(hold.get("investigation_ref"), "change.hold.investigation_ref")
    relations = require_mapping(data.get("relations") or {}, "change.relations")
    derived = require_mapping(relations.get("derived_from") or {}, "change.relations.derived_from")
    produced = require_mapping(relations.get("produced") or {}, "change.relations.produced")
    for label, mapping, keys in (
        ("derived_from", derived, ("investigations", "claims", "decisions", "evidence")),
        ("produced", produced, ("investigations", "evidence")),
    ):
        for key in keys:
            require_list(mapping.get(key) or [], f"change.relations.{label}.{key}")
    require_list(relations.get("supersedes") or [], "change.relations.supersedes")
    superseded_by = relations.get("superseded_by")
    if superseded_by not in {None, ""}:
        valid_id(superseded_by, "change.relations.superseded_by")
    require_list(data.get("resume_history") or [], "change.resume_history")
    require_list(data.get("revision_history") or [], "change.revision_history")


def load_work_graph(context: ProjectContext, task_root: Path) -> WorkGraph:
    task = load_yaml(task_root / "task.yaml")
    validate_task_shape(task)
    task_id = str(task["id"])

    investigations: dict[str, dict] = {}
    for investigation_id in (task.get("work_items") or {}).get("investigations") or []:
        path = investigation_path(task_root, str(investigation_id))
        data = load_yaml(path)
        validate_investigation_shape(data)
        if data.get("task_id") != task_id:
            raise WorkGraphError(f"investigation {investigation_id} belongs to another task")
        if data.get("id") != investigation_id:
            raise WorkGraphError(f"investigation id does not match file registration: {investigation_id}")
        investigations[str(investigation_id)] = data

    changes: dict[str, tuple[Path, dict]] = {}
    for change_id in (task.get("work_items") or {}).get("changes") or []:
        root = _change_root_for_id(context, str(change_id))
        if root is None:
            raise WorkGraphError(f"registered change not found: {change_id}")
        data = load_yaml(root / "change.yaml")
        validate_change_graph_shape(data)
        if data.get("task_id") != task_id:
            raise WorkGraphError(f"change {change_id} belongs to another task")
        if data.get("id") != change_id:
            raise WorkGraphError(f"change id does not match registration: {change_id}")
        changes[str(change_id)] = (root, data)

    return WorkGraph(task_root=task_root, task=task, investigations=investigations, changes=changes)


def validate_work_graph(context: ProjectContext, task_root: Path) -> WorkGraph:
    graph = load_work_graph(context, task_root)
    task = graph.task
    focus = task["current_focus"]
    focus_type = focus["type"]
    focus_ref = focus.get("ref")
    if focus_type == "investigation" and focus_ref not in graph.investigations:
        raise WorkGraphError(f"current investigation focus does not exist: {focus_ref}")
    if focus_type == "change" and focus_ref not in graph.changes:
        raise WorkGraphError(f"current change focus does not exist: {focus_ref}")

    signatures: dict[str, list[str]] = {}
    active_by_signature: dict[str, list[str]] = {}
    for investigation_id, data in graph.investigations.items():
        signature = str((data.get("problem") or {}).get("signature"))
        signatures.setdefault(signature, []).append(investigation_id)
        if data.get("status") not in {"closed", "concluded"} and data.get("execution_state") == "active":
            active_by_signature.setdefault(signature, []).append(investigation_id)
        source = data.get("source") or {}
        if source.get("type") == "change" and source.get("ref") not in graph.changes:
            raise WorkGraphError(
                f"investigation {investigation_id} references unknown source change {source.get('ref')}"
            )
        if source.get("type") == "investigation" and source.get("ref") not in graph.investigations:
            raise WorkGraphError(
                f"investigation {investigation_id} references unknown source investigation {source.get('ref')}"
            )
        disposition = data.get("disposition") or {}
        if disposition.get("type") in {"resume-change", "revise-change", "create-change", "supersede-change"}:
            target = disposition.get("target")
            if target not in graph.changes:
                raise WorkGraphError(
                    f"investigation {investigation_id} disposition references unknown change {target}"
                )

    duplicates = {signature: refs for signature, refs in active_by_signature.items() if len(refs) > 1}
    if duplicates:
        details = "; ".join(f"{key}: {', '.join(value)}" for key, value in duplicates.items())
        raise WorkGraphError(f"multiple active investigations share a problem signature: {details}")

    registered_signatures = (
        (task.get("pivot_control") or {}).get("repeated_signatures") or {}
    )
    for signature, refs in signatures.items():
        record = registered_signatures.get(signature)
        if not isinstance(record, dict):
            raise WorkGraphError(f"task has no signature registry entry for {signature}")
        if int(record.get("occurrences", 0)) != len(refs):
            raise WorkGraphError(f"signature occurrence count is stale: {signature}")
        if set(map(str, record.get("investigations") or [])) != set(refs):
            raise WorkGraphError(f"signature investigation registry is stale: {signature}")

    for change_id, (_, data) in graph.changes.items():
        if data.get("execution_state") == "paused":
            investigation_ref = (data.get("hold") or {}).get("investigation_ref")
            investigation = graph.investigations.get(str(investigation_ref))
            if investigation is None:
                raise WorkGraphError(f"paused change {change_id} references missing investigation")
            if investigation.get("status") in {"concluded", "closed"}:
                raise WorkGraphError(f"paused change {change_id} points to a concluded investigation")
        derived = ((data.get("relations") or {}).get("derived_from") or {})
        for ref in derived.get("investigations") or []:
            if ref not in graph.investigations:
                raise WorkGraphError(f"change {change_id} derives from unknown investigation {ref}")
        produced = ((data.get("relations") or {}).get("produced") or {})
        for ref in produced.get("investigations") or []:
            investigation = graph.investigations.get(str(ref))
            if investigation is None or (investigation.get("source") or {}).get("ref") != change_id:
                raise WorkGraphError(f"change {change_id} produced investigation relation is inconsistent: {ref}")

    automatic = (task.get("pivot_control") or {}).get("automatic_investigations_from_change") or {}
    used = int(automatic.get("used", 0))
    limit = int(automatic.get("limit", 1))
    escalation = task.get("escalation") or {}
    if used > limit and escalation.get("level") == "none":
        model_status = (escalation.get("model_review") or {}).get("status")
        human_status = (escalation.get("human_checkpoint") or {}).get("status")
        if model_status not in {"completed", "inconclusive"} and human_status != "resolved":
            raise WorkGraphError("automatic pivot budget exceeded without completed escalation")

    human = escalation.get("human_checkpoint") or {}
    if human.get("status") == "pending":
        active_changes = [
            change_id for change_id, (_, data) in graph.changes.items()
            if data.get("execution_state") == "active"
        ]
        if active_changes:
            raise WorkGraphError(
                "active changes are forbidden while a human checkpoint is pending: "
                + ", ".join(active_changes)
            )

    if task.get("status") == "completed":
        if focus_type != "none":
            raise WorkGraphError("completed task must not have a current focus")
        open_investigations = [
            key for key, value in graph.investigations.items()
            if value.get("status") not in {"concluded", "closed"}
        ]
        active_changes = [
            key for key, (_, value) in graph.changes.items()
            if value.get("execution_state") in {"active", "paused"}
        ]
        if open_investigations or active_changes:
            raise WorkGraphError("completed task still has open work items")

    return graph


def graph_summary(context: ProjectContext, graph: WorkGraph) -> dict:
    task = graph.task
    investigations = []
    for investigation_id in (task.get("work_items") or {}).get("investigations") or []:
        data = graph.investigations[investigation_id]
        investigations.append({
            "id": investigation_id,
            "status": data.get("status"),
            "execution_state": data.get("execution_state"),
            "signature": (data.get("problem") or {}).get("signature"),
            "source": data.get("source"),
            "disposition": data.get("disposition"),
        })
    changes = []
    for change_id in (task.get("work_items") or {}).get("changes") or []:
        root, data = graph.changes[change_id]
        changes.append({
            "id": change_id,
            "status": data.get("status"),
            "execution_state": data.get("execution_state"),
            "location": project_relative(context, root),
            "hold": data.get("hold"),
        })
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "current_focus": task.get("current_focus"),
        "investigations": investigations,
        "changes": changes,
        "pivot_control": task.get("pivot_control"),
        "escalation": task.get("escalation"),
    }


def render_status_markdown(context: ProjectContext, graph: WorkGraph) -> str:
    summary = graph_summary(context, graph)
    lines = [
        f"# {summary['title']}",
        "",
        f"- Task: `{summary['id']}`",
        f"- Status: `{summary['status']}`",
        f"- Current focus: `{summary['current_focus']['type']}:{summary['current_focus'].get('ref') or '-'}`",
        f"- Escalation: `{(summary.get('escalation') or {}).get('level', 'none')}`",
        "",
        "## Work graph",
        "",
    ]
    if not summary["investigations"] and not summary["changes"]:
        lines.append("No work items registered.")
    for item in summary["investigations"]:
        lines.append(
            f"- Investigation `{item['id']}` — {item['status']} / {item['execution_state']} "
            f"— signature `{item['signature']}`"
        )
        disposition = item.get("disposition") or {}
        if disposition.get("type") != "pending":
            lines.append(
                f"  - disposition: `{disposition.get('type')}` → `{disposition.get('target') or '-'}`"
            )
    for item in summary["changes"]:
        lines.append(
            f"- Change `{item['id']}` — {item['status']} / {item['execution_state']}"
        )
        if item["execution_state"] == "paused":
            hold = item.get("hold") or {}
            lines.append(
                f"  - hold: `{hold.get('reason')}` → investigation `{hold.get('investigation_ref')}`"
            )
    lines.extend(["", "## Machine summary", "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)
