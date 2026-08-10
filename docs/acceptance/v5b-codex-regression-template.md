# V5-B Codex Preservation Regression

## Status

- Result: `PENDING`
- Acceptance date:
- Tester:
- Harness commit:
- Codex version:
- OS:
- Project/worktree:

This report proves that adding Claude Code did not weaken or reinterpret the V5-A Codex Provider.

## 1. Automated gates

- [ ] Ubuntu GitHub Actions passed.
- [ ] Windows GitHub Actions passed.
- [ ] V4.1 source blob baseline passed.
- [ ] V4.1 installed projection byte baseline passed.
- [ ] PowerShell acceptance scripts parsed.
- [ ] Codex static regression passed from outside the Harness cwd.

Workflow run / commit:

```text

```

## 2. Installation preservation

```powershell
python install.py --project <root> --trust-project
python check.py --project <root>
python runtime\self_check.py --project <root>
```

- [ ] Fresh default install remains Codex-only.
- [ ] `AGENTS.md`, `.codex/config.toml`, six Agent TOMLs, and skill wrappers match V5-A defaults.
- [ ] No Claude projection is created by a default install.
- [ ] Existing Codex trust aliases remain valid.
- [ ] Reinstall/update preserves `.agent-work`, `changes`, and user-owned local model configuration.
- [ ] Projection drift is detected and repaired only by explicit update.

## 3. Legacy compatibility

- [ ] A Task without `execution.orchestrator_provider` is interpreted as Codex.
- [ ] Existing `luna / terra / sol` request and attestation artifacts remain readable.
- [ ] Existing Codex CLI paths still work.
- [ ] Existing native error messages and collector identities are preserved.
- [ ] Existing managed App Server execution records the same truthful execution type.

Evidence refs:

```text

```

## 4. Native Codex runtime

- [ ] Agent profile is actually bound, not merely discoverable.
- [ ] `fork_turns: none` is explicit.
- [ ] Exactly one spawn call binds one child thread.
- [ ] Child and parent thread IDs are present and distinct.
- [ ] Actual model and reasoning effort match the frozen request.
- [ ] Sandbox is read-only.
- [ ] cwd is the project root.
- [ ] Combined rollout/App Server evidence is complete.

## 5. Managed Codex runtime

- [ ] Managed execution uses a new independent App Server thread.
- [ ] Parent/fork references are absent.
- [ ] Sandbox is read-only and network is disabled.
- [ ] Request/profile/developer-instruction hashes match.
- [ ] Workspace-write mutation is rejected.
- [ ] Managed success is not used to infer native model support.

## 6. Configurable model selectors

Use a disposable project-local override.

- [ ] A new, previously unknown Codex selector changes the generated Agent TOML without Python changes.
- [ ] Role effort override changes only the native effort field.
- [ ] Effective selector-to-grade mapping reaches native and managed attestation.
- [ ] Unsupported native selector is reported by capability/runtime evidence, not silently replaced.
- [ ] Restoring the default configuration restores the frozen V5-A projection bytes.

## 7. Representative workflow regression

- [ ] Simple Task.
- [ ] Investigation with evidence/claim/decision.
- [ ] Context Scout delegation.
- [ ] HIGH-risk fixture and human checkpoint.
- [ ] Investigation-to-Change pivot.
- [ ] Stronger-model escalation.
- [ ] Knowledge legacy diagnose.
- [ ] Review and archive gates.
- [ ] Final tracked `git status --short` is unchanged.

## 8. Final decision

- Overall result: `PENDING`
- Regressions found:
- Accepted limitations:
- Follow-up changes required:
- Tester signature/date:
