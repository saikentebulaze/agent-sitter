from __future__ import annotations

import hashlib
import json


class DecisionAuthorityError(ValueError):
    pass


def resolved_human_decisions(data: dict) -> list[dict]:
    """Return the compact authoritative projection of explicit user choices.

    Agent recommendations are deliberately excluded from this projection. Once
    the assessment is resolved, the user's choice and its evidence are the only
    decision values downstream consumers may treat as authoritative.
    """

    human = data.get("human_in_loop") or {}
    assessment = human.get("decision_assessment") or {}
    if str(assessment.get("status") or "") != "resolved":
        return []

    result: list[dict] = []
    for raw in human.get("decisions") or []:
        if not isinstance(raw, dict):
            continue
        decision_id = str(raw.get("id") or "").strip()
        user_decision = str(raw.get("user_decision") or "").strip()
        evidence = str(raw.get("evidence") or "").strip()
        question = str(raw.get("question") or "").strip()
        if not decision_id or not user_decision or not evidence:
            raise DecisionAuthorityError(
                "resolved human decision requires id, user_decision, and evidence"
            )
        result.append(
            {
                "id": decision_id,
                "question": question,
                "user_decision": user_decision,
                "evidence": evidence,
            }
        )
    result.sort(key=lambda item: item["id"])
    return result


def human_decision_digest(data: dict) -> str:
    payload = json.dumps(
        resolved_human_decisions(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def authority_projection(data: dict) -> dict:
    decisions = resolved_human_decisions(data)
    return {
        "status": "authoritative" if decisions else "not-applicable",
        "sha256": human_decision_digest(data),
        "decisions": decisions,
        "rule": (
            "User decisions are authoritative. Agent recommendations are advisory only; "
            "downstream Design, Implementation, Verification, Review, and durable Memory "
            "must remain consistent with these choices unless the user explicitly reconsiders them."
        ),
    }
