# Sitter Harness v4 work graph

v4 removes the old `mode + phase` task model. There is one runtime model only; no v3 compatibility branch remains in normal commands.

## Objects

- **Task** is the stable engineering-work container. It owns delegation, human checkpoints, learning, current focus, timeline, pivot budget, and escalation.
- **Investigation** stabilizes engineering knowledge. It owns a problem signature, claims, evidence, experiments, decisions, remaining unknowns, and disposition.
- **Production Change** stabilizes production behavior. It retains the existing design, approval, implementation, verification, review, knowledge, and archive lifecycle.

Investigation and Change never mutate into each other. A pivot creates or resumes a related object and records the relation in the Task work graph.

## Entry points

```powershell
python runtime\create_task.py <task-id> --title "..." --entry investigation `
  --question "..." --signature <stable-problem-signature> --project <root>

python runtime\create_task.py <task-id> --title "..." --entry change `
  --change-id <change-id> --change-title "..." --project <root>
```

Task IDs and Change IDs are stable identifiers. A Change ID is unique across `changes/active` and `changes/archive`; creation fails before writing if the ID already exists.

Run learning intake immediately after creation, then validate:

```powershell
python runtime\learning.py --project <root> intake .agent-work/<task-id>/task.yaml
python runtime\validate_task_state.py .agent-work/<task-id>/task.yaml
python runtime\work.py --project <root> validate <task-id>
```

## Investigation records

```powershell
python runtime\work.py --project <root> record-evidence <task> <inv> ...
python runtime\work.py --project <root> record-claim <task> <inv> ...
python runtime\work.py --project <root> record-decision <task> <inv> ...
```

A `supported` claim requires supporting evidence. A `refuted` claim requires contradicting evidence. An accepted decision may only depend on supported claims. A decision marked `requires_human` also requires a resolved Task human decision and durable evidence.

A concluded or closed Investigation is immutable. New facts are represented by a new Investigation or a new superseding record, never by rewriting the evidence chain that already produced a Change.

## Pivots

Investigation to Change:

```powershell
python runtime\work.py --project <root> pivot-to-change <task> <inv> <change-id> `
  --title "..." --rationale "..."
```

Change to Investigation:

```powershell
python runtime\work.py --project <root> investigate-change <change-id> `
  --title "..." --question "..." --signature <signature>
```

The Change is paused while the Investigation is active. Concluding with `resume-change` requires explicit confirmation that scope, design, and approval remain valid.

`revise-change` preserves prior review history and round numbering, archives any pending review request as cancelled, resets stale approval/verification/knowledge/archive state, and returns the Change to design. Existing Reviewer output is never overwritten or renumbered.

## Loop prevention and escalation

One Change-to-Investigation pivot is allowed automatically per Task. A repeated pivot requires a concrete discrimination rationale and creates a blocked Investigation plus a stronger-model review requirement.

The escalated Investigation is stored as a stable target. While stronger-model or human escalation is pending, normal commands cannot create another Investigation, move current focus, mutate evidence, or continue production work.

Model review is a two-step transaction:

```powershell
python runtime\work.py --project <root> request-model-review <task> `
  [--role framework_scout|maintainer_reviewer|deep_reviewer] `
  [--elevated-authorization-ref <ref>]

python runtime\work.py --project <root> record-model-review <task> `
  --artifact <exact-reviewer-output> `
  --outcome supported|inconclusive|block `
  --evidence-ref <native-thread-or-audit-ref>
```

`request-model-review` freezes Task and Investigation hashes and names the read-only Reviewer. `record-model-review` verifies that frozen input, stores the exact returned artifact, records provenance, archives the request packet, and updates escalation atomically. Deep Reviewer requests require explicit elevated-model authorization evidence.

A stronger model outcome of `inconclusive` or `block` automatically creates a human checkpoint and blocks production execution. Only explicit human resolution may continue or stop the work:

```powershell
python runtime\work.py --project <root> resolve-human-checkpoint <task> `
  --action continue --decision "..." --evidence "..."
```

The key invariant is: repeated failure cannot create an autonomous Investigation/Change loop that excludes the human engineer.

## Task completion

Task completion has a controlled write path:

```powershell
python runtime\learning.py --project <root> closeout .agent-work/<task>/task.yaml --reason "..."
python runtime\work.py --project <root> complete-task <task> --rationale "..."
```

The command requires:

- every Investigation is concluded or closed;
- every Change is archived or abandoned;
- no stronger-model, human, or blocked escalation remains;
- Learning Closeout is `assessed`.

The transaction closes concluded Investigations, clears current focus, records the completion event, and validates the completed graph. Manual edits to set `status: completed` are not part of the supported workflow.

## Status

```powershell
python runtime\work.py --project <root> task-status <task-id>
```

This validates the full graph, refreshes `.agent-work/<task-id>/status.md`, and prints a machine-readable summary.
