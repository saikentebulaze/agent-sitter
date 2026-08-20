from __future__ import annotations

from pathlib import Path

import yaml

from change_validation import ChangeValidationError, validate_change_in_process
from project_context import ProjectContext
from reference_resolver import resolve_change_ref
from review_transaction import atomic_write_text, atomic_write_yaml
from work_graph import now_iso


class KnowledgeLifecycleError(ValueError):
    pass


def _load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise KnowledgeLifecycleError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise KnowledgeLifecycleError(f"expected YAML mapping: {path}")
    return data


def defer_knowledge(
    context: ProjectContext,
    change_value: str | Path,
    *,
    reason: str,
) -> str:
    """Explicitly record that the current Change has no durable Knowledge candidate.

    V6.2 intentionally does not auto-defer Knowledge: absence of a durable
    candidate is a valid closure outcome, but it must be an explicit governed
    decision with a reason.  The transaction is intentionally narrow and is
    available only after final verification has advanced the Change to syncing.
    """

    reason = reason.strip()
    if not reason:
        raise KnowledgeLifecycleError("Knowledge defer reason is required")

    ref = resolve_change_ref(context, change_value)
    data = _load(ref.yaml_path)
    if data.get("candidate_readiness_protocol") != 1:
        raise KnowledgeLifecycleError(
            "defer-knowledge is only available for candidate_readiness_protocol 1 Changes"
        )
    if str(data.get("status") or "") != "syncing":
        raise KnowledgeLifecycleError("Knowledge can only be deferred while Change status is syncing")

    sync = data.setdefault("knowledge_sync", {})
    status = str(sync.get("status") or "pending")
    entries = sync.get("entries") or []
    if not isinstance(entries, list):
        raise KnowledgeLifecycleError("knowledge_sync.entries must be a list")
    if entries:
        raise KnowledgeLifecycleError(
            "Knowledge candidates exist; review/promote them instead of deferring Knowledge"
        )
    if status == "promoted":
        raise KnowledgeLifecycleError("promoted Knowledge cannot be replaced by a defer decision")
    if status == "deferred":
        if str(sync.get("deferred_reason") or "").strip() == reason:
            return "deferred"
        raise KnowledgeLifecycleError(
            "Knowledge is already deferred with a different reason"
        )
    if status not in {"pending"}:
        raise KnowledgeLifecycleError(
            f"Knowledge status {status!r} is not eligible for zero-candidate defer"
        )

    original = ref.yaml_path.read_text(encoding="utf-8")
    sync.update(
        {
            "status": "deferred",
            "deferred_reason": reason,
            "deferred_at": now_iso(),
        }
    )
    try:
        atomic_write_yaml(ref.yaml_path, data)
        validate_change_in_process(ref.root)
    except (ChangeValidationError, OSError, ValueError) as error:
        atomic_write_text(ref.yaml_path, original)
        raise KnowledgeLifecycleError(str(error)) from error
    return "deferred"
