---
name: skillporter
description: Official control-center skill for managing, securing, synchronizing, comparing, and moving AI agent skills across 19 harnesses (Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit, Junie, Antigravity, Hermes, OpenClaw, OpenHands, Goose, Continue, Aider). Use when the user asks to inspect installed skills, install or move skills across specific harnesses, exclude harnesses, check outdated skills, scan for security risks, switch profiles, or export, compare, and import portable .skillpack environments.
license: MIT
compatibility: Requires Python 3.9+ and skillporter CLI (uvx skillporter, pipx, or npx @shanmukhdheekonda/skillporter). Zero external runtime dependencies.
metadata:
  author: Shanmukh Dheekonda
  version: "3.1.0"
---

# Skillporter Agent Control Skill

Skillporter is the local-first package manager, environment portability engine, and static supply-chain scanner for `SKILL.md` packages across 19 AI coding and autonomous agent harnesses.

Always treat the `skillporter` CLI (or `skillporter mcp` server) as the single source of truth. Never manually copy, symlink, or delete harness skill directories when `skillporter` can execute the operation transactionally with rollback snapshots and shared-path protection.

## Operating Protocol for AI Agents

1. **Inspect first (`--json`)**: Run read-only commands (`status --json`, `harness list --json`, `diff --json`, `outdated --json`) to establish ground truth before proposing changes.
2. **Preview before mutating (`--dry-run`)**: Always run `--dry-run --json` before `add`, `install`, `import`, `remove`, `move`, `sync --force`, or `profile use --prune`.
3. **Ask confirmation before destructive or risk-override flags**: Never pass `--force`, `--on-conflict overwrite`, `--prune`, or `--allow-risky` without showing the exact conflict or security finding (`file:line` and rule code) and receiving explicit user approval.
4. **Verify after execution**: After any mutating command, run `skillporter status --json` (or `diagnose --json`) and report only verified filesystem changes.
5. **Respect OS & scope boundaries**: Project operations (`--scope project`, default) modify the current repository. User-level operations (`--scope user`) modify the user's home configuration (`~/.claude/skills`, `~/.agents/skills`, `$HERMES_HOME/skills`) and require normal filesystem permissions.
6. **Be honest about shared paths and static scans**: Eight harnesses (`codex`, `cursor`, `gemini-cli`, `zed`, `antigravity`, `opencode`, `openhands`, `goose`) natively scan `.agents/skills`. Removing a skill from `cursor` while `codex` still manages it preserves `.agents/skills` for `codex`. Static security scanning catches known risky patterns and symlink escapes; never claim it guarantees runtime sandboxing.

## Natural-Language Intent Mapping

### 1. Environment State & Discovery

- **"Show all my managed skills" / "What is the state of my AI environment?"**
  ```bash
  skillporter status --json
  skillporter status --scope user --json
  ```
- **"Show which harnesses are installed or have access to this skill"**
  ```bash
  skillporter harness list --json
  skillporter harness inspect <harness> --json
  skillporter diagnose . --json
  ```
- **"Adopt existing unmanaged skills so Skillporter tracks and backs them up"**
  ```bash
  skillporter adopt --all --json
  ```

### 2. Selective Cross-Harness Installation, Exclusion & Relocation

- **"Install this skill in Claude Code and Codex, but not Cursor"**
  ```bash
  skillporter add <owner/repo-or-path> --harness claude-code,codex --exclude-harness cursor --dry-run --json
  skillporter add <owner/repo-or-path> --harness claude-code,codex --exclude-harness cursor --json
  ```
- **"Install into all detected compatible harnesses except Windsurf, skipping existing unmanaged skills"**
  ```bash
  skillporter add <source> --harness detected --exclude-harness windsurf --on-conflict skip --json
  ```
- **"Install into Cursor's dedicated folder without sharing `.agents/skills`"**
  ```bash
  skillporter install ./path/to/skill --harness cursor --isolated --json
  ```
- **"Remove this skill from Cursor but keep it in Codex"**
  ```bash
  skillporter remove <skill-name> --harness cursor --dry-run --json
  skillporter remove <skill-name> --harness cursor --json
  ```
- **"Move this skill from Cursor to Claude Code"**
  ```bash
  skillporter move <skill-name> --from cursor --to claude-code --dry-run --json
  skillporter move <skill-name> --from cursor --to claude-code --json
  ```

### 3. Updates, Security Warnings & Rollback

- **"Check which skills are outdated"**
  ```bash
  skillporter outdated --json
  ```
- **"Find skills that have security warnings or drift"**
  ```bash
  skillporter scan . --json
  skillporter audit . --json
  ```
- **"Update skills safely or roll back a broken update"**
  ```bash
  skillporter update --dry-run --json
  skillporter update --json
  skillporter rollback <skill-name> --json
  ```

### 4. Portable Environments (`.skillpack`) & Comparison

- **"Export my entire Skillporter environment"**
  ```bash
  skillporter export my-environment.skillpack --json
  skillporter export personal.skillpack --scope user --json
  ```
- **"Compare my current setup with this environment package or another project"**
  ```bash
  skillporter diff my-environment.skillpack --json
  skillporter diff ../other-project --json
  ```
- **"Restore my development environment on this machine"**
  ```bash
  skillporter import my-environment.skillpack --dry-run --json
  skillporter import my-environment.skillpack --only-detected --on-conflict skip --json
  ```

### 5. Named Environment Profiles

- **"Create or switch between named environments (e.g. frontend, security-review)"**
  ```bash
  skillporter profile save security-review --json
  skillporter profile list --json
  skillporter profile use security-review --dry-run --json
  skillporter profile use security-review --json
  ```
