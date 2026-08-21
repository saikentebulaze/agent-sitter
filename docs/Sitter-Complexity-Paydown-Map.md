# Sitter Complexity Paydown Map

This document translates the Core Constitution and Core Asset Register into a concrete V6.3 simplification direction.

V6.3 is not a capability-expansion release by default. Its purpose is to preserve the same core information and guarantees while reducing Agent-visible orchestration, duplicated state, repeated runtime work, and compatibility layering.

A useful summary is:

> **Same Core Information + Same or Stronger Guarantees - Ceremony - Derived State - Agent-visible Complexity**

---

## 1. Primary objective

Normal Sitter usage should feel like engineering work assisted by governance, not governance work interrupted by engineering.

The desired normal governed flow is:

```text
complex problem
    ↓
Investigation / bounded Scout when needed
    ↓
implementation + engineering verification
    ↓
prepare-candidate
    ↓
Candidate Human Stop
    ↓
complete-after-approval
    ↓
done
```

LOW work remains:

```text
locate -> act/run -> focused verification -> concise report
```

The internal state and evidence can remain rich. The parent Agent should not manually orchestrate every storage and lifecycle transition.

---

## 2. Paydown Layer A — Agent-facing surface compression

### Problem

Current governed work exposes too many low-level operations to the parent Agent. Each command creates additional reasoning about legal state, next action, retries, status checks, and evidence bookkeeping.

### Direction

Normal-path Agent-facing commands should converge toward a very small set of semantic operations, for example:

- investigate / bounded delegation when uncertainty requires it;
- `prepare-candidate`;
- explicit user review / acceptance;
- `complete-after-approval`;
- diagnostic `status` only for recovery or ambiguity.

Low-level commands such as individual readiness recording, finalization, rendering, semantic `advance`, Knowledge defer, cleanup finalization, Learning intake/closeout, and other lifecycle maintenance should remain internal/recovery APIs where needed but leave the normal path.

### Rule

> If Harness can deterministically perform the sequence and knows the real stop conditions, the parent Agent should not be required to compose the sequence manually.

### Expected benefit

- fewer CLI/process invocations;
- fewer conversational round trips;
- less main-Agent state-machine reasoning;
- lower token consumption;
- fewer opportunities for incorrect command ordering;
- clearer user-visible engineering completion.

---

## 3. Paydown Layer B — Candidate transaction compression

### `prepare-candidate`

The high-level transaction should own the Candidate-preparation sequence rather than acting as a shell wrapper around many externally orchestrated commands.

Target responsibilities include:

1. validate all candidate evidence input before mutation;
2. capture the current workspace state once for reusable deterministic checks;
3. batch readiness evidence validation and commit;
4. finalize test hygiene from the same captured workspace where safe;
5. classify changed workspace surfaces conservatively;
6. run Change Budget / scope preflight before spending Reviewer cost;
7. freeze the Candidate snapshot;
8. decide whether the existing Review remains valid or a Reviewer is required;
9. run the independent Provider-bound Reviewer when required;
10. re-check relevant production state after the external Reviewer to avoid stale acceptance;
11. transition to the Candidate Human Stop;
12. stop.

The transaction must not continue into final verification or closure before required user acceptance.

### Atomicity model

External model execution prevents one giant ACID transaction. Sitter should instead use bounded atomic commit points, immutable request/evidence artifacts, stale detection, and idempotent recovery.

A later Knowledge or Learning stop must not roll back already-valid engineering verification.

---

## 4. Paydown Layer C — Approval-to-closure compression

### `complete-after-approval`

After explicit Candidate acceptance, one semantic operation should coordinate normal closure:

1. verify that required acceptance is current;
2. record and finalize batch Final Verification evidence;
3. stop immediately if engineering verification fails;
4. assess Knowledge consequences;
5. preserve real Knowledge candidates and stop for human action only when necessary;
6. take the explicit zero-Knowledge path without forcing meaningless document churn;
7. validate experiment/test/temporary production cleanup without deleting user files silently;
8. archive when archive preconditions are satisfied;
9. run Learning closeout automatically when there is no meaningful user decision;
10. preserve observations and stop if mature durable candidates require user curation;
11. complete the owning Task only if no other active Investigation/Change prevents completion.

### User-visible rule

Engineering completion and governance closure should be distinguishable without creating another persisted lifecycle state machine.

If engineering proof is complete but governance residual work remains, the Agent should report that truth explicitly rather than implying the engineering work is unfinished.

---

## 5. Paydown Layer D — Derived state reduction

### First-wave candidates

The clearest redundant persisted fields are:

- `completion.implementation_complete`;
- `completion.ready_for_user_review`.

These are reconstructable from canonical readiness, review, acceptance, and lifecycle state.

Normal dashboards should compute them rather than requiring every mutation path to synchronize duplicate booleans.

### Later candidates

After compatibility impact is understood, evaluate:

- `methodology.test_cleanup_complete` when authoritative finalization evidence already exists;
- aggregate review status derived from Architecture / Scope / Numerical Evidence axes;
- aggregate verification status derived from structured results;
- `ready-to-archive` when it functions only as a transient Archive transaction precondition.

### Constraint

V6.3 should not become a broad schema-migration project. Remove the highest-value duplication first and preserve readers for legacy state where practical.

---

## 6. Paydown Layer E — Projection reduction

Structured evidence remains authoritative. Human-readable Markdown remains valuable, but it should be a projection rather than another lifecycle obligation.

Candidates for lazy or boundary rendering:

- `verification.md`;
- `archive-summary.md`;
- Task / Change status Markdown;
- Knowledge review diff/projection;
- empty Knowledge-sync documents.

Create or refresh projections when a user/reviewer needs them or at a meaningful lifecycle boundary, not after every structured write.

---

## 7. Paydown Layer F — General workspace semantic boundary

### Problem

A changed file is not automatically a Production semantic change. Conversely, extension-based ignores can hide real production changes.

The design must not special-case spreadsheets, CSV, Markdown, images, reports, or any other particular file type.

### Minimum semantic roles

```text
production
    source/config/schema/build/durable production-facing tests/other governed behavior

evidence
    benchmark/reference/comparison/analytical/other assurance inputs

task-output
    reports/exports/generated analysis/user-requested auxiliary deliverables

harness
    Task/Investigation/Change/Review/Learning/Knowledge/installed Harness state
```

### Conservative classification

1. known Harness path -> `harness`;
2. Change-owned production or test surface -> `production`;
3. explicit assurance evidence reference -> `evidence`;
4. explicit exact Task output -> `task-output`;
5. unknown -> `production`.

### Safety restrictions

- no global extension ignore;
- no broad `outputs/**` exclusion merely for convenience;
- tracked source/config cannot be declared task-output merely to avoid stale detection;
- auxiliary output referenced as assurance evidence must remain content-bound to that evidence even if excluded from Production Snapshot;
- classification should require minimum explicit metadata and avoid a large Artifact Ownership framework unless real usage proves it necessary.

The purpose is to distinguish **engineering semantic surfaces**, not to solve one acceptance example.

---

## 8. Paydown Layer G — Review cost reduction

### Preserve

- one independent Candidate Reviewer when required;
- Architecture / Scope / Numerical Evidence guarantees;
- Provider-bound real runtime execution and attestation;
- immutable request and stale detection;
- full re-review after real implementation changes that invalidate the previous judgment.

### First V6.3 optimization

Do not build a generic Delta Review engine initially.

Support only a narrow mechanically provable reuse path for changes that do not alter the previously reviewed semantic surface, such as removal of a recognized temporary/generated artifact or equivalent cleanup.

A mechanical recheck is allowed only when deterministic evidence proves that:

- production semantics are unchanged;
- Design and authoritative human decisions are unchanged;
- relevant readiness/test evidence used by the prior review is unchanged;
- the prior Architecture/Numerical result does not require semantic remediation;
- the only difference belongs to an explicitly recognized mechanical cleanup class.

Any ambiguity falls back to FULL Reviewer.

### Future Delta Review

Only introduce axis-level Delta Review if real telemetry demonstrates repeated material savings that cannot be obtained by preflight or mechanical reuse. Do not create a generic invalidation framework merely because component digests exist.

---

## 9. Paydown Layer H — Learning and Knowledge ceremony

### Preserve

- Learning observations;
- mature candidates;
- individual human curation where authority is required;
- Durable Memory promotion;
- Knowledge index, provenance, freshness, conflict, and supersession;
- cross-session and cross-Task context value.

### Compress

- deterministic Learning intake should occur automatically when governed Task creation requires it;
- no-observation closeout should become an internal no-op transaction;
- ordinary observations should be persisted without requiring conversational ceremony;
- only mature durable candidates that need user curation should create a user-visible stop;
- zero-Knowledge closure should not require meaningless candidate documents or keyword-driven manual review;
- keyword-only Knowledge hints that do not determine truth should leave the normal path.

### Principle

> Remove Learning/Knowledge ceremony, not Learning/Knowledge information.

---

## 10. Paydown Layer I — Minimum Sufficient Capability

Sitter should implement the Constitution's cost principle across role selection and execution.

### Execution ladder

```text
deterministic logic
      ↓ if insufficient
cheap narrow specialist
      ↓ if insufficient
mid-tier specialist
      ↓ if insufficient
strong model
      ↓ if a material unresolved choice remains
human authority
```

### Role economics

The Core should express provider-neutral capability/reasoning needs. Providers map them to native model selectors.

Typical intent:

- Locator / simple Memory filtering -> cheapest sufficient model, low reasoning;
- Context/Test Scout -> cheap-to-mid model, bounded reasoning;
- Framework Scout -> mid-tier with stronger reasoning when cross-module semantics require it;
- Maintainer Reviewer -> sufficiently strong independent reviewer;
- Deep Reviewer -> strongest tier only after evidence shows ordinary review/exploration is insufficient.

Do not hard-code current Codex model names into Governance Core.

### Subagent rule

Cheap subagents reduce cost only when they reduce more expensive parent work or parallelize genuinely independent uncertainty. More subagents are not automatically cheaper.

### Parallelism rule

Default to one relevant Scout. Fan out only when multiple independent unknown surfaces can materially change the decision and latency benefit justifies additional token cost.

### Reuse rule

Within the same Task, valid delegation or deterministic evidence should be reused when its frozen authority and relevant workspace surface remain current. Do not re-run semantically identical Scouts for ceremony.

### Agent-to-Agent density

Child results should prefer compact structured evidence packets—paths, symbols, call chains, evidence refs, unknowns, confidence—over long narrative essays. Human-readable explanation belongs at the user boundary.

### Stop rule

Once the current objective and assurance requirement are satisfied, default to stopping rather than adding speculative Scouts, status checks, tests, or Reviewer runs.

---

## 11. Paydown Layer J — Process and workspace reuse

### Shared workspace capture

Within one high-level transaction, repeated deterministic consumers should reuse one immutable captured workspace state where safe:

- changed tracked/untracked paths;
- production semantic set;
- test candidates;
- Production Snapshot hash;
- reviewer-readable diff;
- Change Budget inputs.

After an external Provider/model execution, re-capture the portions necessary to prove that the reviewed inputs remain current.

### In-process validation

When the same Python validation logic can be called safely in-process, do not launch another Python interpreter merely to invoke its CLI wrapper.

This is especially useful on Windows, where process-launch failures can dominate Harness overhead.

### Failure taxonomy

At minimum distinguish:

- `process_spawn_failure`: child process never started;
- `command_exit_failure`: child started but Harness/helper/runtime command returned nonzero;
- `engineering_test_failure`: the engineering verification itself produced a failing result.

Do not misclassify host-level failures that occur before Harness starts as Harness-observed events.

---

## 12. Paydown Layer K — Compatibility debt

Current version evolution has created layered facades and compatibility re-exports.

V6.3 should begin a compatibility inventory rather than add another version layer.

Examples to inspect:

- `harness.py -> _harness_v62_impl.py -> _harness_impl.py`;
- `work.py -> _work_impl.py` resolver monkeypatching;
- `learning.py -> _learning_impl.py` compatibility facade;
- old Codex top-level runtime re-exports;
- legacy Scout/fallback entrypoints now superseded by Provider-bound governed execution.

Classify each compatibility surface as:

1. external caller still exists -> keep a thin documented shim;
2. only internal tests call it -> migrate tests/callers, then retire;
3. no caller exists -> remove.

### Hard rule

Do not introduce `_harness_v63_impl.py` as the next permanent layer.

New V6.3 semantic coordinators should call authoritative domain transactions directly.

---

## 13. Minimal telemetry

Telemetry exists to prove whether complexity paydown actually reduced cost, not to build an observability platform.

A lightweight Harness-owned record may count:

- Harness CLI invocations;
- high-level transaction invocations;
- Scout runs by role/capability grade;
- Reviewer runs;
- mechanical review reuses;
- Sitter-owned subprocess launches;
- process spawn/exit failures;
- transaction wall-clock duration;
- optionally provider token usage only when the Provider supplies trustworthy structured metrics.

Do not persist prompts, model transcripts, or large tracing payloads merely for telemetry.

---

## 14. Proposed V6.3 implementation slices

These slices are intentionally narrower than earlier Adaptive Governance proposals.

### V6.3-A — Surface and orchestration compression

- batch candidate evidence;
- true `prepare-candidate` coordinator;
- batch final verification;
- `complete-after-approval` coordinator;
- remove normal-path status polling and explicit low-level lifecycle composition;
- automate no-op Learning/Knowledge steps.

Primary goal: visible token/CLI/latency reduction without assurance changes.

### V6.3-B — Semantic workspace boundary and review reuse

- minimal `production / evidence / task-output / harness` classification;
- conservative exact-output declarations;
- Production Snapshot / Change Budget integration;
- assurance artifact hash binding;
- narrow mechanical review reuse;
- ambiguous cases -> FULL Reviewer.

Primary goal: prevent unrelated workspace artifacts from invalidating production assurance while preserving conservative safety.

### V6.3-C — State/process debt paydown

- derive the clearest duplicate completion fields;
- lazy projections;
- shared workspace capture;
- in-process validation where equivalent;
- failure taxonomy;
- minimal usage telemetry.

Primary goal: reduce internal synchronization and Windows process overhead.

### V6.3-D — Compatibility paydown

- inventory old facades and re-exports;
- migrate internal callers/tests to authoritative APIs;
- retire dead compatibility surfaces;
- keep only proven external shims;
- flatten Harness CLI implementation rather than adding a new version layer.

Primary goal: prevent Sitter itself from becoming an accumulated legacy system.

These slices may be adjusted after implementation inspection, but the Constitution and Asset Register should remain more stable than the release plan.

---

## 15. Explicit non-goals for V6.3

Unless new evidence demonstrates a real independent need, V6.3 should not introduce:

- a second Work Graph or Lite lifecycle;
- a new persisted engineering-complete lifecycle;
- a general Artifact Ownership framework with broad policy schema;
- extension-based global ignores;
- a generic Delta Review dependency engine;
- new Memory or Learning databases;
- a Provider rewrite;
- cross-Provider Task transfer or mixed orchestration;
- weakened Reviewer independence or runtime attestation;
- weaker numerical evidence requirements;
- automatic lowering of Change assurance when current work risk falls;
- silent Knowledge defer, silent cleanup deletion, or tolerance waivers;
- a per-turn Skill-loaded state machine to fight Provider behavior;
- a multi-agent scheduler or maximum-parallelism policy;
- policy/document expansion whose only effect is to give the parent Agent more text to read.

---

## 16. Acceptance criteria

Complexity paydown is successful only if both sides of the equation are proven.

### Core behavior preserved

A fresh-session regression suite should prove:

- active long Task continuity still works;
- Investigation evidence and unknowns survive;
- Human Decision Authority still stales inconsistent downstream proof;
- Memory freshness/conflict behavior still works;
- required Scout independence still works;
- LOW requests remain outside heavy governance;
- unit-only numerical Candidate remains invalid where representative evidence is required;
- independent Candidate Review remains Provider-bound and attested;
- Candidate Human Stop remains intact;
- Final Verification remains post-approval;
- archived review/evidence provenance remains replayable.

### Cost reduced

Real governed acceptance should compare baseline and candidate using the same engineering task and controls, measuring at minimum:

- Harness interactions / CLI calls;
- Reviewer runs;
- Scout runs;
- parent-facing governance text/actions;
- Sitter-owned subprocess count;
- transaction/closure duration;
- avoidable retries;
- provider token usage where trustworthy metrics are available.

A V6.3 change that adds internal concepts without reducing measured cost or improving a core guarantee should be treated skeptically.
