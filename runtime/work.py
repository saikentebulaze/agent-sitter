from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adaptive_work import investigate_change, pivot_to_change
from core.work_risk import RiskVector, parse_level, vector_mapping
from delegation_transaction import (
    DelegationTransactionError,
    authorize_delegation,
    close_delegation,
    delegation_status,
    record_delegation_result,
    request_delegation,
    supplement_delegation_context,
)
from governed_validation import validate_governed_work_graph
from governed_work import (
    PivotTransactionError,
    complete_task,
    conclude_investigation,
    create_investigation,
    record_claim,
    record_decision,
    record_evidence,
    record_model_review,
    request_model_review,
    resolve_human_checkpoint,
)
from project_context import resolve_project_context
from risk_transaction import RiskTransactionError, reassess_task_risk
from task_status import build_action_dashboard
from work_graph import WorkGraphError, resolve_task_root


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _add_delegation_commands(subparsers: argparse._SubParsersAction) -> None:
    authorize = subparsers.add_parser("authorize-delegation")
    authorize.add_argument("task")
    authorize.add_argument("--decision", choices=("required", "optional"), required=True)
    authorize.add_argument(
        "--scope",
        action="append",
        choices=("readonly-exploration", "readonly-review"),
        required=True,
    )
    authorize.add_argument("--evidence", required=True)
    authorize.add_argument("--parent-model", default="unknown")
    authorize.add_argument(
        "--parent-tier", choices=("luna", "terra", "sol", "unknown"), default="unknown"
    )

    request = subparsers.add_parser("request-delegation")
    request.add_argument("task")
    request.add_argument(
        "--role",
        choices=(
            "source_locator",
            "context_scout",
            "test_scout",
            "framework_scout",
            "maintainer_reviewer",
            "deep_reviewer",
        ),
        required=True,
    )
    request.add_argument(
        "--target-type", choices=("task", "investigation", "change"), required=True
    )
    request.add_argument("--target-ref", required=True)
    request.add_argument("--purpose", required=True)
    request.add_argument("--question", required=True)
    request.add_argument("--decision-supported", required=True)
    request.add_argument("--include", action="append", default=[])
    request.add_argument("--exclude", action="append", default=[])
    request.add_argument("--start-ref", action="append", default=[])
    request.add_argument("--confirmed-fact", action="append", default=[])

    record = subparsers.add_parser("record-delegation-result")
    record.add_argument("task")
    record.add_argument("delegation")
    record.add_argument("--artifact", type=Path, required=True)
    record.add_argument(
        "--outcome", choices=("completed", "need-context", "failed"), required=True
    )
    record.add_argument("--evidence-ref", required=True)
    record.add_argument("--attestation", type=Path, required=True)

    supplement = subparsers.add_parser("supplement-delegation-context")
    supplement.add_argument("task")
    supplement.add_argument("delegation")
    supplement.add_argument("--ref", action="append", required=True)
    supplement.add_argument("--reason", action="append", required=True)

    for name in ("fail-delegation", "cancel-delegation"):
        command = subparsers.add_parser(name)
        command.add_argument("task")
        command.add_argument("delegation")
        command.add_argument("--reason", required=True)
        command.add_argument("--evidence-ref", required=True)

    status = subparsers.add_parser("delegation-status")
    status.add_argument("task")
    status.add_argument("delegation", nargs="?")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sitter v4 governed work-graph commands")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("task-status")
    status.add_argument("task")

    validate = subparsers.add_parser("validate")
    validate.add_argument("task")

    risk = subparsers.add_parser("reassess-risk")
    risk.add_argument("task")
    risk.add_argument(
        "--semantic",
        choices=("low", "medium", "high", "critical"),
        required=True,
    )
    risk.add_argument(
        "--repository-change",
        choices=("low", "medium", "high", "critical"),
        required=True,
    )
    risk.add_argument("--reason", required=True)
    risk.add_argument("--evidence-ref")
    risk.add_argument("--remaining-work-bounded", action="store_true")
    risk.add_argument("--raise-assurance", action="store_true")

    create_inv = subparsers.add_parser("create-investigation")
    create_inv.add_argument("task")
    create_inv.add_argument("--title", required=True)
    create_inv.add_argument("--question", required=True)
    create_inv.add_argument("--signature", required=True)
    create_inv.add_argument(
        "--source-type", choices=("task", "change", "investigation"), default="task"
    )
    create_inv.add_argument("--source-ref")
    create_inv.add_argument("--discrimination-rationale")

    evidence = subparsers.add_parser("record-evidence")
    evidence.add_argument("task")
    evidence.add_argument("investigation")
    evidence.add_argument("--id", required=True)
    evidence.add_argument("--kind", required=True)
    evidence.add_argument("--source-ref", required=True)
    evidence.add_argument("--provenance", required=True)
    evidence.add_argument(
        "--reliability", choices=("low", "medium", "high"), default="medium"
    )
    evidence.add_argument("--supports", action="append", default=[])
    evidence.add_argument("--contradicts", action="append", default=[])
    evidence.add_argument("--limitation", action="append", default=[])

    claim = subparsers.add_parser("record-claim")
    claim.add_argument("task")
    claim.add_argument("investigation")
    claim.add_argument("--id", required=True)
    claim.add_argument("--statement", required=True)
    claim.add_argument(
        "--status",
        choices=("open", "supported", "refuted", "inconclusive", "superseded"),
        required=True,
    )
    claim.add_argument(
        "--confidence", choices=("low", "medium", "high"), required=True
    )
    claim.add_argument("--supporting-evidence", action="append", default=[])
    claim.add_argument("--contradicting-evidence", action="append", default=[])

    decision = subparsers.add_parser("record-decision")
    decision.add_argument("task")
    decision.add_argument("investigation")
    decision.add_argument("--id", required=True)
    decision.add_argument("--statement", required=True)
    decision.add_argument(
        "--status",
        choices=("proposed", "accepted", "rejected", "superseded"),
        required=True,
    )
    decision.add_argument("--claim", action="append", default=[])
    decision.add_argument("--evidence", action="append", default=[])
    decision.add_argument("--requires-human", action="store_true")
    decision.add_argument("--evidence-ref")

    pivot = subparsers.add_parser("pivot-to-change")
    pivot.add_argument("task")
    pivot.add_argument("investigation")
    pivot.add_argument("change_id")
    pivot.add_argument("--title", required=True)
    pivot.add_argument("--rationale", required=True)
    pivot.add_argument("--supersede-change")

    investigate = subparsers.add_parser("investigate-change")
    investigate.add_argument("change")
    investigate.add_argument("--title", required=True)
    investigate.add_argument("--question", required=True)
    investigate.add_argument("--signature", required=True)
    investigate.add_argument("--discrimination-rationale")

    conclude = subparsers.add_parser("conclude-investigation")
    conclude.add_argument("task")
    conclude.add_argument("investigation")
    conclude.add_argument(
        "--disposition",
        choices=(
            "no-change-required",
            "resume-change",
            "revise-change",
            "follow-up-investigation",
            "inconclusive",
        ),
        required=True,
    )
    conclude.add_argument("--target")
    conclude.add_argument("--rationale", required=True)
    conclude.add_argument("--remaining-unknown", action="append", default=[])
    conclude.add_argument("--scope-revalidated", action="store_true")
    conclude.add_argument("--design-revalidated", action="store_true")
    conclude.add_argument("--approval-still-valid", action="store_true")

    model_request = subparsers.add_parser("request-model-review")
    model_request.add_argument("task")
    model_request.add_argument(
        "--role",
        choices=(
            "framework_scout",
            "maintainer_reviewer",
            "deep_reviewer",
        ),
    )
    model_request.add_argument("--elevated-authorization-ref")

    model_record = subparsers.add_parser("record-model-review")
    model_record.add_argument("task")
    model_record.add_argument("--artifact", type=Path, required=True)
    model_record.add_argument(
        "--outcome", choices=("supported", "inconclusive", "block"), required=True
    )
    model_record.add_argument("--evidence-ref", required=True)

    human = subparsers.add_parser("resolve-human-checkpoint")
    human.add_argument("task")
    human.add_argument("--action", choices=("continue", "stop"), required=True)
    human.add_argument("--decision", required=True)
    human.add_argument("--evidence", required=True)

    complete = subparsers.add_parser("complete-task")
    complete.add_argument("task")
    complete.add_argument("--rationale", required=True)

    _add_delegation_commands(subparsers)

    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        if args.command in {"task-status", "validate"}:
            task_root = resolve_task_root(context, args.task)
            graph = validate_governed_work_graph(context, task_root)
            if args.command == "validate":
                print("work_graph: valid")
            else:
                print(
                    json.dumps(
                        build_action_dashboard(graph), ensure_ascii=False, indent=2
                    )
                )
        elif args.command == "reassess-risk":
            current, peak, assurance_change = reassess_task_risk(
                context,
                args.task,
                target=RiskVector(
                    parse_level(args.semantic),
                    parse_level(args.repository_change),
                ),
                reason=args.reason,
                evidence_ref=args.evidence_ref,
                remaining_work_bounded=args.remaining_work_bounded,
                raise_assurance=args.raise_assurance,
            )
            print(
                json.dumps(
                    {
                        "current": vector_mapping(current),
                        "peak": vector_mapping(peak),
                        "assurance_change": assurance_change,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "create-investigation":
            investigation_id = create_investigation(
                context,
                args.task,
                title=args.title,
                question=args.question,
                signature=args.signature,
                source_type=args.source_type,
                source_ref=args.source_ref,
                discrimination_rationale=args.discrimination_rationale,
            )
            print(investigation_id)
        elif args.command == "record-evidence":
            record_evidence(
                context,
                args.task,
                args.investigation,
                evidence_id=args.id,
                kind=args.kind,
                source_ref=args.source_ref,
                provenance=args.provenance,
                reliability=args.reliability,
                supports=args.supports,
                contradicts=args.contradicts,
                limitations=args.limitation,
            )
            print(args.id)
        elif args.command == "record-claim":
            record_claim(
                context,
                args.task,
                args.investigation,
                claim_id=args.id,
                statement=args.statement,
                status=args.status,
                confidence=args.confidence,
                supporting_evidence=args.supporting_evidence,
                contradicting_evidence=args.contradicting_evidence,
            )
            print(args.id)
        elif args.command == "record-decision":
            record_decision(
                context,
                args.task,
                args.investigation,
                decision_id=args.id,
                statement=args.statement,
                status=args.status,
                claims=args.claim,
                evidence=args.evidence,
                requires_human=args.requires_human,
                evidence_ref=args.evidence_ref,
            )
            print(args.id)
        elif args.command == "pivot-to-change":
            root = pivot_to_change(
                context,
                args.task,
                args.investigation,
                change_id=args.change_id,
                title=args.title,
                rationale=args.rationale,
                supersede_change=args.supersede_change,
            )
            print(root.relative_to(context.project_root))
        elif args.command == "investigate-change":
            investigation_id = investigate_change(
                context,
                args.change,
                title=args.title,
                question=args.question,
                signature=args.signature,
                discrimination_rationale=args.discrimination_rationale,
            )
            print(investigation_id)
        elif args.command == "conclude-investigation":
            conclude_investigation(
                context,
                args.task,
                args.investigation,
                disposition=args.disposition,
                target=args.target,
                rationale=args.rationale,
                remaining_unknowns=args.remaining_unknown,
                scope_revalidated=args.scope_revalidated,
                design_revalidated=args.design_revalidated,
                approval_still_valid=args.approval_still_valid,
            )
            print(f"concluded: {args.investigation}")
        elif args.command == "request-model-review":
            packet = request_model_review(
                context,
                args.task,
                role=args.role,
                elevated_authorization_ref=args.elevated_authorization_ref,
            )
            print(packet.relative_to(context.project_root))
        elif args.command == "record-model-review":
            record_model_review(
                context,
                args.task,
                artifact=args.artifact,
                outcome=args.outcome,
                evidence_ref=args.evidence_ref,
            )
            print(f"model review recorded: {args.outcome}")
        elif args.command == "resolve-human-checkpoint":
            resolve_human_checkpoint(
                context,
                args.task,
                action=args.action,
                decision=args.decision,
                evidence=args.evidence,
            )
            print(f"human checkpoint resolved: {args.action}")
        elif args.command == "complete-task":
            complete_task(context, args.task, rationale=args.rationale)
            print(f"task completed: {args.task}")
        elif args.command == "authorize-delegation":
            authorize_delegation(
                context,
                args.task,
                decision=args.decision,
                scopes=args.scope,
                evidence=args.evidence,
                parent_model=args.parent_model,
                parent_tier=args.parent_tier,
            )
            print(f"delegation authorized: {args.task}")
        elif args.command == "request-delegation":
            packet = request_delegation(
                context,
                args.task,
                role=args.role,
                target_type=args.target_type,
                target_ref=args.target_ref,
                purpose=args.purpose,
                question=args.question,
                decision_supported=args.decision_supported,
                include=args.include,
                exclude=args.exclude,
                start_refs=args.start_ref,
                confirmed_facts=args.confirmed_fact,
            )
            print(packet.relative_to(context.project_root))
        elif args.command == "record-delegation-result":
            output, outcome, already_recorded = record_delegation_result(
                context,
                args.task,
                args.delegation,
                artifact=args.artifact,
                outcome=args.outcome,
                evidence_ref=args.evidence_ref,
                attestation=args.attestation,
            )
            prefix = "already recorded" if already_recorded else "recorded"
            print(
                f"{prefix}: {outcome}: "
                f"{output.relative_to(context.project_root).as_posix()}"
            )
        elif args.command == "supplement-delegation-context":
            packet = supplement_delegation_context(
                context,
                args.task,
                args.delegation,
                refs=args.ref,
                reasons=args.reason,
            )
            print(packet.relative_to(context.project_root))
        elif args.command in {"fail-delegation", "cancel-delegation"}:
            close_delegation(
                context,
                args.task,
                args.delegation,
                outcome="failed" if args.command == "fail-delegation" else "cancelled",
                reason=args.reason,
                evidence_ref=args.evidence_ref,
            )
            print(f"{args.command}: {args.delegation}")
        elif args.command == "delegation-status":
            print(
                json.dumps(
                    delegation_status(context, args.task, args.delegation),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    except (
        ValueError,
        WorkGraphError,
        PivotTransactionError,
        DelegationTransactionError,
        RiskTransactionError,
    ) as error:
        fail(str(error))


if __name__ == "__main__":
    main()
