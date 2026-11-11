# Getting Started with Skillporter

**ONE SKILL. EVERY AGENT.**

Skillporter is the universal package manager, validator, security scanner, and cross-harness synchronizer for AI-agent skills (`SKILL.md`).

## 1. Run Immediately (Zero Install)

```bash
# With uvx (recommended for Python users)
uvx skillporter diagnose .

# Or with npx (recommended for Node/TypeScript users)
npx skillporter diagnose .
```

## 2. Detect Your Installed AI Agents

```bash
skillporter detect .
```

Skillporter probes your workspace and home directory for all 19 supported coding and autonomous agent harnesses (Claude Code, OpenAI Codex, Cursor, GitHub Copilot, Gemini CLI, Google Antigravity, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit Agent, JetBrains Junie, Hermes Agent, OpenClaw, OpenHands, Goose, Continue, and Aider).

## 3. Add a Skill from GitHub or Local Path

```bash
# Install a skill from GitHub across all detected harnesses
skillporter add Shanmukh-l33t/skillporter --harness all

# Preview the installation plan and static security report without modifying disk
skillporter add Shanmukh-l33t/skillporter --harness all --dry-run
```

## 4. Diagnose Reachability & Content Drift

```bash
skillporter diagnose .
```

If any skill is missing from a target harness, points to a broken symlink, is duplicated across two folders read by the same harness, or has drifted in SHA-256 content across copies, `diagnose` names the exact cause and exits `1`.

## 5. Repair Automatically

```bash
skillporter doctor --fix
```
