# V5-B Dual Provider Coexistence Acceptance

## Status

- Result: `PENDING`
- Acceptance date:
- Tester:
- Harness commit:
- Codex version:
- Claude Code version:
- OS:
- Project/worktree:

## 1. Dual installation

```powershell
python install.py --project <root> `
  --provider codex `
  --provider claude `
  --trust-project
python check.py --project <root>
python runtime\self_check.py --project <root>
```

- [ ] `enabled_providers` contains exactly `codex` and `claude`.
- [ ] Every projection has one owner.
- [ ] Codex owns no `.claude` path.
- [ ] Claude owns no `.codex`, `.agents`, or `AGENTS.md` path.
- [ ] Exact, case-folded, and ancestor ownership conflicts are rejected before writing.
- [ ] `.claude/settings.local.json` remains user/Claude-owned and absent from the manifest.
- [ ] Local model override is excluded and never overwritten.

## 2. Transactional replacement behavior

- [ ] Existing Codex-only install can add Claude with `--enable-provider claude`.
- [ ] Ordinary install with no Provider arguments preserves the installed Provider set.
- [ ] Removing an installed Provider through install is rejected.
- [ ] Claude enable/update leaves frozen default Codex projections unchanged.
- [ ] Codex update leaves Claude projections unchanged.
- [ ] V4.1 managed installation can be replaced directly without per-version migration.
- [ ] `.agent-work`, `changes`, `knowledge`, local model configuration, production source and user files are preserved.
- [ ] Injected failure restores mirror, managed projections and Git exclude.

Evidence refs:

```text

```

## 3. Immutable Task binding

Create two Tasks:

```powershell
python runtime\create_task.py codex-task --provider codex ...
python runtime\create_task.py claude-task --provider claude ...
```

- [ ] Codex Task request uses only the Codex Provider profile.
- [ ] Claude Task request uses only the Claude Provider profile.
- [ ] Task Provider cannot be changed after creation.
- [ ] Delegation CLI has no per-attempt Provider override.
- [ ] Supplemented attempt preserves the original Provider and frozen profile.
- [ ] Stronger-model escalation stays within the Task Provider.

## 4. Cross-Provider rejection

- [ ] Claude attestation cannot complete a Codex request.
- [ ] Codex attestation cannot complete a Claude request.
- [ ] Managed/native evidence sources cannot be substituted within either Provider.
- [ ] Claude Task cannot invoke a governed Codex child.
- [ ] Codex Task cannot invoke a governed Claude child.
- [ ] Mixed-provider orchestration is rejected by the formal runtime/CLI boundary.

## 5. Same-project runtime proof

Run one completed governed delegation for each Provider without reinstalling between them.

| Task | Provider | Role | Execution | Actual model | Result | Evidence |
|---|---|---|---|---|---|---|
| | codex | | native/managed | | PENDING | |
| | claude | | native/managed | | PENDING | |

- [ ] Both results remain independently attributable.
- [ ] Their raw evidence uses Provider-native collector names.
- [ ] Normalized Core evidence uses the same Provider-neutral contract vocabulary.
- [ ] No result or attestation file is shared between Tasks.

## 6. Linked-worktree and settings ownership

| Scenario | Expected | Result | Evidence |
|---|---|---|---|
| Fresh Claude install | no Harness-created `.claude/settings.local.json` | PENDING | |
| Existing main-checkout user settings | byte-for-byte preserved | PENDING | |
| Existing linked-worktree user settings | byte-for-byte preserved | PENDING | |
| Governed settings | present only inside Harness mirror | PENDING | |
| User settings in manifest | absent | PENDING | |
| Failure during install | user settings remain untouched | PENDING | |

## 7. Final repository state

- [ ] `check.py` passes and validates both enabled Providers.
- [ ] `self_check.py` validates both Providers.
- [ ] Codex capability/runtime evidence is current.
- [ ] Claude managed capability report is current.
- [ ] No production source file changed during acceptance.
- [ ] Final tracked `git status --short` equals the initial tracked state.

## 8. Final decision

- Overall result: `PENDING`
- Blocking findings:
- Accepted limitations:
- Follow-up changes required:
- Tester signature/date:
