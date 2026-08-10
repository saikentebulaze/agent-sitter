from __future__ import annotations

import argparse
from pathlib import Path

from common import fail
from core.provider_registry import get_provider, registered_providers
from project_context import ProjectContext, resolve_project_context


def core_required_assets(context: ProjectContext) -> tuple[Path, ...]:
    governor = context.adapter_root / "skills" / "change-governor"
    knowledge = context.adapter_root / "knowledge"
    return (
        context.package_root / "manifest.yaml",
        context.package_root / "runtime" / "project_context.py",
        context.package_root / "runtime" / "provider_attestation.py",
        context.package_root / "runtime" / "core" / "provider_contract.py",
        context.package_root / "runtime" / "core" / "provider_registry.py",
        context.package_root / "runtime" / "core" / "projection_plan.py",
        context.package_root / "runtime" / "core" / "managed_projection.py",
        context.package_root / "runtime" / "core" / "role_spec.py",
        context.package_root / "runtime" / "core" / "runtime_selection.py",
        context.package_root / "runtime" / "core" / "task_runtime.py",
        context.package_root / "runtime" / "validate_task_state.py",
        context.package_root / "runtime" / "validate_investigation.py",
        context.package_root / "runtime" / "validate_work_graph.py",
        context.package_root / "runtime" / "validate_change.py",
        context.package_root / "runtime" / "governance_checks.py",
        context.package_root / "runtime" / "artifact_consistency.py",
        context.package_root / "runtime" / "delegation_policy.py",
        context.package_root / "runtime" / "delegation_context.py",
        context.package_root / "runtime" / "delegation_validation.py",
        context.package_root / "runtime" / "delegation_transaction.py",
        context.package_root / "runtime" / "decision_authority.py",
        context.package_root / "runtime" / "active_task_index.py",
        context.package_root / "runtime" / "session_context.py",
        context.package_root / "runtime" / "session_start_hook.py",
        context.package_root / "runtime" / "memory_context.py",
        context.package_root / "runtime" / "memory_scout_once.py",
        context.package_root / "runtime" / "harness.py",
        context.package_root / "runtime" / "_harness_impl.py",
        context.package_root / "runtime" / "knowledge_gate.py",
        context.package_root / "runtime" / "knowledge_tool.py",
        context.package_root / "runtime" / "work.py",
        context.package_root / "runtime" / "work_graph.py",
        context.package_root / "runtime" / "task_status.py",
        context.package_root / "runtime" / "governed_validation.py",
        context.package_root / "runtime" / "governed_work.py",
        context.package_root / "runtime" / "pivot_transaction.py",
        context.package_root / "runtime" / "review_transaction.py",
        context.package_root / "runtime" / "learning.py",
        context.package_root / "runtime" / "requirements.txt",
        governor / "SKILL.md",
        governor / "references" / "subagent-model-policy.md",
        governor / "references" / "reasoning-budget-policy.md",
        governor / "references" / "learning-incubator-policy.md",
        governor / "references" / "superpowers-integration.md",
        governor / "references" / "human-in-loop-policy.md",
        governor / "assets" / "task.yaml.template",
        governor / "assets" / "investigation.yaml.template",
        governor / "assets" / "change.yaml.template",
        governor / "assets" / "verification.md.template",
        governor / "assets" / "knowledge-sync.md.template",
        knowledge / "schemas" / "knowledge-index.schema.json",
        knowledge / "templates" / "knowledge-flow.md",
        knowledge / "templates" / "knowledge-decision.md",
        knowledge / "templates" / "knowledge-debt.md",
        knowledge / "templates" / "critical-surface.md",
        context.package_root / "docs" / "v4-work-graph.md",
        context.package_root / "docs" / "delegation-context.md",
    )


def run_self_check(context: ProjectContext) -> None:
    providers = tuple(get_provider(provider_id) for provider_id in registered_providers())
    required = list(core_required_assets(context))
    for provider in providers:
        required.extend(provider.required_assets(context))

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("missing package assets: " + ", ".join(missing))

    for provider in providers:
        provider.validate_static_configuration(context)
    print("harness_self_check: passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        context = resolve_project_context(args.project)
        run_self_check(context)
    except ValueError as error:
        fail(str(error))


if __name__ == "__main__":
    main()
