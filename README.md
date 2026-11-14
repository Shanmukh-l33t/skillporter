# Skillporter 3.0

**The package manager, dependency resolver, and supply-chain security layer for AI agent skills.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Harnesses: 19 Supported](https://img.shields.io/badge/harnesses-19%20supported-00b4d8)](docs/harnesses/README.md)
[![Zero Runtime Dependencies](https://img.shields.io/badge/dependencies-0-success)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Website:** [skillporter.dev](https://skillporter.dev) · **Documentation:** [skillporter.dev/docs](https://skillporter.dev/docs)

---

## 1. What Is Skillporter?

Skillporter is a lightweight, zero-runtime-dependency CLI and Model Context Protocol (MCP) server that installs, synchronizes, pins, audits, and rolls back `SKILL.md` packages across 19 AI coding and autonomous agent harnesses.

## 2. Why Do I Need It?

Every AI agent harness reads skills from a different directory (`.claude/skills/`, `.agents/skills/`, `.github/skills/`, `.windsurf/skills/`, `$HERMES_HOME/skills/`, `~/.openclaw/skills/`).

- A skill placed in `.claude/skills/` is invisible to OpenAI Codex, Gemini CLI, Zed, and Windsurf.
- Hand-rolled symlinks break inside Docker builds, CI checkouts, `git worktree`, and Windows checkouts.
- Manual copies across directories silently drift out of sync across teammates, while naive removals from shared `.agents/skills/` directories break other agents.

## 3. What Does It Protect Me From?

Agent skills are untrusted supply-chain packages: agents load `SKILL.md` directly into system context and execute bundled scripts. Skillporter helps defend against:

- **Silent skill drift and unpinned upstream changes**: `skillporter.lock` pins resolved Git commits, SHA-256 tree digests, and per-file hashes, blocking unexpected upstream mutations during `sync`.
- **Known static supply-chain hazards**: Inspects Python ASTs, JavaScript/TypeScript scripts, Markdown instructions, and bounded Base64/Hex/PowerShell payloads for embedded credentials, prompt-injection override patterns, hidden Unicode/comments, shell-pipe RCE, unsafe deserialization, symlink escapes, and multi-file staged execution before installation.
- **Unsafe archive & filesystem operations**: Blocks Zip-Slip/Tar-Slip (`../`, `..\`, drive paths, Windows reserved device names, Unicode NFC/NFD collisions, symlinks, special files, decompression bombs) and stages installs transactionally with crash-recovery journals.
- **Unscoped agent filesystem writes**: Constrains `skillporter mcp` to the workspace root with default-deny write permissions (`SKILLPORTER_MCP_ALLOW_WRITES=1` opt-in) and separates conflict overrides (`--force`) from security risk overrides (`--allow-risky`).

> **Important Security Note**: Static scanning (`STATIC_SECURITY_ASSESSMENT`) inspects files for known dangerous patterns and structural anomalies. **A clean static scan does not prove or guarantee that a skill is safe at runtime.** Novel natural-language prompt injections or dynamically fetched payloads can still steer an agent at runtime.

## 4. How Do I Install It?

```bash
# Option A: Run immediately without global installation via uvx or npx
uvx skillporter diagnose .
npx @shanmukhdheekonda/skillporter diagnose .

# Option B: Install from PyPI with uv or pipx (PEP 668 safe)
uv tool install skillporter
pipx install skillporter

# Option C: Standalone verified release installer (Linux & macOS)
# Verifies SHA256SUMS.txt + GitHub OIDC provenance attestation (`gh attestation verify`)
# or an out-of-band pinned digest (`SKILLPORTER_SHA256=<64-hex>`). Never falls back to mutable `main`.
curl -fsSL https://github.com/Shanmukh-l33t/skillporter/releases/download/v3.0.0/install.sh -o install.sh
SKILLPORTER_VERSION=v3.0.0 sh install.sh
```

## 5. How Do I Use It? (60-Second Quick Start)

```bash
# 1. Run the zero-residue interactive demo (heals broken symlinks & SHA-256 drift in a temp dir)
skillporter demo

# 2. Install a skill across harnesses (validates spec, runs static security scan, deduplicates .agents/skills)
skillporter add anthropics/skills --skill pdf --harness all

# 3. Inspect & security-scan skills (text, JSON, or SARIF 2.1.0 for GitHub Code Scanning)
skillporter scan .
skillporter scan . --format sarif > skillporter.sarif

# 4. Initialize manifest, synchronize transitive dependencies, and verify reproducible lockfile in CI
skillporter init
skillporter sync
skillporter lock --check

# 5. Diagnose reachability, audit provenance/override logs, or roll back to a verified snapshot
skillporter diagnose .
skillporter audit .
skillporter rollback pdf
```

---

## Core Differentiators

- **Multi-Harness Management**: Writes shared `.agents/skills/` once across 8 primary harnesses while preserving shared directories when individual harnesses are removed.
- **Deterministic Lockfiles (`skillporter.lock`)**: Pins `resolved_commit`, `tree_hash`, per-file SHA-256 `file_hashes`, `pin_state` (`PINNED_COMMIT` / `PINNED_CONTENT` / `UNPINNED_MUTABLE`), dependencies, and adapter version.
- **Reproducible Synchronization**: `skillporter sync` honors locked Git commit SHAs even when upstream branches move, and rejects unexpected upstream content changes without `--force`.
- **Multi-Layer Static Security Assessment**: Combines Python AST analysis, JS/TS checks, Markdown prompt/delegation inspection, bounded Base64/Hex/PowerShell decoding, cross-file chain detection, completeness tracking (`INCOMPLETE_ASSESSMENT` on truncated/unreadable files), and optional NVIDIA SkillSpector integration.
- **SHA-256 Drift & Duplicate Detection**: `diagnose`, `status`, and `doctor` detect diverging copies across harnesses and duplicate loading within the same harness.
- **Transactional Rollback & Crash Recovery**: Stages replacements in `.skillporter/tmp/txn-*` with a write-ahead `journal.json` and snapshots prior versions in `.skillporter/backups/` for atomic `skillporter rollback`.

---

## Harness Compatibility & Verification Matrix (19 Harnesses)

Skillporter distinguishes **support status** (`NATIVE`, `COMPATIBLE`, `ADAPTED`) from **verification evidence** (`RUNTIME_VERIFIED`, `INTEGRATION_TESTED`, `FIXTURE_TESTED`, `DOCUMENTATION_VERIFIED`). An adapter is never marked `RUNTIME_VERIFIED` unless tested against a live harness runtime.

| Harness | Project Path | User / Global Path | Support | Verification Evidence |
|---|---|---|---|---|
| **Hermes Agent** | `.hermes/skills/` | `$HERMES_HOME/skills/<cat>/<name>` | `NATIVE` | `RUNTIME_VERIFIED` |
| **Claude Code** | `.claude/skills/` | `~/.claude/skills/` | `NATIVE` | `INTEGRATION_TESTED` |
| **OpenAI Codex** | `.agents/skills/` | `~/.agents/skills/` | `NATIVE` | `INTEGRATION_TESTED` |
| **Cursor** | `.agents/skills/`, `.cursor/skills/` (+2 compat) | `~/.agents/skills/`, `~/.cursor/skills/` | `NATIVE` | `INTEGRATION_TESTED` |
| **GitHub Copilot** | `.github/skills/` (+2 compat) | `~/.copilot/skills/` (+1 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **Gemini CLI** | `.agents/skills/`, `.gemini/skills/` | `~/.agents/skills/`, `~/.gemini/skills/` | `NATIVE` | `FIXTURE_TESTED` |
| **Google Antigravity** | `.agents/skills/` (+1 compat) | `~/.gemini/config/skills/` | `NATIVE` | `FIXTURE_TESTED` |
| **Windsurf** | `.windsurf/skills/` | `~/.codeium/windsurf/skills/` | `NATIVE` | `FIXTURE_TESTED` |
| **Cline** | `.cline/skills/` (+3 compat) | `~/.cline/skills/` | `NATIVE` | `FIXTURE_TESTED` |
| **Roo Code** | `.roo/skills/` (+1 compat) | `~/.roo/skills/` (+1 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **OpenCode** | `.opencode/skills/` (+2 compat) | `~/.config/opencode/skills/` (+2 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **Zed** | `.agents/skills/` | `~/.agents/skills/` | `NATIVE` | `FIXTURE_TESTED` |
| **Replit Agent** | `.agents/skills/` (+1 compat) | `~/.config/agents/skills/` | `NATIVE` | `FIXTURE_TESTED` |
| **JetBrains Junie** | `.junie/skills/` (+1 compat) | `~/.junie/skills/` (+1 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **OpenClaw** | `.openclaw/skills/` (+2 compat) | `~/.openclaw/skills/` (+1 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **OpenHands** | `.agents/skills/` (+2 compat) | `~/.agents/skills/` (+1 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **Goose** | `.agents/skills/` (+1 compat) | `~/.agents/skills/` (+1 compat) | `NATIVE` | `FIXTURE_TESTED` |
| **Continue** | `.continue/skills/` (`.continue/rules/` adapted) | `~/.continue/skills/` | `COMPATIBLE` | `FIXTURE_TESTED` |
| **Aider / AiderDesk** | `.aider-desk/skills/` (`CONVENTIONS.md` adapted) | `~/.aider-desk/skills/` | `ADAPTED` | `FIXTURE_TESTED` |

---

## CLI Reference

| Command | Description |
|---|---|
| `skillporter add <source>` | Resolve, validate, security-scan, and install skills (`--dry-run`, `--allow-risky`, `--force`, `--json`) |
| `skillporter install <dir>` | Security-scan and install a local skill directory (`--dry-run`, `--allow-risky`, `--force`, `--json`) |
| `skillporter remove <skill>` | Safely remove a skill while preserving shared `.agents/skills/` still owned by other harnesses (`--dry-run`, `--json`) |
| `skillporter sync [path]` | Resolve pinned/transitive dependencies, verify lockfile hashes, and synchronize harnesses (`--dry-run`, `--json`) |
| `skillporter lock [path] [--check]` | Write or CI-verify (`--check`) deterministic `skillporter.lock` |
| `skillporter scan [path]` | Run static security & supply-chain assessment (`--format text\|json\|sarif`, `--max-risk-score`) |
| `skillporter audit [path]` | Inspect installed skill origins, security posture, lockfile drift, and `.skillporter/audit.jsonl` events |
| `skillporter diagnose [path]` | Check reachability, broken symlinks, SHA-256 content drift, duplicates, and spec compliance |
| `skillporter doctor [path] [--fix]` | Comprehensive workspace health check and tamper-safe repair (`--dry-run`, `--json`) |
| `skillporter status [path]` | Unified workspace manifest, lockfile, per-harness installed/locked state, and drift summary |
| `skillporter update [skill]` | Fetch, security-gate, backup, and update tracked skills (`--dry-run`, `--allow-risky`, `--json`) |
| `skillporter rollback <skill>` | Atomically restore a skill (and dependency graph) from SHA-256-verified `.skillporter/backups/` (`--dry-run`, `--json`) |
| `skillporter validate [path]` | Validate `SKILL.md` against the Agent Skills specification (`--format text\|json\|sarif`) |
| `skillporter inspect <source>` | Inspect local/remote package structure, security posture, and adapted rule previews |
| `skillporter graph [path]` | Render or export (`--json`) topological skill dependency graph |
| `skillporter sandbox run <skill>` | **[Experimental]** Opt-in non-mutating dry-run behavioral trace |
| `skillporter explain <finding>` | Explain any diagnostic, lockfile, validation, or `sec-*` finding code with remediation commands |
| `skillporter search / info / pack / publish` | Search catalog, inspect metadata, build deterministic `.tar.gz` + `provenance.json`, or publish |
| `skillporter detect / matrix / demo` | Detect installed harnesses, print 19-harness matrix, or run zero-residue demo |
| `skillporter mcp` | Run hardened JSON-RPC 2.0 MCP server (read-only by default; `--allow-writes` opt-in) |

### Exit Codes
- `0`: Clean / operation succeeded
- `1`: Policy or diagnostic finding (drift, broken symlink, spec error, security block, lockfile mismatch, cycle/conflict)
- `2`: Usage or runtime error (invalid argument, unknown harness, missing path)
