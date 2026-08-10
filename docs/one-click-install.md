# One-click Harness install and upgrade

Use `scripts/install-or-update-harness.ps1` to install the current Harness into a new Git project or upgrade an existing Harness installation.

The script performs the complete guarded flow:

```text
update Harness source branch
→ install Python requirements
→ run Harness repository tests
→ dry-run the target installation
→ reinstall the managed mirror and projections
→ run check.py and self_check.py
→ verify work and delegation CLIs
→ compare source and installed versions
→ verify tracked target-project status did not change
```

It uses `install.py --reinstall`, so the same command works for both first-time installation and an existing managed Harness. The installer preserves `.agent-work/`, `changes/`, production code, and other non-managed project files.

## Existing Git project

Run from any PowerShell working directory:

```powershell
powershell -ExecutionPolicy Bypass -File `
  E:\code\Harness\sitter\scripts\install-or-update-harness.ps1 `
  -ProjectRoot E:\code\Refactor\dev
```

Defaults:

- update the Harness source repository to `master` with `git pull --ff-only`;
- install or upgrade with `--reinstall`;
- trust the target Git common root for Codex;
- run all Harness tests before installation;
- refuse to continue when the Harness source repository has local changes;
- refuse any change to the target project's tracked Git status.

After success, close existing Codex sessions and start a new session from the target project root.

## New project directory

To create a missing directory and initialize it as a Git repository:

```powershell
powershell -ExecutionPolicy Bypass -File `
  E:\code\Harness\sitter\scripts\install-or-update-harness.ps1 `
  -ProjectRoot E:\code\NewProject `
  -InitializeGit
```

The script does not create an initial commit or add project files.

## Existing unmanaged AGENTS.md or Codex projections

The installer normally refuses to overwrite files that it cannot prove are Harness-managed. After reviewing the dry-run and deciding that Harness should take ownership, run:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\install-or-update-harness.ps1 `
  -ProjectRoot E:\code\Refactor\dev `
  -AdoptExisting
```

The installer backs up adopted entrypoints below the installed Harness mirror.

## Explicitly untrusted project

A prior explicit `untrusted` entry is not overwritten by the normal flow. Only after deciding to reverse that prior security decision, use:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\install-or-update-harness.ps1 `
  -ProjectRoot E:\code\Refactor\dev `
  -ForceTrustProject
```

## Useful options

| Option | Meaning |
| --- | --- |
| `-HarnessBranch <name>` | Update and install from another Harness branch; default is `master`. |
| `-PythonCommand <path>` | Use a specific Python executable; default is `python`. |
| `-InitializeGit` | Create a missing target directory and initialize Git when needed. |
| `-SkipSourceUpdate` | Use the current local Harness checkout without switching or pulling. |
| `-SkipHarnessTests` | Skip repository unit tests; installation checks still run. |
| `-AdoptExisting` | Explicitly back up and replace unmanaged Harness entrypoints. |
| `-ForceTrustProject` | Override a prior explicit Codex `untrusted` decision. |
| `-NoTrustProject` | Install without modifying user-level Codex trust configuration. |

`-ForceTrustProject` and `-NoTrustProject` cannot be combined.

## Safety behavior

The script stops when:

- `ProjectRoot` is not the exact Git worktree root;
- the Harness source repository has local changes while source update is enabled;
- `git pull --ff-only` cannot update the selected Harness branch;
- Harness tests fail;
- installation dry-run or actual installation fails;
- installation or self-check fails;
- the installed version differs from the source manifest version;
- the target project's tracked Git status changes during installation.

Untracked Harness projections are excluded locally by the installer. Existing tracked project changes are allowed, but their exact status must remain unchanged across the operation.
