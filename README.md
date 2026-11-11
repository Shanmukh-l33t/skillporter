# SKILLPORTER

## ONE SKILL. EVERY AGENT.

**Install, manage, validate, security-scan, and synchronize AI-agent skills across the entire agent ecosystem.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Harnesses: 19 Verified](https://img.shields.io/badge/harnesses-19%20supported-00b4d8)](docs/harnesses/README.md)
[![Tests: 60 Passing](https://img.shields.io/badge/tests-60%20passing-brightgreen)](tests/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-success)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<p align="center">
  <img src="docs/assets/demo.svg" alt="Skillporter Terminal Demonstration" width="860" />
</p>

Every AI coding and autonomous agent harness reads skills from a **different directory**:

| Harness | Project Path | Personal / Global Path | Support |
|---|---|---|---|
| **Claude Code** | `.claude/skills/` | `~/.claude/skills/` | `NATIVE` |
| **OpenAI Codex** | `.agents/skills/` | `~/.agents/skills/` | `NATIVE` |
| **Cursor** | `.agents/skills/`, `.cursor/skills/` (+2 compat) | `~/.agents/skills/`, `~/.cursor/skills/` | `NATIVE` |
| **GitHub Copilot** | `.github/skills/`, `.agents/skills/` (+1 compat) | `~/.copilot/skills/`, `~/.agents/skills/` | `NATIVE` |
| **Gemini CLI** | `.agents/skills/`, `.gemini/skills/` | `~/.agents/skills/`, `~/.gemini/skills/` | `NATIVE` |
| **Google Antigravity** | `.agents/skills/` (+1 compat) | `~/.gemini/config/skills/` | `NATIVE` |
| **Windsurf** | `.windsurf/skills/` | `~/.codeium/windsurf/skills/` | `NATIVE` |
| **Cline** | `.cline/skills/`, `.clinerules/skills/` (+2 compat) | `~/.cline/skills/` | `NATIVE` |
| **Roo Code** | `.roo/skills/`, `.agents/skills/` | `~/.roo/skills/`, `~/.agents/skills/` | `NATIVE` |
| **OpenCode** | `.opencode/skills/`, `.agents/skills/` (+1 compat) | `~/.config/opencode/skills/` (+2 compat) | `NATIVE` |
| **Zed** | `.agents/skills/` | `~/.agents/skills/` | `NATIVE` |
| **Replit Agent** | `.agents/skills/`, `.claude/skills/` | `~/.config/agents/skills/` | `NATIVE` |
| **JetBrains Junie** | `.junie/skills/`, `.agents/skills/` | `~/.junie/skills/`, `~/.agents/skills/` | `NATIVE` |
| **Hermes Agent** | `.hermes/skills/` | `$HERMES_HOME/skills/<category>/<name>` | `NATIVE` |
| **OpenClaw** | `.openclaw/skills/`, `skills/`, `.agents/skills/` | `~/.openclaw/skills/`, `~/.agents/skills/` | `NATIVE` |
| **OpenHands** | `.agents/skills/`, `.openhands/skills/` | `~/.agents/skills/`, `~/.openhands/skills/` | `NATIVE` |
| **Goose** | `.agents/skills/`, `.goose/skills/` | `~/.agents/skills/`, `~/.config/goose/skills/` | `NATIVE` |
| **Continue** | `.continue/skills/` (`.continue/rules/` adapted) | `~/.continue/skills/` | `COMPATIBLE` |
| **Aider / AiderDesk** | `.aider-desk/skills/` (`CONVENTIONS.md` adapted) | `~/.aider-desk/skills/` | `ADAPTED` |

A skill authored for Claude Code in `.claude/skills/` is silently invisible to OpenAI Codex, Gemini CLI, Zed, and Windsurf. Hand-rolled symlinks break in Docker build contexts, `git worktree`, and Windows checkouts — while manual copies silently drift out of sync.

**Skillporter solves the entire lifecycle:** one command resolves skills from GitHub or local paths, runs a static security and supply-chain scan, deduplicates shared destinations (`.agents/skills`), tracks ownership and SHA-256 content hashes, detects content drift across copies, and supports deterministic lockfiles (`skillporter.lock`) and transactional rollback.

---

## One-Command Installation & Zero-Install Execution

```bash
# Run immediately with uvx (zero install)
uvx skillporter diagnose .

# Or run with npx
npx skillporter diagnose .

# Or install globally via uv / pipx / pip
uv tool install skillporter
pipx install skillporter
pip install skillporter
```

### Native Agent Integration (MCP Server)

Register Skillporter directly inside Claude Code, Codex, Cursor, Windsurf, or Hermes so your agent can diagnose, scan, and synchronize skills on command:

```bash
claude mcp add skillporter -- uvx skillporter mcp
codex mcp add skillporter -- uvx skillporter mcp
```

---

## 60-Second Quick Start

```bash
# 1. Detect which AI agent harnesses are installed or active in your repo
skillporter detect .

# 2. Install a skill from GitHub across all detected harnesses (validates + security-scans first)
skillporter add anthropics/skills --skill pdf --harness all

# 3. Diagnose reachability, broken symlinks, duplicate loading, and SHA-256 content drift
skillporter diagnose .

# 4. Run a static supply-chain security scan on any skill directory
skillporter scan .

# 5. Initialize skillporter.yaml, synchronize teammates, and pin skillporter.lock
skillporter init
skillporter sync
skillporter lock
```

---

## Real-World Evidence: Why Skillporter Exists

Built after auditing the exact failure modes reported across upstream agent ecosystems:

- **[agentskills/agentskills#15](https://github.com/agentskills/agentskills/issues/15)** (130+ comments) — *"Claude is looking at `.claude/skills/` and GitHub Copilot is looking at `.github/skills/`… create symlinks that match the specific folder of each harness"*
- **[thn-inc/claude-tweaks#3000](https://github.com/thn-inc/claude-tweaks/issues/3000)** — skill resolution misses `.agents/skills` when the symlink is absent or inside a **git worktree**
- **[openclaw/openclaw#14593](https://github.com/openclaw/openclaw/issues/14593)** — symlinked skill installs fail inside Docker build contexts
- **[squne121/loop-protocol](https://github.com/squne121/loop-protocol/issues)** — replacing broken Codex skill symlinks with a fail-closed `.agents/skills` bridge

---

## Key Features

### 1. Universal Source Resolution (`skillporter add`)
Install skills from:
- **GitHub shorthand**: `skillporter add owner/repo` or `skillporter add owner/repo/skills/my-skill@v1.2.0`
- **GitHub tree URLs**: `skillporter add https://github.com/owner/repo/tree/main/skills/my-skill`
- **Git URLs & commit SHAs**: `skillporter add https://example.com/skills.git --ref ceb64c6`
- **ZIP & tar.gz archives**: `skillporter add ./bundle.zip` (hardened against Zip-Slip and symlink escapes)
- **Registry slugs**: `skillporter add registry:anthropics/skills`
- **Local directories**: `skillporter add ./authoring/my-skill --harness claude-code --harness codex`

### 2. SHA-256 Content-Drift & Duplicate Detection (`skillporter diagnose`)
Competing tools copy files once and report success forever. Skillporter hashes every file inside every installed skill copy (`SHA-256`).
- **Drift**: If you edit `.claude/skills/my-skill/SKILL.md` and forget to update `.agents/skills/my-skill/SKILL.md`, `skillporter diagnose` flags `DRIFT` with the exact diverging hashes and exits `1`.
- **Duplicate loading**: If a skill is installed in both `.agents/skills` and `.cursor/skills`, `diagnose` flags `DUPLICATE` so Cursor does not load the same skill twice.

### 3. Static Security & Supply-Chain Protection (`skillporter scan`)
Agent skills contain natural-language instructions and executable scripts. Before installing any skill, Skillporter inspects all Markdown and script files for:
- **Embedded secrets & private keys** (`sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key`)
- **Prompt injection & covert overrides** (`sec-prompt-override`, `sec-hidden-unicode`, `sec-html-comment-instruction`)
- **Dangerous execution patterns** (`sec-curl-pipe-sh`, `sec-reverse-shell`, `sec-credential-harvest`, `sec-dynamic-eval`)
- **Filesystem escapes** (`sec-symlink-escape`, `sec-path-traversal`, `sec-binary-artifact`)

*Transparency note: Static scanning inspects files for known dangerous patterns and structural escapes; it does not guarantee runtime safety.*

### 4. Manifest (`skillporter.yaml`), Lockfile (`skillporter.lock`) & Rollback
Declare your project's skills in `skillporter.yaml`:

```yaml
schema_version: 1
project: acme-platform
scope: project
strategy: copy
security_policy: HIGH
harnesses:
  - claude-code
  - codex
  - cursor
  - github-copilot
skills:
  - name: skillporter
    source: Shanmukh-l33t/skillporter/skills/skillporter
    ref: main
```

Run `skillporter sync` to reconcile the workspace, `skillporter lock` to pin exact git commits and SHA-256 tree hashes in `skillporter.lock`, and `skillporter rollback <skill>` to restore the previous snapshot from `.skillporter/backups/` if an update introduces a regression.

---

## CLI Reference

| Command | Description |
|---|---|
| `skillporter add <source>` | Resolve, validate, security-scan, and install skills from GitHub, Git, archive, or local path |
| `skillporter diagnose [path]` | Check reachability, broken symlinks, SHA-256 content drift, duplicates, and spec compliance |
| `skillporter doctor [path] [--fix]` | Run full workspace health check and optionally auto-repair missing/drifted installs |
| `skillporter scan [path]` | Run static supply-chain and prompt-injection security assessment |
| `skillporter validate [path]` | Validate `SKILL.md` frontmatter and body against the [Agent Skills spec](https://agentskills.io/specification) |
| `skillporter inspect <source>` | Inspect a local or remote skill package (files, scripts, security, adapted previews) before installing |
| `skillporter detect [path]` | Detect which AI agent harnesses are installed on the machine or active in the project |
| `skillporter matrix` | Print the 19-harness compatibility and verification matrix (`--json` supported) |
| `skillporter init [path]` | Generate `skillporter.yaml` from discovered skills and active harnesses |
| `skillporter sync [path]` | Reconcile workspace skills across target harnesses and update `skillporter.lock` |
| `skillporter lock [path]` | Write deterministic `skillporter.lock` with SHA-256 content tree hashes |
| `skillporter list [path]` | List managed and discovered skills with ownership, hashes, and active harnesses |
| `skillporter update [skill]` | Update tracked skills from their recorded upstream source |
| `skillporter rollback <skill>` | Restore a skill to its previous backup snapshot in `.skillporter/backups/` |
| `skillporter install <path>` | Low-level local directory installer (`--strategy copy\|symlink`, `--adapt`, `--force`) |
| `skillporter remove <skill>` | Remove a skill from target harnesses (`uninstall` alias supported) |
| `skillporter search [query]` | Search the seed and configured skill registry catalog |
| `skillporter info <target>` | Show detailed metadata for a harness adapter or registry package |
| `skillporter pack [path]` | Build an immutable `.tar.gz` release archive and `provenance.json` checksum manifest |
| `skillporter mcp` | Start the zero-dependency stdio JSON-RPC 2.0 MCP server |

### Exit Codes (CI Contract)
- `0` — Clean / all checks passed
- `1` — Findings detected (missing reachability, content drift, broken symlink, spec error, or security policy block)
- `2` — Usage or runtime error (invalid path, unknown harness, unsafe overwrite refusal)

---

## GitHub Action Integration

Validate `SKILL.md` compliance, scan for security risks, and verify harness reachability automatically on every pull request:

```yaml
name: Skillporter Check
on: [push, pull_request]
jobs:
  skills:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Shanmukh-l33t/skillporter@v2
        with:
          command: validate
          path: .
          run-security-scan: "true"
```

---

## Documentation

- [Getting Started](docs/getting-started/README.md)
- [Installation & Distribution (uvx, npx, binaries, MCP)](docs/installation/README.md)
- [Supported Harnesses & Evidence Directory (19 Harnesses)](docs/harnesses/README.md)
- [CLI Command Reference](docs/commands/README.md)
- [Configuration (`skillporter.yaml` & `skillporter.lock`)](docs/configuration/README.md)
- [Security & Supply-Chain Model](docs/security/README.md)
- [System Architecture](ARCHITECTURE.md)
- [Adapter Development SDK](docs/adapters/README.md)
- [Registry & Immutable Packaging](docs/registry/README.md)
- [Troubleshooting](docs/troubleshooting/README.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Product Roadmap](ROADMAP.md)

---

## License

MIT — see [LICENSE](LICENSE).
