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

## Reviewer responsibility

The Reviewer must check whether the implementation contains an unrecorded material semantic decision. Missing algorithm/state/acceptance decisions are Architecture or Numerical Evidence findings, not mere documentation issues.

## Long-term evaluation

Record cases where the checkpoint was unnecessary, too late, or missed an important decision. The goal is not maximum interruption or maximum autonomy; it is the smallest amount of human input that prevents semantic black boxes and misaligned designs.
