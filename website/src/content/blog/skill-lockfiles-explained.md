---
title: "Skill lockfiles explained"
heading: "Skill lockfiles: what they pin and what they do not"
description: "A git ref is not a pin. What skillporter.lock records, how file hashes catch an edited copy, and how lock --check fails a build."
date: "2026-11-14"
---

## A branch is not a pin

`skillporter add anthropics/skills --ref main` resolves `main` once, at install time. Whatever commit that branch pointed at is installed. The next fetch asks the network again, and `main` may point somewhere else by then. A tag is the same story with better manners: tags can be deleted and recreated against a different commit, and nothing in a plain `git clone` will tell you it happened.

A skill directory is also not a package. It is a folder of Markdown and scripts that stands in one place and gets read from there. It has no build step, no tarball and no checksum unless you make one. Someone can edit `SKILL.md` in place, add a script next to it, or force-push over the branch you installed from. Nothing breaks at build time, because there is no build. The agent simply reads different instructions on the next run, and every harness copying that directory inherits the change.

`skillporter.lock` exists to close that gap. It records the bytes that were installed, not the name of the branch they came from.

## What skillporter.lock records

This is an excerpt from the lockfile recorded for this site's own build. One skill, three of its twelve file hashes, two of its nineteen targets:

```json
{
  "schema_version": 2,
  "reproducible": true,
  "skills": {
    "pdf": {
      "source": "https://github.com/anthropics/skills.git",
      "resolved_commit": "2c5958ecac7cee2b583967a2c4981d0f4a75c579",
      "pin_state": "PINNED_COMMIT",
      "tree_hash": "6b86f0c798b5a47987bdd48a97964c0d349ea8ecbc4b886f10dcc38ab0580c32",
      "file_hashes": {
        "SKILL.md": "d1c7caf5f35eb7d37877dd7fc33a095037be2b34fb5d2f7f4d43bde3165bb4ee",
        "forms.md": "9530b3f57034792e0242a3abfe8b3c296466329551916f2ff6c5a70db78f7e44",
        "scripts/fill_fillable_fields.py": "d140872c2e92e41b1e05370ae8d270c5b7f5ebdf55d9905f03bc974a9c708ff5"
      },
      "installed_targets": ["claude-code", "codex"]
    }
  }
}
```

Each entry carries the following.

| Field | What it holds |
|---|---|
| `source` | The URL or path the skill came from. |
| `resolved_commit` | The full 40 character commit the ref resolved to. `sync` installs this commit even if the branch has moved. |
| `tree_hash` | One SHA-256 over the whole skill directory. Any change to any file changes it. |
| `file_hashes` | A SHA-256 per file, so a mismatch points at the file that changed. |
| `installed_targets` | The harnesses the skill was installed for, by ID. |
| `pin_state` | Whether the entry is actually immutable. |

The entry also records how it was installed (`strategy`, `scope`, `adapt`), which Skillporter version produced the install (`adapter_version`), what it depends on (`dependencies`), and the static risk score at lock time (`risk_score`). The top level carries `schema_version` and `reproducible`.

`pin_state` has three values. `PINNED_COMMIT` means a content hash plus a resolved commit, which is the only state where both the bytes and their origin are fixed. `PINNED_CONTENT` means a hash without a commit, typical of a local directory: the content is pinned, its origin is not. `UNPINNED_MUTABLE` means a remote source with no resolved commit, or an entry with no content hash. One `UNPINNED_MUTABLE` entry sets the top-level `reproducible` flag to `false`, because a single floating entry is enough to make the whole install unrepeatable.

## One hash for the directory, one per file

Two levels of hashing answer two different questions. `tree_hash` answers whether anything changed at all. `file_hashes` answer what changed.

Take a workspace where `pdf` is installed for all 19 harnesses. Eight of them share one directory under `.agents/skills/pdf`, while Claude Code reads its own copy under `.claude/skills/pdf`. Someone opens that copy in an editor to "just add a note" and fixes a path while they are there. The shared directory still matches the lockfile. The Claude Code copy does not, and `skillporter lock --check` reports the path, so you know which copy to open.

Without per-file hashes you would know a directory had drifted but not whether it was a typo in `reference.md` or a new script under `scripts/`. The distinction matters at review time: one is noise, the other is code that an agent may execute. The digest in the check output is shortened to 12 characters for reading; the lockfile stores the full 64 character SHA-256.

## Check mode

`skillporter lock --check` writes nothing. It reads `skillporter.yaml`, reads the lockfile, hashes what is on disk, and compares. Exit code 1 means the lockfile is stale or the files no longer match it. Exit code 2 means the command could not run at all, which keeps a broken install from being mistaken for a clean pass. On success it prints a single line saying the lockfile is up to date and verified with zero drift.

A real failure looks like this:

```text
$ skillporter lock --check
skillporter.lock check FAILED (1 issue(s)):
  - lockfile drift on 'pdf' (.claude/skills/pdf): locked 6b86f0c798b5 != disk e08dcf6fa1c6
```

`skillporter lock` without `--check` is the write path, and `skillporter sync` writes the lockfile too. When on-disk content differs from the lockfile, a plain `sync` refuses to re-lock without `--force`. It will not quietly adopt your edit as the new truth, and it will not silently overwrite it either. Same rule for a moved source: if `skillporter.yaml` now points a skill somewhere else, `--check` reports the mismatch instead of treating the new source as the new baseline.

## In CI

One line in any pipeline is enough, because the exit code carries the answer:

```yaml
steps:
  - run: uvx skillporter lock --check
```

The composite GitHub Action wraps the same check behind an input, so a pull request that edits an installed skill copy fails instead of passing review:

```yaml
- uses: Shanmukh-l33t/skillporter@v3.0.0
  with:
    command: validate
    lock-check: "true"
    max-risk-score: "30"
```

`lock-check` defaults to `false`, so it is opt-in. `command` defaults to `validate`, and the action runs the static security scan as well unless `run-security-scan` is set to `false`. The full input list is in the [CI docs](/docs/ci).

## What a lockfile proves, and what it does not

A lockfile proves what you installed. It is a receipt: this source, this commit, these file hashes, these harnesses, this Skillporter version. It lets a teammate or a CI job reproduce the same bytes and detect when they no longer match.

It is not a safety verdict. The `risk_score` in the entry is a static assessment made at lock time, and a clean score says nothing about what a skill does when an agent runs it. The lockfile also cannot pin what a skill's scripts download at runtime, and if the pinned commit has been deleted from the source, the install cannot be reproduced from the lockfile at all. A local source is only as stable as the directory it points at.

So pin the content, then review it separately. The static scan is worth running, and it is honest about its limits, which is a different thing from being safe. Details on the file format, pin states and migration from older schema versions are in the [lockfile reference](/docs/lockfiles). For keeping one set of pinned skills in step across harnesses, see [how to sync skills across harnesses](/blog/sync-skills-across-harnesses).