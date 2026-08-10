# Dynamic Risk Lifecycle

Risk is a runtime routing signal, not a permanent label attached at Task creation.

## Three meanings

- `task.work_risk.current`: risk of the next engineering work. May increase or decrease.
- `task.work_risk.peak`: historical maximum execution risk. Automatically increases and never automatically decreases.
- `change.risk`: Production Change assurance floor. Verification and independent review follow this value, not current cleanup risk.

## Increase quickly

Reassess upward as soon as new facts materially expand uncertainty or engineering consequence. Typical triggers include:

- new user requirements or scope expansion;
- an unexpected test/calculation/runtime result;
- unknown root cause requiring Investigation;
- temporary diagnostic probes/tests becoming necessary;
- new/changed state, cache, lifecycle, ordering, ownership, interface, or responsibility;
- path dependence or cross-case/step inheritance;
- coordinates, direction, sign, units, tolerance, solver or numerical semantics;
- multiple plausible product/engineering interpretations;
- a previously assumed requirement or architecture fact proving false.

Risk escalation itself does not need user approval. Material engineering choices discovered by the escalation may require a Human Checkpoint.

When an increased execution risk also represents the minimum proof required for the active Production Change, raise Change assurance in the same reassessment. Do not raise Change assurance merely because an unrelated Investigation was difficult.

## Decrease conservatively

Current risk may decrease when the unknown engineering surface has actually closed. A decrease requires:

- no open Investigation;
- no active stronger-model/human/blocking escalation;
- no unresolved material human decision;
- remaining work is explicitly bounded and does not introduce new state/interface/responsibility/semantic choices.

Typical low-risk tail work includes deleting diagnostics, final test cleanup, comments, naming, documentation sync, or other mechanical completion work after the design and behavior are stable.

Lowering current risk never lowers `task.work_risk.peak` or `change.risk`.

## Assurance reduction

Production assurance is intentionally harder to reduce than execution risk. Do not reduce `change.risk` as part of ordinary risk reassessment. A future explicit assurance-reassessment transaction may lower it only when durable evidence shows the final production deliverable is genuinely lower risk, for example when an apparently critical solver problem is proven to be invalid test input and no production behavior changes.

## Follow-up turns

Reassess incrementally. A follow-up naming request normally leaves risk unchanged. A new request to preserve state across analysis steps may immediately raise risk. Do not restart the entire governance process when the new turn does not materially change the engineering surface.
