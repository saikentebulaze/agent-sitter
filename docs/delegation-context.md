# Delegation Context Protocol

Sitter Harness v4.1 uses a frozen delegation request packet instead of copying the parent conversation into a child Agent.

## Core rule

```text
Static role instructions
+ role-specific frozen Context Capsule
+ evidence pulled by reference
+ exact child output
+ verified runtime attestation
+ parent-controlled promotion
```

All current Sitter child roles are read-only and require:

```yaml
context_policy:
  inheritance: none
```

The parent Agent owns Task, Investigation, and Change writes. A child Agent may only read its request packet and the bounded authority references in that packet.

## Installed runtime path

The Harness runtime is installed below the project worktree. Do not assume that a project-root `runtime/` projection exists.

```powershell
$ProjectRoot = (Get-Location).Path
$HarnessRoot = Join-Path $ProjectRoot ".harness\sitter"
$Runtime = Join-Path $HarnessRoot "runtime"
```

All examples below invoke scripts through `$Runtime`.

## Authorize delegation

```powershell
python "$Runtime\work.py" --project <root> authorize-delegation <task-id> `
  --decision required `
  --scope readonly-exploration `
  --scope readonly-review `
  --evidence "user authorized read-only subagents for this task" `
  --parent-model gpt-5.6-terra `
  --parent-tier terra
```

Model-tier elevation remains governed by `task.yaml#delegation.model_budget`.

## Request a child Agent

```powershell
python "$Runtime\work.py" --project <root> request-delegation <task-id> `
  --role context_scout `
  --target-type change `
  --target-ref <change-id> `
  --purpose "trace the bounded ownership chain" `
  --question "Does Contact duplicate MPC responsibilities?" `
  --decision-supported "Decide whether the approved responsibility boundary must change." `
  --include AnalysisContact `
  --include AnalysisMpcConstraint `
  --exclude friction-redesign `
  --start-ref src/analysis/analysis_contact.cpp
```

The command:

- loads the role's requested model, reasoning effort, and sandbox from its Agent TOML;
- allocates a stable `dlg-NNN`;
- generates `.agent-work/<task>/delegations/<dlg>/attempt-01.request.yaml`;
- applies a role-specific Change/Investigation projection;
- freezes the relevant authority inputs;
- records the planned delegation in `task.yaml`.

## Execution modes

Two execution modes are explicit and auditable.

### Native MultiAgentV2

Use this only when the runtime attestation proves that the native child actually received the requested sandbox.

Generate the exact native spawn contract:

```powershell
python "$Runtime\delegation_runtime.py" --project <root> `
  spawn-contract <task-id> <dlg-id>
```

The result contains:

```json
{
  "tool": "spawn_agent",
  "task_name": "sitter_dlg_001_a1_<project-task-hash>",
  "agent_type": "context_scout",
  "fork_turns": "none",
  "message": "Read and follow: ..."
}
```

Use those values unchanged. Omitting `fork_turns` is forbidden because MultiAgentV2 defaults the omitted value to full-history inheritance.

After the native child finishes:

```powershell
python "$Runtime\delegation_runtime.py" --project <root> `
  collect-attestation <task-id> <dlg-id>
```

The collector:

1. obtains the local Codex home from App Server initialization;
2. finds exactly one persisted `spawn_agent` request for the deterministic task name;
3. verifies the expected `agent_type` and `fork_turns: none`;
4. binds the spawn call ID to the child UUID through persisted `sub_agent_activity`;
5. calls `thread/read` for parent/child/role metadata;
6. calls metadata-only `thread/resume` for actual model, effort, sandbox, cwd, and permission information;
7. writes sanitized evidence and an attestation beside the frozen request;
8. rejects missing, ambiguous, stale, or mismatched evidence.

Record only after attestation succeeds:

```powershell
python "$Runtime\delegation_runtime.py" --project <root> `
  record-result <task-id> <dlg-id> `
  --artifact <exact-child-output> `
  --outcome completed
```

### Harness-managed App Server isolation

This is the controlled read-only path when native MultiAgentV2 inherits a broader parent permission profile.

Run the frozen request in a new App Server thread:

```powershell
python "$Runtime\delegation_runtime.py" --project <root> `
  run-isolated <task-id> <dlg-id>
```

The Harness calls `thread/start` with:

- the exact Agent TOML model;
- the exact Agent TOML developer instructions;
- `sandbox: read-only`;
- `approvalPolicy: never`;
- the project cwd and runtime workspace root;
- no parent thread and no forked history.

It then calls `turn/start` with the exact reasoning effort and an explicit `readOnly` sandbox policy, waits for `turn/completed`, and checks metadata-only `thread/resume` before accepting the output.

Generated artifacts:

```text
.agent-work/<task>/delegations/<dlg>/attempt-N.result-candidate.md
.agent-work/<task>/delegations/<dlg>/attempt-N.runtime-attestation.yaml
.agent-work/<task>/delegations/<dlg>/attempt-N.runtime-evidence.json
```

The managed attestation must prove:

- execution type `app-server-isolated-agent`;
- a new thread with no `parentThreadId` and no `forkedFromId`;
- exact Agent TOML binding through the profile file and developer-instruction hashes;
- actual model and reasoning effort returned by App Server;
- actual `read-only` sandbox in both `thread/start` and `thread/resume`;
- expected project cwd;
- exact `thread/start` and `turn/start` request hashes.

After reviewing the candidate output, record it:

```powershell
python "$Runtime\delegation_runtime.py" --project <root> `
  record-isolated-result <task-id> <dlg-id> `
  --outcome completed
```

The Task records the truthful execution type:

```yaml
execution: app-server-isolated-agent
```

It is never mislabeled as a native subagent.

## Runtime artifacts and result ownership

Both execution modes use schema-version-2 runtime attestations. A legacy or manually authored schema-version-1 profile copy is rejected.

A child result never modifies an Investigation or Change automatically. The parent reviews it and explicitly records accepted Evidence, Claims, Decisions, tests, or design changes through the existing governed commands.

If a frozen authority input changed, the exact output is preserved but the delegation is recorded as `stale`; it cannot enter `delegation.completed`.

## Codex 0.146.0 native permission limitation

The local Codex 0.146.0 probe established that native MultiAgentV2 correctly applied the Locator model and reasoning effort, but the child inherited the parent turn's live permission profile after role configuration. With a normal workspace-write parent, the observed child sandbox was:

```json
{
  "type": "workspaceWrite",
  "writableRoots": [],
  "networkAccess": false
}
```

The App Server also returned the project as a runtime workspace root. This is not equivalent to read-only.

Therefore:

- the native collector reports `workspace-write` exactly as observed;
- a read-only Sitter role fails native attestation under that state;
- an empty `writableRoots` array is not reinterpreted as read-only;
- developer instructions saying "do not modify files" are not sandbox enforcement;
- the Harness does not silently accept or downgrade the mismatch;
- use `run-isolated` for a separately attested read-only execution.

## Bounded context supplement

A child may return `NEED_CONTEXT` with one concrete blocking question and its prior search scope. Record that result only after runtime attestation succeeds, then add only the missing references:

```powershell
python "$Runtime\work.py" --project <root> `
  supplement-delegation-context <task-id> <dlg-id> `
  --ref src/nonlinear/constraint_updater.cpp `
  --reason "contains the missing activation lifecycle"
```

The Harness creates a new immutable attempt. It does not overwrite attempt 1. At most two context supplements are allowed by the default role policy.

## Role projections

- Locator: scope and exact search anchors; no full Design.
- Context Scout: Change lifecycle, risk, budget, relations, Proposal and Design references.
- Test Scout: behavior contract, verification, critical surfaces, and test-facing references.
- Framework Scout: cross-module constraints, relations, decisions, and design references.
- Maintainer Reviewer: frozen production artifacts without parent self-review or desired outcome.
- Deep Reviewer: broader evidence and decision context, still without parent preference.

Existing `harness review` and stronger-model review commands keep their current external interfaces in v4.1. They will be migrated to the common packet builder only after the generic delegation runtime is proven in a real Sitter worktree.
