---
title: "Syncing agent skills across harnesses"
heading: "Keeping agent skills in sync across harnesses"
description: "Harnesses read different directories, so one skill turns into five copies that quietly diverge. Sync and drift detection keep the copies honest."
date: "2026-11-13"
---

## The copy-paste problem

Skillporter ships adapters for 19 harnesses, and they do not agree on where skills live. Claude Code reads `.claude/skills`, Codex reads `.agents/skills`, Windsurf reads `.windsurf/skills`, GitHub Copilot reads `.github/skills`, Cline reads `.cline/skills`. A skill you want across your tools is the same folder copied into five places.

Divergence is silent because each harness only sees its own copy, and nothing on disk compares them. Edit the copy in `.claude/skills/pdf`, keep working in Claude Code, and every test you run passes. Your teammate on Codex loads the older copy in `.agents/skills/pdf` and gets different instructions from the same commit.

Two kinds show up. Behavioral divergence is an edit to the instructions that landed in one copy: the tools now disagree about the task, and the bug report will not reproduce because it was filed against a tool you were not using. Structural divergence is the copy that gained a `references/` directory, a helper script, or an edited frontmatter `description`, so one harness sees trigger text the others never load.

The adapter registry calls this out for Claude Code: it reads only `.claude/skills`, and a skill authored in `.agents/skills` is invisible there without a bridge. The registry note names it the most common silent failure.

## The symlink problem

The obvious answer is one real copy and a link everywhere else. Skillporter supports that: `--strategy symlink`, or `strategy: symlink` in the manifest, writes relative links to a single canonical copy. Relative links are better than absolute ones, and still break.

**Containers.** A symlink is a path, nothing more. If the link target sits outside the build context that `docker build` receives, the target is never copied into the image and the link points at nothing. A bind mount that covers the workspace but not the canonical folder does the same. The harness walks its skills directory, finds a dangling entry, and reports a skill that exists in your repository as missing.

**Git worktrees.** A worktree is a second checkout of the same repository, at a different path and on a different branch. Links that resolve into the main checkout share one physical copy across branches, so an edit made while testing one branch changes what another loads. Move or delete the main worktree and the others point at a path that no longer exists.

**Windows.** Creating a symlink requires Developer Mode or an elevated shell, and git only recreates links on checkout when `core.symlinks=true`. Many Windows git installs leave that off. Without it, the link is checked out as a small text file holding the target path, so the skill directory is a file and no harness can read it.

**Repository moves.** Absolute links break on any move. Relative links survive only when the source and the target move together; move the skill root inside the repository and the relative distance changes.

Copy is the default for these reasons: real files work in Docker build contexts, CI checkouts, worktrees and Windows clones, at the cost of duplicate bytes.

## The shared .agents/skills destination

The cheapest fix is not a link. It is a shared directory, and `.agents/skills` is the closest thing the ecosystem has to a common path: 14 of the 19 adapters read it.

Eight use it as their project primary, meaning it is the first place they look: Codex, Cursor, Gemini CLI, Google Antigravity, Zed, Replit Agent, OpenHands and Goose. Six more read it as a compatibility path behind their own directory: GitHub Copilot, Cline, Roo Code, OpenCode, JetBrains Junie and OpenClaw. Five do not read it at all: Claude Code, Windsurf, Continue, Aider / AiderDesk, and Hermes Agent, which resolves against `$HERMES_HOME/skills` instead.

That changes the arithmetic. When one run targets all 19 harnesses in a clean workspace, each physical destination is written once and the harnesses that share a path are registered against the same copy. The recorded all-harness sync produces 12 directories, not 19, with the other seven registrations resolving into `.agents/skills`. Deduplication also prevents a specific nuisance: Cursor lists a skill twice if the same name appears in both `.agents/skills` and `.cursor/skills`.

## The reconcile workflow

Start with the manifest. `skillporter init` reads the skills and harnesses it finds in the workspace and writes `skillporter.yaml`.

```bash
skillporter init
```

From then on, the manifest is the input and the directories are output. Preview the work before writing anything:

```bash
skillporter sync --dry-run
```

Then apply it. Sync installs what is missing, leaves identical copies alone, and rewrites `skillporter.lock`. Each harness gets a line stating what happened, either `created`, `unchanged`, or an error.

```bash
skillporter sync
```

Check reachability from a single harness's point of view, which is what a teammate actually experiences:

```bash
skillporter diagnose --harness claude-code
```

Repair what is broken: dangling links removed, missing installs created, drifted copies brought back in line.

```bash
skillporter doctor --fix
```

When copies disagree, plain `sync` stops instead of guessing. It exits `1` and reports which copy differs from the lock. Name the authoritative path with `--prefer`, or accept the most recently modified copy with `--force` alone; if two copies share a timestamp it asks for `--prefer` rather than picking. Replaced copies are snapshotted into `.skillporter/backups/` first, so `skillporter rollback` can restore them. In CI, `skillporter lock --check` writes nothing and fails when disk content no longer matches the lockfile.

## What drift detection compares

Drift detection is a hash comparison, not a diff of intentions. The lockfile records two levels for each skill: a `tree_hash`, one SHA-256 over the whole skill directory, and `file_hashes`, one SHA-256 per file inside it.

The tree hash walks the directory in sorted order and feeds each `relative/path:file_digest` line into one cumulative SHA-256, so a rename counts as drift even when the bytes are identical, and a new `references/` file counts too. `.git`, `__pycache__` and `.DS_Store` are excluded so checkout noise does not register as drift.

`diagnose` hashes every copy of a skill it can find, groups them by skill name, and calls it drift when the group holds more than one distinct hash. The finding prints the first eight characters of each copy's hash next to its path, so `.agents/skills/pdf (6b86f0c7)` beside `.claude/skills/pdf (e08dcf6f)` shows the two differ. That prefix identifies which copy drifted; the per-file hashes stored next to the tree hash are what let you trace it to the file that changed.

The honest limit is structural. Synchronization makes copies, and a copy is an ordinary directory anyone can edit by hand. Nothing stops a teammate from patching `.claude/skills/pdf` at 2 a.m., and nothing makes that edit propagate. The lockfile records what was installed; `diagnose` compares what is on disk now. That gap is what the command exists to surface. A clean `diagnose` means the copies agree; it says nothing about whether their content is any good.

## When a manifest beats loose folders

Loose folders are fine for one harness, one machine, one afternoon. A manifest earns its place as soon as any of these is true: more than one harness reads the same skill, more than one person works in the repository, or CI needs to produce the same workspace a developer has.

`skillporter.yaml` declares which skills, which harnesses, which security policy and which strategy, and `skillporter.lock` pins the content those declarations resolved to. A new teammate clones the repository, runs `skillporter sync`, and gets the same directories the rest of the team has. From then on the destination directories are build output: edit at the source, sync, commit the manifest and the lock.

The manifest format is documented in [configuration](/docs/configuration), the reconcile behavior including the `--force` and `--prefer` rules is in [synchronization](/docs/synchronization), and the lockfile fields are covered in [skill lockfiles explained](/blog/skill-lockfiles-explained).