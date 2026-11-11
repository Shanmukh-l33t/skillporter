# Skillporter Architecture

**ONE SKILL. EVERY AGENT.**

Skillporter is a local-first, zero-dependency Python core engine with thin distribution wrappers (PyPI/`uvx`, `npx`, standalone zipapp/binaries, GitHub Action, and native MCP/skill integrations). Every interface delegates to a single authoritative core package (`skillporter`).

```
+-----------------------------------------------------------------------------------+
|                           USER & AGENT INTERFACES                                 |
|  CLI (`skillporter`)  |  NPX (`npx skillporter`)  |  MCP (`skillporter mcp`)      |
|  GitHub Action        |  Native Agent Skills      |  Python SDK (`import ...`)    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        SKILLPORTER CORE ENGINE (`skillporter/`)                   |
|                                                                                   |
|  +------------------+  +------------------+  +------------------+  +-----------+  |
|  |   cli.py / ui.py |  |   diagnose.py    |  |   install.py     |  | state.py  |  |
|  |  Commands, ANSI  |  | Reachability,    |  | Transactional    |  | Ownership,|  |
|  |  tables, JSON,   |  | SHA-256 drift,   |  | copy/symlink,    |  | backups,  |  |
|  |  exit contracts  |  | duplicate checks |  | shared-dest dedup|  | rollback  |  |
|  +------------------+  +------------------+  +------------------+  +-----------+  |
|                                                                                   |
|  +------------------+  +------------------+  +------------------+  +-----------+  |
|  |   sources.py     |  |   security.py    |  |   manifest.py    |  |formats.py |  |
|  | GitHub, Git URL, |  | Secret scan,     |  | skillporter.yaml |  | SKILL.md, |  |
|  | subdir, ref/SHA, |  | script analysis, |  | skillporter.lock |  | AGENTS.md,|  |
|  | zip, local, reg  |  | prompt-inj,      |  | deterministic    |  | .mdc,     |  |
|  | staging          |  | path/symlink     |  | sync & pinning   |  | rules     |  |
|  +------------------+  +------------------+  +------------------+  +-----------+  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |             UNIVERSAL HARNESS ADAPTER LAYER (`harnesses.py`)                |  |
|  |  19 Verified & Categorized Harnesses + Declarative Adapter Extension SDK    |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 1. Design Principles

1. **Single Authoritative Core**: All business logic lives in `skillporter/`. The `npx` package, MCP server, and GitHub Action invoke the Python core directly rather than re-implementing rules in JavaScript or Bash.
2. **Zero Runtime Dependencies**: The core uses Python 3.9+ standard library modules only (`pathlib`, `hashlib`, `json`, `urllib`, `zipfile`, `tarfile`, `shutil`, `argparse`, `dataclasses`). It runs in any bare Python environment without network installs or native C extensions.
3. **Evidence-Based Compatibility**: Every harness adapter records its `SupportStatus` (`NATIVE`, `COMPATIBLE`, `ADAPTED`, `PARTIAL`, `UNSUPPORTED`, `UNVERIFIED`), `VerificationLevel` (`RUNTIME_VERIFIED`, `INTEGRATION_TESTED`, `DOCUMENTATION_VERIFIED`, `UNIT_TESTED`, `UNVERIFIED`), official documentation URL, and verification date.
4. **Safe & Transactional by Default**:
   - Never overwrites unmanaged user files without `--force`.
   - Never executes scripts from downloaded skills during resolution or installation.
   - Snapshots existing managed skills into `.skillporter/backups/` before updates or overwrites so failed operations automatically roll back and users can run `skillporter rollback <skill>`.

---

## 2. Module Responsibilities

### `skillporter/harnesses.py` — Universal Adapter Registry & SDK
- Defines `SkillPath`, `SupportStatus`, `VerificationLevel`, `HarnessCapabilities`, `DetectionRule`, and `Harness` (the adapter contract).
- Ships 19 adapters covering coding and autonomous agents:
  - Coding: `claude-code`, `codex`, `cursor`, `github-copilot`, `gemini-cli`, `antigravity`, `windsurf`, `cline`, `roo-code`, `opencode`, `zed`, `replit`, `junie`, `continue`, `aider`.
  - Autonomous: `hermes`, `openclaw`, `openhands`, `goose`.
- Distinguishes **primary install path** (`paths[0]`) from **compatibility read paths** (`is_compatibility=True`) so `install` writes once while `diagnose` models every directory a harness actually scans.
- Exposes `detect_harnesses(root, home)` to discover which agents are installed on the machine or active in the workspace, and `register_adapter()` / `load_adapter_file()` for declarative third-party adapters without executing untrusted code.

### `skillporter/frontmatter.py` & `skillporter/formats.py` — Specification & Format Engine
- Parses and validates `SKILL.md` against the [Agent Skills Specification](https://agentskills.io/specification).
- Inspects skill directories for `scripts/`, `references/`, `assets/`, `AGENTS.md`, and harness-specific configs.
- Provides explicit, previewable format adaptation (`render_adapted_skill`) for harnesses that require or benefit from rule files (`.cursor/rules/<name>.mdc`, `.github/instructions/<name>.instructions.md`, `.continue/rules/<name>.md`, Aider `CONVENTIONS.md`).

### `skillporter/security.py` — Static Security & Supply-Chain Scanner
- Computes deterministic SHA-256 content tree hashes (`compute_tree_hash`) across all files in a skill directory.
- Scans `SKILL.md`, documentation, and bundled scripts (`.sh`, `.py`, `.js`, `.ts`, `.ps1`) for:
  - Embedded secrets and private keys (`sec-hardcoded-secret`, `sec-private-key`).
  - Prompt injection and hidden instruction overrides (`sec-hidden-unicode`, `sec-prompt-injection`, `sec-html-comment-override`).
  - Dangerous command execution (`sec-curl-pipe-sh`, `sec-dangerous-exec`, `sec-reverse-shell`, `sec-credential-harvest`).
  - Filesystem escapes (`sec-symlink-escape`, `sec-path-traversal`, `sec-binary-payload`).
- Enforces installation policy gates (default: block installation on `CRITICAL` or `HIGH` findings unless `--allow-risky` / `--force` is explicitly provided).

### `skillporter/sources.py` — Universal Source Resolver
- Resolves skill packages from:
  - Local directories and single-skill or multi-skill repositories.
  - GitHub repositories (`owner/repo`, `github:owner/repo`, `owner/repo/subpath@ref`).
  - Arbitrary Git URLs (`https://...`, `git@...`) with branch, tag, or commit pinning.
  - Local or remote `.zip` / `.tar.gz` archives with strict Zip-Slip and symlink escape protection.
  - Registry specifiers (`registry:publisher/skill@version`).

### `skillporter/state.py` & `skillporter/manifest.py` — Lifecycle, Manifest & Lockfile
- `skillporter.yaml`: Declarative project manifest listing required skills, sources, target harnesses, strategy, and security policy.
- `skillporter.lock`: Deterministic JSON lockfile pinning exact resolved git commit, version, SHA-256 content tree hash, and installed destinations.
- `.skillporter/state.json`: Tracks managed installations, ownership metadata, content hashes, and backup snapshots under `.skillporter/backups/<skill>/<timestamp>-<hash>/` for atomic rollback.

### `skillporter/diagnose.py` & `skillporter/install.py` — Diagnosis & Transactional Installation
- `diagnose`: Checks reachability across harnesses, detects broken symlinks, detects **content drift** (SHA-256 mismatch across copies of the same skill), detects **duplicate loading** within a single harness (e.g., skill present in both `.agents/skills` and `.cursor/skills`), and validates frontmatter.
- `install` / `add` / `sync` / `update` / `rollback`: Plans installations, deduplicates shared destinations (`.agents/skills`), verifies ownership, backs up prior versions, writes copies or portable relative symlinks, verifies post-install reachability, and records state.

### `skillporter/registry.py` & `skillporter/mcp_server.py` — Ecosystem & Native Agent Server
- `registry.py`: Local + remote registry index client with curated seed packages (`search`, `info`, `pack`).
- `mcp_server.py`: Zero-dependency stdio JSON-RPC 2.0 Model Context Protocol (MCP) server exposing Skillporter diagnostics, scanning, and synchronization directly to AI agents.
