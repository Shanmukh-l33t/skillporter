# Skill management

A skill is a directory with a `SKILL.md` file and, optionally, `scripts/`, `references/` and other assets. Skillporter moves that directory from a source into the places your harnesses read, and keeps track of what it wrote.

## Sources

`skillporter add` accepts any of these.

| Source | Example |
|---|---|
| GitHub shorthand | `anthropics/skills` |
| GitHub shorthand with a subpath and ref | `owner/repo/skills/pdf@v1.2.0` |
| GitHub tree URL | `https://github.com/owner/repo/tree/main/skills/pdf` |
| Git URL | `https://example.com/team/skills.git`, `git@example.com:team/skills.git` |
| Local archive | `./release-notes.zip`, `./release-notes.tar.gz` |
| Local directory | `./skills/release-notes` |

Use `--ref` to pin a branch, tag or commit, and `--skill` to pick skills out of a repository that contains several:

```bash
skillporter add anthropics/skills --skill pdf --ref main --harness all
```

Source resolution never executes anything inside the fetched repository or archive. Git clones run with external protocol helpers, filesystem monitors and symlink checkout disabled. Archives are extracted with path, size and file-count limits. See the [security model](../security/README.md).

## What happens during `add`

1. **Resolve.** The source is fetched into a temporary directory and the commit is recorded.
2. **Validate.** Each selected skill is checked against the Agent Skills specification.
3. **Assess.** The static security assessment runs. A blocking result stops here.
4. **Plan.** Destinations are computed per harness. Harnesses that share a directory are deduplicated.
5. **Install.** Files are staged and moved into place as one transaction.
6. **Verify.** The installed copies are checked.

`--dry-run` performs steps 1 to 4 and prints the plan.

## Choosing harnesses

```bash
skillporter add ./skills/release-notes --harness claude-code --harness codex
skillporter add ./skills/release-notes --harness all
```

Without `--harness`, Skillporter uses the harnesses declared in `skillporter.yaml`, or the ones it detects as active in the workspace.

## Copy or symlink

`--strategy copy` is the default. Every destination gets real files, which works inside Docker build contexts, CI checkouts, `git worktree` and Windows clones.

`--strategy symlink` creates relative symlinks to one canonical copy. Edits show up everywhere at once, but the links break wherever symlinks are not preserved.

## Project or user scope

`--scope project` (the default) writes inside the repository, for example `.claude/skills/pdf`. `--scope user` writes to your home directory, for example `~/.claude/skills/pdf`, so the skill is available in every project.

## Adapted rule files

Some harnesses also read rule files in their own format. `--adapt` writes those alongside the skill:

```bash
skillporter add ./skills/release-notes --harness cursor --adapt
```

Preview an adaptation without installing:

```bash
skillporter inspect ./skills/release-notes --preview-adapt cursor-mdc
```

Bundled `scripts/` stay in the skill directory. They are not embedded in the rule file.

## Conflicts and risk are separate decisions

- `--force` answers "may I overwrite what is already there?" It never bypasses a security block.
- `--allow-risky` answers "do I accept these security findings?" The findings are printed and the decision is written to `.skillporter/audit.jsonl`.

Structural escapes, such as a symlink that points outside the skill or a path traversal entry, cannot be accepted with either flag.

## Removing a skill

```bash
skillporter remove pdf --harness cursor
skillporter remove pdf
```

When several harnesses share `.agents/skills/pdf`, removing the skill from one of them keeps the shared copy for the others. It is deleted when the last owner is removed.

## Updating and rolling back

```bash
skillporter update pdf --dry-run
skillporter update pdf
skillporter rollback pdf
```

`update` fetches the recorded source again, runs the security gate, snapshots the current version to `.skillporter/backups/` and replaces it. `rollback` restores the most recent snapshot. Skillporter keeps the ten most recent snapshots per skill.

## How installs stay consistent

Installs across several harnesses are a single transaction.

- New content is staged under `.skillporter/tmp/txn-<id>/`.
- A write-ahead `journal.json` records every path that will be created or replaced before anything moves.
- If any destination fails, the destinations already written are restored.
- If the process is killed mid-install, a later Skillporter run in that workspace reads the journal and rolls back the unfinished transaction.
- Workspace changes are serialized with a cross-process lock, so two concurrent runs do not interleave.

## Local state

Skillporter keeps its state in `.skillporter/` at the workspace root:

| Path | Contents |
|---|---|
| `.skillporter/state.json` | Which skills Skillporter manages, and where. |
| `.skillporter/backups/` | Snapshots used by `rollback`. |
| `.skillporter/audit.jsonl` | Structured event log with credentials scrubbed. |
| `.skillporter/tmp/` | In-flight transactions. |

Add `.skillporter/` to `.gitignore`. Commit `skillporter.yaml` and `skillporter.lock`.
