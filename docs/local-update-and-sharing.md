# Installation, updates, and sharing

Sitter is installed into a target Git repository or Git worktree. The Sitter source checkout and the target project remain separate repositories; installing Sitter does not add Sitter source files to the target project's tracked history.

## Install into a project

Pass the exact Git repository or worktree root to `--project`:

```bash
python install.py --project <project-root> --dry-run
python install.py --project <project-root>
python check.py --project <project-root>
```

Use `--trust-project` when enabling the Codex provider and the project is not already trusted by Codex.

A first install should always be inspected with `--dry-run`. Sitter refuses to overwrite an unmanaged conflicting projection unless an explicit adoption path can prove that the file belongs to an earlier generated installation.

## Provider selection

Fresh installs default to Codex-only.

Claude-only:

```bash
python install.py --project <project-root> --provider claude --dry-run
python install.py --project <project-root> --provider claude
```

Codex + Claude:

```bash
python install.py --project <project-root> --provider codex --provider claude --trust-project --dry-run
python install.py --project <project-root> --provider codex --provider claude --trust-project
```

For an existing Sitter installation, omitting provider arguments preserves the provider set recorded in `manifest-lock.yaml`. Enabling an additional provider is explicit; Sitter does not silently reinterpret the Task provider contract.

## Repositories and worktrees

No extra worktree is required. For an ordinary clone, pass the clone root. For a linked Git worktree, pass that worktree's exact root and install Sitter there explicitly when that worktree needs the projections.

```bash
git worktree list
python install.py --project <worktree-root> --dry-run
```

Do not identify a target by branch name alone: a branch is not a filesystem destination.

## Managed installation layer

Depending on enabled providers, Sitter may manage:

```text
.harness/sitter/
AGENTS.md
.codex/config.toml
.codex/agents/*.toml
.agents/skills/*/SKILL.md
CLAUDE.local.md
.claude/agents/*.md
.claude/skills/*/SKILL.md
.claude/hooks/governance-runtime-hook.py
Sitter-managed blocks in .git/info/exclude
```

The installer records managed projections and their hashes in the local installation manifest. `.git/info/exclude` is edited only inside marked Sitter-owned blocks; the tracked `.gitignore` is not used for local projections.

## Durable project and user state

The following are not part of transactional replacement and must survive Sitter updates:

```text
.agent-work/
changes/
knowledge/
.claude/settings.local.json
.harness/sitter.models.local.yaml
production source code
other user-owned files
```

Claude Code and the user own `.claude/settings.local.json`; Sitter does not create, replace, or delete it.

## Update and drift handling

Use the current Sitter checkout to update a project:

```bash
python install.py --project <project-root> --dry-run
python install.py --project <project-root>
python check.py --project <project-root>
```

The installer computes the current desired state, verifies ownership of the existing managed layer, snapshots what is needed for rollback, replaces managed projections transactionally, and restores the previous managed state if a post-swap operation fails.

`--update` and `--reinstall` remain supported compatibility entry points, but ordinary installation already follows the transactional replacement path.

If a previously managed file no longer matches the recorded hash and ownership cannot be proven safely, Sitter fails instead of silently deleting or overwriting the file.

## Verification

After installation or update, run:

```bash
python check.py --project <project-root>
python <project-root>/.harness/sitter/runtime/self_check.py --project <project-root>
git -C <project-root> status --short
```

`check.py` validates generated projection hashes and provider-owned assets. The installed self-check validates the package from the project-local mirror. Generated local projections should remain excluded from the target repository's normal Git status unless the project intentionally tracks them.

## Sharing

Share the Sitter source repository independently. Each recipient clones Sitter, selects their own target project/worktree, runs a dry-run, and installs the provider set they need. Target-project work records and user settings are not copied from the Sitter source repository.
