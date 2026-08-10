# Reasoning Budget Policy

Model tier and reasoning effort are independent budget dimensions. The Governor must choose the lowest reliable pair rather than treating model selection alone as the cost control.

## Default roles

| Role | Model | Default effort | Use |
| --- | --- | --- | --- |
| `source_locator` | GPT-5.6 Luna | low | exact files, symbols, callers, tests and named log evidence |
| `context_scout` | GPT-5.6 Luna | medium | business chains, data flow and state lifecycle |
| `test_scout` | GPT-5.6 Luna | medium | evidence meaning, tolerance and regression risk |
| `framework_scout` | GPT-5.6 Terra | medium | framework ownership and cross-module semantics |
| `maintainer_reviewer` | GPT-5.6 Terra | medium | normal independent review |
| `deep_reviewer` | GPT-5.6 Sol | high | exceptional CRITICAL escalation |

Use Locator for bounded retrieval. Do not spend Context/Test Scout reasoning on work that only needs deterministic search.

## Escalation rules

1. Using the role default effort requires no extra approval beyond normal subagent authorization.
2. A one-step increase that remains at `high` or below may execute without interrupting the user, but the task must record a concrete `effort_reason` and `effort_escalation: recorded`.
3. `xhigh`, `max`, or an increase of two or more effort levels requires explicit user authorization before execution.
4. Model-tier elevation remains a separate approval. General subagent approval does not authorize either a stronger model or exceptional effort.
5. `max` is never a default Agent TOML value.
6. Do not keep increasing Luna effort when the missing capability is architectural or semantic abstraction; route to the appropriate Terra role instead.

## Evidence

Planned and completed entries must both record `reasoning_effort`. Completed evidence must match the approved plan. A configuration file is not execution evidence.

## Cost-quality feedback

When an escalation materially improves or fails to improve the result, record that observation in the Learning Inbox. Repeated evidence may justify changing a role default through a governed Harness Change; one task must not silently rewrite defaults.
