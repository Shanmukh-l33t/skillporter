# Synchronization

`skillporter sync` makes the workspace match the manifest and the lockfile. It is the command you run after cloning a repository, after changing `skillporter.yaml`, and after a skill copy has been edited by hand.

```bash
skillporter sync
```

## What sync does

1. Reads `skillporter.yaml`. If there is no manifest, it mirrors the skills it discovers across the active harnesses.
2. Resolves each skill's source. When the lockfile has a `resolved_commit`, that exact commit is used, even if the branch has moved.
3. Verifies fetched content against the locked `tree_hash`.
4. Runs the static security assessment.
5. Installs missing copies and leaves identical ones alone.
6. Writes `skillporter.lock`.

The output states what happened for each harness. This excerpt is abridged and the workspace path is shortened:

```text
$ skillporter sync
wrote ~/acme-api/skillporter.lock (1 locked skill(s))
unchanged antigravity      ~/acme-api/.agents/skills/skillporter
created   claude-code      ~/acme-api/.claude/skills/skillporter
unchanged codex            ~/acme-api/.agents/skills/skillporter
unchanged cursor           ~/acme-api/.agents/skills/skillporter
```

Preview without writing:

```bash
skillporter sync --dry-run
```

## Drift

Drift means two copies of the same skill have different content. It usually happens when someone edits `.claude/skills/<skill>` and forgets the copy in `.agents/skills/<skill>`. Different harnesses then run different instructions.

`skillporter diagnose` detects drift by hashing every copy. Abridged output:

```text
$ skillporter diagnose . --harness claude-code --harness codex --harness cursor
SKILL  claude-code     codex           cursor
-----------------------------------------------------
pdf    DRIFT           DRIFT           DRIFT

findings:
  - skill 'pdf' has content drift across copies: .agents/skills/pdf (6b86f0c7), .claude/skills/pdf (e08dcf6f)
```

## Sync never guesses

When copies differ, a plain `sync` stops. It will not pick a winner or overwrite your edit without being told to. Output with the workspace path shortened:

```text
$ skillporter sync
error: on-disk skill content differs from skillporter.lock; refusing to re-lock without --force:
  - pdf (~/acme-api/.claude/skills/pdf): locked 6b86f0c7 != disk e08dcf6f
```

You have two ways forward.

**Name the authoritative copy.**

```bash
skillporter sync --force --prefer .agents/skills/pdf
```

**Let Skillporter use the most recently modified copy.**

```bash
skillporter sync --force
```

If two copies have the same modification time, Skillporter asks for `--prefer` and does not choose.

Either way, the copies that are about to be replaced are snapshotted to `.skillporter/backups/` first, so `skillporter rollback <skill>` can restore them.

## Repairing a workspace

```bash
skillporter doctor .
skillporter doctor --fix
```

`doctor` reports each skill's state per harness. `--fix` removes broken symlinks and synchronizes missing or drifted installs. `--dry-run` shows what it would change.

## Limiting the scope

```bash
skillporter sync --harness claude-code --harness codex
skillporter sync --scope user
```

## Security gates still apply

`sync` runs the same assessment as `add`. A blocking finding stops the sync. `--max-risk-score` sets a threshold for one run, `--allow-risky` accepts non-structural findings, and `--force` only concerns overwriting.

## Concurrent runs

`sync` and `lock` take a cross-process workspace lock. Two runs in the same workspace wait for each other and do not interleave writes.

## Typical team setup

1. One person runs `skillporter init` and `skillporter sync`, then commits `skillporter.yaml` and `skillporter.lock`.
2. Everyone else runs `skillporter sync` after pulling.
3. CI runs `skillporter lock --check` and `skillporter scan .`.

See [Lockfiles](../lockfiles/README.md) for the file format and [Troubleshooting](../troubleshooting/README.md) for specific states.
