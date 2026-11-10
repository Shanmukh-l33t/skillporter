---
name: skillporter
description: Diagnose and fix Agent Skill installation across Claude Code, Codex, Cursor, Hermes and OpenClaw. Use when a skill does not activate, when sharing one skill across multiple harnesses, or when setting up a repo so every agent finds its skills.
license: MIT
compatibility: Requires Python 3.9+. No network access needed.
metadata:
  author: Shanmukh Dheekonda
  version: "1.0.0"
---

# skillporter

Every agent harness reads skills from a different directory, so a skill written
for one is silently invisible to the others. This skill uses the `skillporter`
CLI to find out which harnesses can actually see each skill and to fix it
portably.

## When to use

- A skill "doesn't work" in Codex/Cursor/Claude Code even though the file exists.
- The user has symlinks between `.claude/skills` and `.agents/skills` that break.
- Setting up a repository so multiple harnesses share one skill source.
- Validating `SKILL.md` frontmatter before publishing.

## When not to use

- The user only uses one harness and nothing is broken.
- The problem is skill *content* quality, not installation or discovery.
- The task is about MCP servers or plugin packaging (different mechanism).

## Prerequisites

`skillporter` must be installed (`pip install skillporter`) or run from a
checkout. Verify with `skillporter --version` before relying on it.

## Workflow

1. **Diagnose first, never guess.**
   ```bash
   skillporter diagnose .
   ```
   Read the matrix. A `MISSING` cell is the reason a skill is not activating.

2. **Check the harness paths** if the user disputes the result:
   ```bash
   skillporter matrix
   ```
   Paths marked `expected` are unverified — say so rather than asserting them.

3. **Fix with an explicit install.**
   ```bash
   skillporter install path/to/skill --harness codex
   ```
   Prefer `--strategy copy` (default) when the repo is used in Docker or CI;
   use `--strategy symlink` only for local-only workflows.

4. **Re-run `diagnose`** and confirm the cell flipped to `yes`. Never report
   success from the install output alone.

5. **Validate spec compliance** before publishing a skill:
   ```bash
   skillporter validate .
   ```

## Rules

- Always run `diagnose` before and after a change; report only verified state.
- Never hand-create symlinks when `install` will do it correctly.
- Do not modify a user's source skill directory — installs write only into
  harness directories.
- Exit code 1 means findings; surface them instead of silencing the command.

## Verification

Success is `diagnose` showing `yes` for every harness the user cares about, and
`validate` exiting 0. If a harness still shows `MISSING`, read the location
column — the path, not the skill, is usually the problem.
