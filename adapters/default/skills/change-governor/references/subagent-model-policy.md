# Subagent Authorization, Model and Reasoning Budget

This policy separates four decisions:

1. permission to use subagents;
2. permission to exceed the parent model tier;
3. permission to use exceptional reasoning effort;
4. the exact bounded context made visible to the child.

Granting one never implies any of the others.

## Model tiers

For GPT-5.6 routing:

```text
luna < terra < sol
```

Model tier and reasoning effort are independent. Read `reasoning-budget-policy.md` before routing.

Default role pairs:

- `source_locator`: Luna/low for exact files, symbols, callers, tests and named log evidence;
- `context_scout`: Luna/medium for business chains and state lifecycle;
- `test_scout`: Luna/medium for evidence meaning, tolerance and regression risk;
- `framework_scout`: Terra/medium for framework ownership and cross-module semantics;
- `maintainer_reviewer`: Terra/medium for normal independent review;
- `deep_reviewer`: Sol/high for exceptional CRITICAL escalation.

Do not use a stronger model merely because it is available. Do not use a semantic Scout for work that only needs Locator retrieval.

## Exploration offload economics

A read-only Scout is a context-cost optimization tool as well as an independence mechanism. The parent should not consume a high-tier context window doing broad retrieval that a cheaper bounded child can perform independently.

Use a cheap parent triage first: one or two obvious anchor reads are enough to decide whether the work is local or exploration-dominant. Delegate early when ownership is still unknown, the chain crosses modules/lifecycle stages, or the next step would otherwise be broad repository traversal. For HIGH/CRITICAL Investigation work, start the required Scout as soon as the question and bounded starting scope are stable instead of waiting for the final-truth gate to block progress.

Prefer exactly one Scout initially. Choose the cheapest role that matches the job. A second Scout is justified only by `NEED_CONTEXT`, a genuinely independent second search line, or evidence conflict that needs discrimination. Do not fan out merely to increase confidence.

The parent must not mechanically repeat the child's whole search after completion. Re-open only decisive references needed to verify the child's result, integrate it with other evidence, or perform the production change. The parent owns the final conclusion; that does not require duplicating retrieval work.

MEDIUM work remains eligible to stay entirely in the parent when one or two local reads resolve the scope. LOW Fast Path work does not use subagents for ceremony.

## Independent child context

All current Sitter child roles must use independent context:

```yaml
context_policy:
  inheritance: none
```

Do not copy the parent conversation into the child. The parent generates a frozen role-specific Context Capsule through `work.py request-delegation` and passes only its request path to the native child Agent.

The request packet contains:

- one precise objective and the decision it supports;
- include/exclude scope and start anchors;
- a role-specific read-only projection of Task, Investigation, or Change;
- authority references to code, logs, experiments, and production artifacts;
- confirmed facts clearly separated from withheld parent hypotheses;
- an output contract and bounded `NEED_CONTEXT` protocol;
- frozen hashes for relevant authority inputs.

The parent retains write ownership of Task, Investigation, and Change. Child output never updates authoritative state automatically.

A child may request one concrete missing context item. The parent uses `supplement-delegation-context` to add only the missing references. Each attempt is immutable and the default maximum is two supplements.

## Parent-tier comparison

Before requesting each planned delegation:

1. Record the parent model and tier when visible.
2. Record child role, model, tier, reasoning effort, bounded purpose and target.
3. If child tier is above parent tier, request explicit user authorization naming that model and purpose.
4. If parent tier cannot be established, treat Terra/Sol as potentially elevated.
5. Luna may run under normal delegation authorization unless the user set a stricter ceiling.

A general approval such as “you may use read-only subagents” does not permit a Terra parent to spawn Sol.

## Reasoning-effort comparison

- Role default effort: no additional approval.
- One-step increase at `high` or below: record a concrete reason; no additional interruption.
- `xhigh`, `max`, or an increase of two or more levels: obtain explicit user authorization.
- `max` is never a default role setting.
- If the problem requires stronger abstraction rather than more search or verification, route to a stronger role instead of repeatedly increasing Luna effort.

## Runtime attestation

A completed delegation must provide runtime evidence for:

- canonical agent name;
- actual model and tier;
- actual reasoning effort;
- `execution: native-subagent`;
- `context_inheritance: none`;
- read-only sandbox;
- native thread or audit reference.

The Harness compares the attestation with the frozen request. A mismatch is rejected. Configuration files or a child Agent's own statement that it was isolated are not sufficient runtime evidence.

If a frozen input changed before result recording, preserve the exact output but record the delegation as `stale`; it must not enter `delegation.completed` or be promoted as current Evidence/Review.

## Failure and denial

- `denied` means continue without that elevated role/effort only if evidence remains sufficient and the task remains safe.
- `failed` means the authorized role could not run; record the runtime reason.
- `cancelled` means the target or purpose no longer applies; preserve the request history.
- Do not silently substitute the parent for a required Scout or Reviewer.
- Do not silently replace denied Sol or exceptional effort through another path.

## Evidence

A completed native delegation entry must record:

- stable `dlg-NNN` id;
- canonical agent name;
- configured model and tier;
- actual `reasoning_effort`;
- `execution: native-subagent`;
- request, output and record references;
- runtime/audit `evidence_ref`;
- `context.inheritance: none`.

Planned and completed model, tier and reasoning effort must match. The same role may be used more than once in a Task, but each use must have a distinct delegation ID.
