# Evidence-Gated Learning Incubator

The Harness must automatically consider reusable experience without automatically turning every observation into permanent memory, tooling, knowledge or Skills.

## Operating rule

- Automatic: intake search, observation capture, deduplication, recurrence counting, closeout assessment and review-packet generation.
- User-gated: promotion into tools, Skills, authoritative knowledge, policy, user-level configuration or Harness code.
- A user must not need to remind Codex to run intake, record a repeated pitfall, perform closeout or present a mature candidate.

## Candidate store

Project-local candidates live at:

```text
.agent-work/_learning/inbox.yaml
```

This file is local governance state, not authoritative project knowledge. It is ignored through the worktree's `.git/info/exclude` together with `.agent-work/`.

Candidate scopes:

- `project`: project-specific facts, procedures or tools;
- `user-environment`: machine, shell, encoding, path or personal workflow behavior;
- `harness`: defects or reusable improvements in the Harness itself.

User-environment candidates are first staged inside the project. Writing outside the project requires a later explicit promotion approval.

## Lifecycle

```text
observed -> watching -> ready-for-review -> approved -> promoted
                     \-> dismissed
observed/watching -> stale
```

A candidate reaching `ready-for-review` must be proactively presented by Codex before task completion. Approval only authorizes a governed promotion proposal; it does not itself create the final asset.

## What to capture

Capture observations that caused meaningful retry cost, corrected an Agent assumption, exposed a stable tooling gap, revealed a recurring environment/path/encoding issue, or showed that an existing Skill or policy is inadequate.

Do not capture ordinary typos, trivial one-off syntax mistakes, unverified guesses, or low-value narration.

## Promotion preference

1. Deterministic inputs and outputs: program or tool.
2. Stable fact: project knowledge or environment configuration.
3. Reusable contextual judgment: Skill.
4. Governance invariant: policy plus Validator when enforceable.

"Can be implemented deterministically" is a strong reason not to spend model tokens repeating the procedure.

## Default readiness thresholds

- General pitfall: at least three occurrences across at least two tasks with a consistent root cause.
- Deterministic tool: verified successful workaround at least twice across at least two tasks.
- Skill: repeated successful use across multiple task classes, a real need for model judgment, and no existing Skill that covers it.
- Safety, data loss, project-external writes, credential exposure, silent numerical error or false validation: immediate review candidate.

Frequency alone is not enough; the review packet must state root-cause confidence, expected benefit, maintenance cost and why the recommended target is preferable to alternatives.

## Required task lifecycle

### Intake

Before leaving `intake`, run the learning intake command and load only the most relevant entries and approved tools. Do not inject the whole Inbox into model context.

### Execution

Use deterministic tools when an approved matching tool exists. Record meaningful new observations and update existing signatures rather than creating duplicates.

### Closeout

Before `review` or `completed`, run learning closeout. If no observation exists, provide a concrete reason. Mature candidates set `user_attention.required: true`.

### User attention

Mature candidates must be presented in one compact batch, normally at task closeout. The user may approve, defer or dismiss. Codex must not invent or infer the user's decision.

## Self-modification boundary

The Harness may observe problems in itself and recommend a Harness Change. It may not silently modify its own policy, runtime, prompts or Agent defaults based on a candidate entry.
