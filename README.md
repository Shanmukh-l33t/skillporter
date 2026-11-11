# SKILLPORTER — The AI Agent Skill Manager

**ONE SKILL. EVERY AGENT.** Multi-agent skill synchronization, skill lifecycle management, 0–100 security risk scoring, and deterministic `skillporter.lock` lockfiles across 19 AI coding harnesses.

```bash
# Zero-install execution (<60s): diagnose your repo or run the interactive demo
uvx skillporter diagnose .
uvx skillporter demo
```

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Harnesses: 19 Verified](https://img.shields.io/badge/harnesses-19%20supported-00b4d8)](docs/harnesses/README.md)
[![Tests: 133 Passing](https://img.shields.io/badge/tests-133%20passing-brightgreen)](tests/)
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

---

## Why Skillporter? (Feature Comparison vs. Lookalike Tools)

| Capability | **skillporter (v2.4)** | `skillport` | `agent-skill-porter` | `skill-porter` |
|---|:---:|:---:|:---:|:---:|
| **Supported AI Harnesses** | **19 (Evidence-Verified)** | 3 | 4 | 2 |
| **Shared `.agents/skills` Deduplication** | **Yes (writes once for 14 agents)** | No | No | No |
| **SHA-256 Content-Drift Detection** | **Yes (`diagnose`, `lock --check`)** | No | No | No |
| **Security Engine & 0–100 Risk Score** | **NVIDIA SkillSpector + Built-in Fallback** | None | Basic regex | None |
| **SARIF 2.1.0 & GitHub Code Scanning** | **Yes (`--format sarif`)** | No | No | No |
| **Opt-in Dry-Run Sandbox (`sandbox run`)** | **Yes (WASM / gVisor / AST Tracer)** | No | No | No |
| **Semver Dependency Resolver & `graph`** | **Yes (`skillporter.yaml` + `skillporter.lock` v2)** | No | No | No |
| **Transactional Rollback (`.skillporter/backups/`)** | **Yes (atomic graph restore)** | No | No | No |
| **Built-in MCP Server (`skillporter mcp`)** | **Yes (Claude, Codex, Cursor, LangChain, CrewAI, AutoGen)** | No | No | No |

---

## 60-Second Quick Start & Zero-Install Execution

```bash
# 1. Try the 60-second zero-residue demo (shows broken symlinks & SHA-256 drift being healed)
uvx skillporter demo

# 2. Diagnose your repository immediately via uvx or npx
uvx skillporter diagnose .
npx @shanmukhdheekonda/skillporter diagnose .

# 3. Validate SKILL.md compliance and compute a 0-100 security risk score (JSON or SARIF)
skillporter validate . --format json
skillporter scan . --format sarif > skillporter.sarif

# 4. Explain any diagnostic, lockfile, or security finding in plain English
skillporter explain DRIFT
skillporter explain sec-prompt-override

# 5. Install a skill across all detected harnesses, resolve dependencies, and pin skillporter.lock
skillporter add anthropics/skills --skill pdf --harness all
skillporter sync
skillporter lock --check
skillporter graph
```

---

## Security Model, Risk Scoring & Experimental Dry-Run Sandbox

Agent skills are untrusted supply-chain packages: they inject natural-language instructions directly into your LLM's system context and often bundle executable scripts (`scripts/*.py`, `scripts/*.sh`).

### 1. Dual-Engine Security Scanning & 0–100 Risk Score (`validate`, `scan`, `inspect`)
- **Primary Backend**: Integrates **NVIDIA SkillSpector** (`skillspector scan --no-llm --format json`) when installed on `PATH`, merging its findings with Skillporter's built-in scanner.
- **Built-in Offline Fallback**: When running offline (`--offline` or `SKILLPORTER_OFFLINE=1`) or without `skillspector` installed, Skillporter runs its zero-dependency static and semantic-heuristic engine (`skillporter-static v2.4.0`).
- **Transparent 0–100 Risk Score & Category Breakdown**: Every scan computes a deterministic `0–100` risk score broken down across 6 categories:
  1. `secrets` (`sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key`)
  2. `prompt_injection` (`sec-prompt-override`, `sec-hidden-unicode`, `sec-html-comment-instruction`, `sec-css-hidden-instruction`)
  3. `code_execution` (`sec-curl-pipe-sh`, `sec-obfuscated-exec`, `sec-base64-decode`, `sec-reverse-shell`, `sec-dynamic-eval`)
  4. `data_exfiltration` (`sec-env-exfil`, `sec-credential-harvest`, `sec-data-exfil`)
  5. `filesystem_escape` (`sec-symlink-escape`, `sec-path-traversal`, `sec-markdown-path-traversal`, `sec-broken-symlink`)
  6. `supply_chain` (`sec-binary-artifact`, `sec-script-outside-scripts-dir`, `sec-external-download`, `sec-oversized-file`)
- **Configurable Fail-Closed Thresholds (`skillporter.yaml`)**:
  ```yaml
  schema_version: 2
  project: acme-platform
  security:
    policy: HIGH
    max_risk_score: 30
  ```
  Any skill scoring above `security.max_risk_score` blocks `skillporter add` and `skillporter sync` with exit code `1`. Structural escapes (`sec-symlink-escape`, `sec-path-traversal`) are unconditionally blocked even with `--allow-risky` or `--force`.

### 2. What Is Checked vs. What Is NOT Checked
- **What IS Checked**:
  - Known prompt-injection override directives, hidden zero-width/bidi Unicode, HTML comments, and `display:none` CSS blocks in `SKILL.md`.
  - Hardcoded PEM private keys, AWS keys, GitHub PATs, and OpenAI/Anthropic/Slack tokens.
  - Pipe-to-shell RCE (`curl | sh`), base64/hex obfuscation, reverse shells, `os.environ` exfiltration, credential store reads (`~/.ssh`, `~/.aws`, `/etc/shadow`), and `eval`/`exec`/`os.system`.
  - Archive Zip-Slip/Tar-Slip path traversal, decompression bombs, and escaping symlinks.
- **What Is NOT Checked (Honest Limitations)**:
  - **Static analysis does not guarantee runtime safety.** Novel semantic prompt injections phrased without known override patterns can still steer an LLM at runtime.
  - Dynamic payloads fetched at runtime from legitimate-looking domains after a skill is invoked by an agent.
  - Model-specific jailbreaks or downstream tool-call misconfigurations inside the host agent harness.

### 3. Experimental Opt-In Dry-Run Sandbox (`skillporter sandbox run <skill>`)
To reduce (though not eliminate) runtime blind spots, `skillporter sandbox run <skill>` (default **OFF**, labeled **EXPERIMENTAL**) inspects and traces a skill using `wasmtime` (WASI capability sandbox with zero preopened write dirs and zero network sockets), `runsc` (gVisor rootless `--network=none` sandbox), or the built-in AST + shell behavioral interceptor:
- Reports `proposed_file_writes`, `proposed_file_reads`, `proposed_network_calls`, `proposed_tool_invocations`, and `proposed_env_accesses`.
- Mathematically verifies via before/after SHA-256 tree hashing that **zero host files or network sockets were mutated**.

---

## Dependencies, Semver Constraints & Lockfile v2 (`skillporter.yaml` & `skillporter.lock`)

Declare skill dependencies with semver ranges (`^1.0.0`, `~1.2.0`, `>=1.0.0 <2.0.0`, `*`) in `skillporter.yaml` or `SKILL.md` frontmatter:

```yaml
schema_version: 2
project: acme-platform
scope: project
strategy: copy
security:
  policy: HIGH
  max_risk_score: 30
harnesses:
  - claude-code
  - codex
  - cursor
skills:
  - name: release-orchestrator
    source: ./skills/release-orchestrator
    version: "1.2.0"
    dependencies:
      - name: changelog-helper
        version: "^1.0.0"
        source: ./skills/changelog-helper
```

- `skillporter graph [--format json]` prints the resolved topological dependency tree and exits `1` on cyclic dependencies or version conflicts.
- `skillporter sync` installs the full transitive dependency set in topological order.
- `skillporter lock --check` verifies in CI that `skillporter.lock` matches on-disk SHA-256 hashes and the resolved dependency graph (auto-migrating v1 lockfiles on read with a one-time warning).
- `skillporter rollback <skill>` (or `skillporter rollback all`) atomically restores the skill and its transitive dependencies from `.skillporter/backups/`.

---

## CLI Reference

| Command | Description |
|---|---|
| `skillporter add <source>` | Resolve, validate, security-scan, and install skills (`--max-risk-score`, `--format json`) |
| `skillporter diagnose [path]` | Check reachability, broken symlinks, SHA-256 content drift, duplicates, and spec compliance |
| `skillporter doctor [path] [--fix]` | Run full workspace health check and auto-repair missing/drifted installs |
| `skillporter scan [path]` | Run security & supply-chain assessment with 0–100 risk score (`--format text\|json\|sarif`) |
| `skillporter validate [path]` | Validate `SKILL.md` spec compliance and compute 0–100 risk score (`--format text\|json\|sarif`) |
| `skillporter sandbox run <skill>` | **[Experimental]** Run opt-in dry-run behavioral sandbox (`--runtime auto\|wasm\|gvisor\|dry-run`) |
| `skillporter demo` | Scaffold a temporary multi-harness workspace and demonstrate drift/symlink auto-repair in <60s |
| `skillporter explain <finding>` | Translate any diagnostic code (`DRIFT`, `BROKEN`, `CYCLE`) or `sec-*` rule into plain English + fix |
| `skillporter graph [path]` | Print or export (`--format json`) the resolved transitive skill dependency tree |
| `skillporter sync [path]` | Resolve transitive dependencies, reconcile across harnesses, and update `skillporter.lock` |
| `skillporter lock [path] [--check]` | Write or CI-verify (`--check`) deterministic `skillporter.lock` v2 |
| `skillporter status [path]` | Show per-harness installed vs. locked state, copy drift, and lockfile drift |
| `skillporter publish [path]` | Validate, security-gate (`risk_score <= 30`), pack, and publish to registry (`--dry-run`) |
| `skillporter ci-report [path]` | Generate Markdown/JSON PR report for GitHub Actions and the Skillporter GitHub App |
| `skillporter inspect <source>` | Inspect local/remote skill package with risk score, categories, and adapted previews |
| `skillporter detect [path]` | Detect installed AI agent harnesses on the machine or active in the project |
| `skillporter matrix` | Print the 19-harness compatibility and verification matrix (`--json` supported) |
| `skillporter rollback <skill>` | Atomically restore a skill (and its dependency graph) from `.skillporter/backups/` |
| `skillporter mcp` | Start the zero-dependency stdio JSON-RPC 2.0 MCP server |

### Exit Codes (CI Contract)
- `0` — Clean / all checks passed
- `1` — Findings detected (drift, broken symlink, spec error, security block, risk score > threshold, lock drift, or dependency cycle/conflict)
- `2` — Usage or runtime error (invalid path, unknown harness, missing `--skill` name)
