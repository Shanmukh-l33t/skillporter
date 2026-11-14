---
title: "Skill Porter, the two-word name for Skillporter"
heading: "Skill Porter is Skillporter, spelled with a space"
description: "Skill Porter and Skillporter are one product: an open source package manager that installs, scans, pins and synchronizes AI agent skills across 19 harnesses."
kicker: "Product"
---

## What Skill Porter means

Skill Porter and Skillporter are the same product: an open source package manager for AI agent skills. It installs, validates, scans, pins and synchronizes `SKILL.md` packages across 19 harnesses, 15 coding clients and 4 autonomous agents. The two-word form is how people write the name in prose and in search, so this page uses it. There is no second tool behind the spelling and no fork to compare against. Every command and path below belongs to the released package, MIT licensed, with no runtime dependencies and no hosted service in the loop.

## What it does

Skill Porter runs the lifecycle of a package manager over skill directories. Each stage exists because the one before it can fail.

1. **Resolve.** `add` accepts a GitHub shorthand, tree URL, git URL, archive or local path, and fetches it into a temporary directory. Nothing is executed at this stage.
2. **Validate.** The skill is checked against the Agent Skills specification: frontmatter fields, name and directory agreement, description length, file layout.
3. **Scan.** The static assessment runs before anything is written. A blocking result stops the install there.
4. **Install.** One destination is planned per adapter. Harnesses sharing `.agents/skills` share a single write, and all destinations land in one journaled transaction, so an interrupted run leaves nothing half-written.
5. **Pin.** `skillporter.lock` records the resolved commit and a SHA-256 for every file.
6. **Sync.** `sync` reconciles the manifest, the lockfile and the directories. It will not overwrite a copy that changed on disk until you pass `--force`, which takes the most recently modified copy unless you name one with `--prefer`.
7. **Diagnose.** `diagnose` reports which harnesses see each skill, plus drift between copies, duplicates and broken symlinks.
8. **Roll back.** `rollback` restores a skill from the snapshot taken before the last overwrite, stored under `.skillporter/backups/`.

```bash
skillporter add anthropics/skills --skill pdf --harness all
skillporter validate .
skillporter scan .
skillporter sync
skillporter lock --check
skillporter diagnose .
skillporter rollback pdf
```

## Install

The first three lines run or install the same Python package. The last two are the standalone installer, for Linux and macOS:

```bash
uvx skillporter --version
pipx install skillporter
npx @shanmukhdheekonda/skillporter --version

curl -fsSL https://github.com/Shanmukh-l33t/skillporter/releases/download/v3.0.0/install.sh -o install.sh
SKILLPORTER_VERSION=v3.0.0 sh install.sh
```

Download the installer to a file first, so you can read it before it runs. It accepts only an immutable version tag, rejecting branch names and aliases such as `latest`, checks the zipapp against `SHA256SUMS.txt` from the same release, and requires one independent authenticity check, either GitHub artifact attestation through the authenticated `gh` CLI, a pinned digest, or a detached signature. Python 3.9 or newer is required in every case, and the npm package needs a Python 3.9+ interpreter (`python3`, `python` or `py -3`) or `uvx` on `PATH`. On Windows, use `uv`, `pipx` or `npx`.

## The skill directories it reconciles

| Harness | Project directory | What to know |
|---|---|---|
| Claude Code | `.claude/skills` | Reads only its own directory. A skill in `.agents/skills` is invisible without a copy or symlink bridge. |
| OpenAI Codex | `.agents/skills` | User scope is `~/.agents/skills`. |
| Cursor | `.agents/skills` | Also reads `.cursor/skills`, with compatibility reads of `.claude/skills` and `.codex/skills`. |
| GitHub Copilot | `.github/skills` | Compatibility reads of `.agents/skills` and `.claude/skills`. |
| Gemini CLI | `.agents/skills` | Falls back to `.gemini/skills`, and `.agents/skills` takes precedence. |

Eight of the 19 adapters use `.agents/skills` as their primary project path, and six more read it as a documented compatibility path. That overlap is the reason Skill Porter deduplicates writes. Ask for one skill across five harnesses and it writes `.agents/skills` once, plus the Claude Code and Copilot directories, instead of five independent copies. Removal follows the same rule: a shared copy stays while another harness still owns it.

The overlap has a trap: installing the same skill into both `.agents/skills` and `.cursor/skills` makes Cursor list it twice. That is why destinations are planned per adapter.

## Lockfiles and reproducibility

`skillporter.lock` is the record of what was installed. Each entry holds the resolved Git commit, one SHA-256 over the whole skill directory, and a SHA-256 per file so a mismatch points at the file that changed. A `pin_state` field says whether the entry is `PINNED_COMMIT`, `PINNED_CONTENT` or `UNPINNED_MUTABLE`, and the top-level `reproducible` flag is true only when no entry is unpinned.

```bash
skillporter lock --check
```

`lock --check` writes nothing. It exits 1 when the lockfile is stale or when the files on disk no longer match the hashes recorded in it, which is what makes a stale copy fail a build instead of quietly reaching an agent. Commit the lockfile beside `skillporter.yaml`.

Skill Porter states the limits plainly. A local directory is pinned by content, not by origin. The lockfile pins the files of a skill; it does not pin what its scripts download at runtime.

## Security scanning

`scan` reads every skill it discovers and produces a risk score from 0 to 100. It parses Python with an AST for `eval`, `exec`, `shell=True` and unsafe deserialization, checks JavaScript for `new Function`, `vm` and `child_process`, and reads Markdown instructions for override phrasing, hidden HTML comments, hidden Unicode and exfiltration directives. It decodes bounded Base64, hex and PowerShell payloads, follows a payload split across files, and checks for embedded secrets, traversal in referenced paths and symlinks that leave the skill root. Archive member checks run earlier, when an archive is unpacked, not during scoring.

```bash
skillporter scan . --max-risk-score 30
skillporter scan . --format sarif
```

`--max-risk-score` turns the score into an exit code, so a threshold fails a build. `--format sarif` emits SARIF, which code scanning tools accept.

Skill Porter does not claim more than that. The scan is static, and a clean scan does not prove a skill is safe at runtime. A prompt injection written in ordinary prose can pass. A URL can serve harmless content at scan time and something else when the agent fetches it. Which tools an agent may call is enforced by the harness and the host, not by this tool.

## Who it is for

Skill Porter is for people running two or more harnesses on the same projects: a laptop with Claude Code and Cursor, a team where one person uses Codex and another uses Copilot, a repository whose skills are read by a coding assistant and an autonomous agent. Those are the setups where hand-made copies turn into drift, and where a lockfile check in CI earns its place.

If you run a single harness and never share a skill, the directory work buys you little. The scan and the lockfile still apply, but plain copies are simpler.

## Next steps

Start with the [getting started guide](/docs/getting-started), or go straight to [install](/install) if you already know which channel you want. The [FAQ](/faq) covers the first questions, and the [blog](/blog) has longer pieces on synchronization, lockfiles and scanning. For the per-command detail, see the [lockfile reference](/docs/lockfiles) and the [security scanning documentation](/docs/security-scanning).
