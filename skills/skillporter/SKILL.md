---
name: skillporter
description: Official control-center skill for managing, consolidating, securing, testing, optimizing, synchronizing, comparing, and moving AI agent skills and instructions across 19 harnesses (Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit, Junie, Antigravity, Hermes, OpenClaw, OpenHands, Goose, Continue, Aider). Use when the user asks to inspect installed skills, consolidate duplicate agent instruction files, recommend skills for a repository, measure context token overhead, preview native harness formats, review updates, check security policies, switch profiles, or export and restore portable .skillpack environments.
license: MIT
compatibility: Requires Python 3.9+ and skillporter CLI (uvx skillporter@latest, pipx, or npx @shanmukhdheekonda/skillporter). Zero external runtime dependencies.
metadata:
  author: Shanmukh Dheekonda
  version: "3.1.0"
---

# Skillporter Agent Control Skill

Skillporter is the local-first control center for AI agent skills, instructions, security policies, and portable development environments across 19 coding and autonomous agent harnesses.

Always treat the `skillporter` CLI (or `skillporter mcp` server) as the single source of truth. Never manually copy, symlink, or delete harness skill directories when `skillporter` can execute the operation transactionally with rollback snapshots and shared-path protection.

## Agent Operation Lifecycle

1. **Understand & inspect first (`--json`)**: Run read-only commands (`status --json`, `consolidate --json`, `context --json`, `suggest --json`, `insights --json`, `harness list --json`) to establish ground truth before proposing changes.
2. **Preview before mutating (`--dry-run` / `--check`)**: Always run `--dry-run --json` (or `update --check --json`, `preview --json`, `consolidate --json`) before `add`, `install`, `import`, `remove`, `move`, `sync --force`, `consolidate --apply`, or `profile use --prune`.
3. **Request confirmation before destructive or risk-override flags**: Never pass `--force`, `--on-conflict overwrite`, `--prune`, `--purge-source`, or `--allow-risky` without showing the exact conflict, file diff, or security finding (`file:line` and rule code) and receiving explicit user approval.
4. **Verify after execution**: After any mutating command, run `skillporter status --json` (or `consolidate --status --json`) and report only verified filesystem changes.
5. **Respect scope and OS permissions**: Project operations (`--scope project`, default) modify the current repository. User-level operations (`--scope user`) modify the user's home configuration (`~/.claude/skills`, `~/.agents/skills`, `$HERMES_HOME/skills`) using normal filesystem permissions.
6. **Be honest about shared paths, capabilities, and static scans**: Eight harnesses (`codex`, `cursor`, `gemini-cli`, `zed`, `antigravity`, `opencode`, `openhands`, `goose`) natively scan `.agents/skills`. Static security scanning and capability inference catch known risky patterns and undeclared capabilities; never claim they guarantee runtime sandboxing.

## Natural-Language Intent Mapping

### 1. Rules Consolidation & Active Context Inspection

- **"Find duplicate or conflicting instructions across CLAUDE.md, AGENTS.md, and Cursor rules"**
  ```bash
  skillporter consolidate --json
  ```
- **"Consolidate my agent instructions safely, check manual edits, or reconcile changes"**
  ```bash
  skillporter consolidate --apply --json
  skillporter consolidate --status --json
  skillporter consolidate --reconcile --json
  skillporter consolidate --rollback --json
  ```
- **"Explain what instructions and skills Codex or Cursor actually receives"**
  ```bash
  skillporter context --harness codex --json
  skillporter preview <skill-name> --harness cursor --json
  ```

### 2. Project Recommendations, Insights & Authoring

- **"Recommend useful skills for this repository"**
  ```bash
  skillporter suggest --json
  ```
- **"Measure how much context my skills and instructions consume"**
  ```bash
  skillporter insights --json
  ```
- **"Create, lint, and test a custom skill"**
  ```bash
  skillporter new <skill-name> --with-references --with-tests --json
  skillporter lint <skill-dir> --strict --json
  skillporter test <skill-dir> --json
  ```

### 3. Selective Cross-Harness Installation, Exclusion & Relocation

- **"Show all installed skills and harness status"**
  ```bash
  skillporter status --json
  skillporter harness list --json
  ```
- **"Install this skill into Claude Code and Codex, excluding Cursor"**
  ```bash
  skillporter add <owner/repo-or-path> --harness claude-code,codex --exclude-harness cursor --dry-run --json
  skillporter add <owner/repo-or-path> --harness claude-code,codex --exclude-harness cursor --json
  ```
- **"Move or remove a skill safely without deleting its upstream source"**
  ```bash
  skillporter move <skill-name> --from cursor --to claude-code --dry-run --json
  skillporter remove <skill-name> --dry-run --json
  skillporter remove <skill-name> --json
  ```

### 4. Security Scanning, Policies, Update Reviews & Rollback

- **"Scan a skill, inspect capabilities, or verify project policy"**
  ```bash
  skillporter scan . --json
  skillporter policy check --json
  skillporter audit . --json
  ```
- **"Review what changed in an update (files, capabilities, risk) before applying"**
  ```bash
  skillporter outdated --json
  skillporter update --check --json
  skillporter update --json
  skillporter rollback <skill-name> --json
  ```

### 5. Portable Environments (`.skillpack`), Comparison & Profiles

- **"Export, compare, or restore an environment across machines"**
  ```bash
  skillporter export my-environment.skillpack --json
  skillporter diff my-environment.skillpack --json
  skillporter import my-environment.skillpack --dry-run --json
  skillporter import my-environment.skillpack --only-detected --on-conflict skip --json
  ```
- **"Save and switch named environment profiles"**
  ```bash
  skillporter profile save security-review --json
  skillporter profile list --json
  skillporter profile use security-review --dry-run --json
  skillporter profile use security-review --json
  ```
