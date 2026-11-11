---
name: skillporter
description: Universal package manager, reachability diagnostician, spec validator, and static security scanner for Agent Skills across 19 AI harnesses (Claude Code, Codex, Cursor, Copilot, Gemini CLI, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit, Junie, Antigravity, Hermes, OpenClaw, OpenHands, Goose, Continue, Aider). Use when installing a skill across multiple agents, diagnosing why a skill does not activate, checking for content drift, or scanning a skill for security risks.
license: MIT
compatibility: Requires Python 3.9+. Zero external runtime dependencies.
metadata:
  author: Shanmukh Dheekonda
  version: "2.0.1"
---

# skillporter

**ONE SKILL. EVERY AGENT.**

Every AI agent harness reads skills from a different directory (`.claude/skills`, `.agents/skills`, `.github/skills`, `.windsurf/skills`, `$HERMES_HOME/skills`, `~/.openclaw/skills`, etc.). `skillporter` detects which harnesses you use, validates `SKILL.md` compliance, scans for supply-chain and prompt-injection risks, installs skills portably without duplicate loading, and catches SHA-256 content drift across copies.

## When to use

- Installing a skill from GitHub (`owner/repo`), an archive, or a local folder into one or all installed agent harnesses.
- Diagnosing why a skill does not activate in Claude Code, Codex, Cursor, Copilot, Windsurf, Hermes, or OpenClaw.
- Checking whether copied skills across `.claude/skills` and `.agents/skills` have drifted out of sync.
- Auditing a third-party skill for embedded secrets, prompt injection, or risky shell scripts before installation.
- Locking and synchronizing a team's skill set with `skillporter.yaml` and `skillporter.lock`.

## Core Workflow

1. **Detect installed harnesses and diagnose current reachability:**
   ```bash
   skillporter detect .
   skillporter diagnose .
   ```

2. **Inspect and security-scan a skill before installing:**
   ```bash
   skillporter inspect owner/repository
   skillporter scan path/to/skill
   ```

3. **Add or synchronize skills across harnesses:**
   ```bash
   # One-command install from GitHub or local path to all detected harnesses
   skillporter add owner/repository --harness all

   # Synchronize existing repo skills or skillporter.yaml across harnesses
   skillporter sync
   ```

4. **Verify reachability, spec compliance, and zero drift:**
   ```bash
   skillporter diagnose .
   skillporter validate .
   ```

5. **Update or roll back:**
   ```bash
   skillporter update
   skillporter rollback <skill-name>
   ```

## Rules

- Always run `skillporter diagnose .` before and after modifying harness skill directories.
- Prefer `--strategy copy` (default) for repositories used in Docker, CI, or git worktrees.
- Never bypass `skillporter scan` findings (`--allow-risky`) without reading the exact file and line reported.
