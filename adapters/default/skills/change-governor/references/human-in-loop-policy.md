# Human-in-the-loop Policy

The default operating mode is **guided autonomy**: preserve long uninterrupted execution, but never let the Agent silently choose important algorithmic or engineering semantics.

## Modes

- `autonomous`: the user explicitly delegates all currently identified design choices within the approved scope. Critical-surface and approval gates still apply.
- `guided`: the default for HIGH/CRITICAL work. The Agent batches material decisions into one design checkpoint before implementation.
- `manual`: the user wants approval at each major design transition. Use only when explicitly requested or when unresolved safety/engineering risk demands it.

Do not interpret silence as `autonomous` for HIGH/CRITICAL work.

## What requires a user decision

A decision checkpoint is required when the task has two or more materially plausible choices involving any of the following:

- governing equations, algorithms, convergence strategy or numerical approximation;
- state variables, trial/committed state, cache invalidation or lifecycle ownership;
- loading, unloading, reloading, yielding, gap/contact opening/closing or path dependence;
- coordinate systems, directions, signs, units, result conventions or error tolerances;
- interface contracts, responsibility ownership or dependency direction;
- compatibility behavior, fallback, silent default or degradation strategy;
- acceptance criteria that change external displacement, reaction, force, stress or persisted state;
- an accuracy, performance, maintainability or commercial-software-compatibility trade-off.

Routine implementation details do not require interruption when they are already implied by the approved design and existing framework conventions.

## Batching and interruption budget

The Agent should investigate first, then ask one compact batch of high-leverage questions. Each question must contain:

1. the concrete decision;
2. the viable options and their observable consequences;
3. the Agent's recommendation and evidence;
4. the default that would be used if the user explicitly delegates the choice.

For a normal HIGH/CRITICAL task, use at most one pre-implementation design checkpoint. Ask again only if new evidence invalidates an approved decision or requires a scope expansion.

## Required artifact state

`human_in_loop` records:

- selected mode;
- whether material decision points were assessed;
- why confirmation is or is not required;
- each decision ID, question, options, recommendation, user decision and evidence;
- whether all required decisions are resolved.

A HIGH/CRITICAL task may not enter implementation while `decision_assessment.status` is `pending` or `required`. A `resolved` status requires every listed decision to contain an explicit user decision and evidence. A `not-required` status requires a concrete reason explaining why no material fork exists.

## Decision authority

Once the user explicitly chooses an option, the **user decision is authoritative project state**. The Agent's earlier recommendation remains historical/advisory context only.

For example, if the Agent recommends A and the user chooses B:

- Design must describe B, not A;
- implementation tasks and production changes must implement B;
- Verification must test B's promised behavior;
- Reviewer must judge the work against B and BLOCK a silent return to A;
- Knowledge, Open Threads, Watchpoints, and other durable Memory must preserve B as the decision unless the user explicitly reconsiders it.

Do not reinterpret a recommendation as the decision. Do not silently supersede, normalize, or "improve" the user's choice because the Agent still prefers another option.

New V6 Changes use `decision_authority_protocol: 1`. Review packets freeze a compact projection containing only decision ID, question, `user_decision`, and evidence; recommendations are deliberately excluded. If the authoritative decisions change after review starts, that review is stale and must be repeated. Durable Knowledge candidates are likewise bound to the current decision digest before promotion.

This authority check is mechanical provenance, not a claim that a validator can semantically understand arbitrary Markdown or source code. Black-box acceptance must still test whether the Agent follows the user's decision in Design and implementation behavior.

## Reviewer responsibility

The Reviewer must check whether the implementation contains an unrecorded material semantic decision. Missing algorithm/state/acceptance decisions are Architecture or Numerical Evidence findings, not mere documentation issues.

For a V6 review, the `decision_authority` projection in the frozen review request is authoritative. If Design, diff, Verification, or proposed durable Memory contradicts it, return BLOCK even if the contradictory behavior matches the Agent's earlier recommendation.

## Long-term evaluation

Record cases where the checkpoint was unnecessary, too late, or missed an important decision. The goal is not maximum interruption or maximum autonomy; it is the smallest amount of human input that prevents semantic black boxes and misaligned designs.
