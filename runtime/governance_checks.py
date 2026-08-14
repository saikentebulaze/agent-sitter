from __future__ import annotations

from common import fail
from decision_authority import DecisionAuthorityError, human_decision_digest


HUMAN_MODES = {"autonomous", "guided", "manual"}
DECISION_STATUSES = {"pending", "not-required", "required", "resolved"}
USER_REVIEW_STATUSES = {"pending", "approved", "changes-requested", "not-required"}
KNOWLEDGE_STATUSES = {"pending", "candidate", "reviewed", "promoted", "deferred"}


def non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    return value.strip()


def string_list(value: object, name: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        fail(f"{name} must be a list of non-empty strings")
    if not allow_empty and not value:
        fail(f"{name} must not be empty")
    return [item.strip() for item in value]


def validate_human_in_loop(
    data: dict,
    *,
    semantic_risk: str,
    advanced: bool,
    label: str = "human_in_loop",
) -> None:
    human = data.get("human_in_loop") or {}
    if not isinstance(human, dict):
        fail(f"{label} must be a mapping")

    mode = str(human.get("mode", "guided"))
    if mode not in HUMAN_MODES:
        fail(f"invalid {label}.mode: {mode}")
    if mode == "autonomous":
        non_empty_string(human.get("mode_evidence"), f"{label}.mode_evidence")

    budget = human.get("interruption_budget") or {}
    if not isinstance(budget, dict):
        fail(f"{label}.interruption_budget must be a mapping")
    if not isinstance(budget.get("batch_questions", True), bool):
        fail(f"{label}.interruption_budget.batch_questions must be boolean")
    checkpoints = budget.get("max_design_checkpoints", 1)
    if not isinstance(checkpoints, int) or checkpoints < 0:
        fail(f"{label}.interruption_budget.max_design_checkpoints must be a non-negative integer")

    assessment = human.get("decision_assessment") or {}
    if not isinstance(assessment, dict):
        fail(f"{label}.decision_assessment must be a mapping")
    status = str(assessment.get("status", "pending"))
    if status not in DECISION_STATUSES:
        fail(f"invalid {label}.decision_assessment.status: {status}")
    reasons = assessment.get("reasons") or []
    string_list(reasons, f"{label}.decision_assessment.reasons")

    decisions = human.get("decisions") or []
    if not isinstance(decisions, list):
        fail(f"{label}.decisions must be a list")
    ids: set[str] = set()
    for index, decision in enumerate(decisions):
        item_label = f"{label}.decisions[{index}]"
        if not isinstance(decision, dict):
            fail(f"{item_label} must be a mapping")
        decision_id = non_empty_string(decision.get("id"), f"{item_label}.id")
        if decision_id in ids:
            fail(f"duplicate human decision id: {decision_id}")
        ids.add(decision_id)
        non_empty_string(decision.get("question"), f"{item_label}.question")
        string_list(decision.get("options") or [], f"{item_label}.options", allow_empty=False)
        non_empty_string(decision.get("recommendation"), f"{item_label}.recommendation")
        if status == "resolved":
            non_empty_string(decision.get("user_decision"), f"{item_label}.user_decision")
            non_empty_string(decision.get("evidence"), f"{item_label}.evidence")

    if status == "not-required" and not reasons:
        fail(f"{label}.decision_assessment.reasons must explain why no material decision exists")
    if status == "required" and not decisions:
        fail(f"{label}.decisions must list the material decisions requiring user input")
    if status == "resolved" and not decisions:
        fail(f"{label}.decisions must preserve the resolved user decisions")

    if semantic_risk in {"high", "critical"} and advanced:
        if status in {"pending", "required"}:
            fail("HIGH/CRITICAL work has unresolved material human decisions")
        if mode == "manual" and status != "resolved":
            fail("manual human-in-loop mode requires a resolved decision checkpoint")


def _validate_decision_authority(data: dict) -> None:
    human = data.get("human_in_loop") or {}
    status = str((human.get("decision_assessment") or {}).get("status") or "")
    protocol = data.get("decision_authority_protocol")
    if protocol not in {None, 1}:
        fail("unsupported decision_authority_protocol")
    if status != "resolved":
        return

    review = data.get("review") or {}
    execution = review.get("execution") or {}
    snapshot = execution.get("input_snapshot") or {}
    knowledge = data.get("knowledge_sync") or {}

    # Pre-V6 schema-v4 Changes may contain resolved human decisions but no
    # authority protocol/snapshots. Keep them read-compatible. Once any V6
    # authority marker exists, however, deleting another marker must not make
    # validation fall open.
    v6_authority = (
        protocol == 1
        or "human_decisions_sha256" in snapshot
        or "human_decisions_sha256" in knowledge
    )
    if not v6_authority:
        return

    try:
        digest = human_decision_digest(data)
    except DecisionAuthorityError as error:
        fail(str(error))

    if str(review.get("status") or "pending") != "pending":
        if str(snapshot.get("human_decisions_sha256") or "") != digest:
            fail(
                "review does not match the current authoritative human decisions; "
                "request a new review"
            )

    if str(knowledge.get("status") or "pending") in {"candidate", "reviewed", "promoted"}:
        if str(knowledge.get("human_decisions_sha256") or "") != digest:
            fail(
                "knowledge candidate does not match the current authoritative human decisions; "
                "render it again before review/promotion"
            )


def validate_change_closure(data: dict, status: str) -> None:
    _validate_decision_authority(data)

    completion = data.get("completion") or {}
    if not isinstance(completion, dict):
        fail("completion must be a mapping")
    implementation_complete = completion.get("implementation_complete", False)
    ready_for_user_review = completion.get("ready_for_user_review", False)
    if not isinstance(implementation_complete, bool):
        fail("completion.implementation_complete must be boolean")
    if not isinstance(ready_for_user_review, bool):
        fail("completion.ready_for_user_review must be boolean")

    user_review = data.get("user_review") or {}
    if not isinstance(user_review, dict):
        fail("user_review must be a mapping")
    user_review_status = str(user_review.get("status", "pending"))
    if user_review_status not in USER_REVIEW_STATUSES:
        fail(f"invalid user_review.status: {user_review_status}")
    if user_review_status in {"approved", "changes-requested"}:
        non_empty_string(user_review.get("evidence"), "user_review.evidence")

    if status in {"verifying", "syncing", "ready-to-archive", "archived"}:
        if not implementation_complete:
            fail("implementation is not marked complete")
    if status in {"syncing", "ready-to-archive", "archived"} and not ready_for_user_review:
        fail("change is not marked ready for user review")
    if status in {"ready-to-archive", "archived"}:
        if user_review_status not in {"approved", "not-required"}:
            fail("user review is not approved")

    knowledge = data.get("knowledge_sync") or {}
    if not isinstance(knowledge, dict):
        fail("knowledge_sync must be a mapping")
    knowledge_status = str(knowledge.get("status", "pending"))
    if knowledge_status not in KNOWLEDGE_STATUSES:
        fail(f"invalid knowledge_sync.status: {knowledge_status}")
    entries = knowledge.get("entries") or []
    if not isinstance(entries, list):
        fail("knowledge_sync.entries must be a list")

    if knowledge_status in {"candidate", "reviewed", "promoted"}:
        non_empty_string(knowledge.get("candidate_ref"), "knowledge_sync.candidate_ref")
    if knowledge_status in {"reviewed", "promoted"}:
        non_empty_string(knowledge.get("rendered_diff_ref"), "knowledge_sync.rendered_diff_ref")
        non_empty_string(knowledge.get("reviewed_by"), "knowledge_sync.reviewed_by")
        non_empty_string(knowledge.get("reviewed_at"), "knowledge_sync.reviewed_at")
        non_empty_string(knowledge.get("review_evidence"), "knowledge_sync.review_evidence")
    if knowledge_status == "deferred":
        non_empty_string(knowledge.get("deferred_reason"), "knowledge_sync.deferred_reason")

    if status in {"ready-to-archive", "archived"} and knowledge_status not in {"promoted", "deferred"}:
        fail("knowledge candidate has not been promoted or explicitly deferred")
