# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [2.4.0] - 2026-11-11

### Added (Workstream 4 — Dependencies & Versioning + WS2.4 & WS3.4–3.5)
- **Semver Dependency Resolver (`skillporter/resolver.py`)**: Deterministic dependency graph resolution supporting `^`, `~`, `>=`, `<=`, `==`, `*`, and compound semver constraints across `skillporter.yaml` (`dependencies:`) and `SKILL.md` frontmatter (`dependencies:`), with cycle detection (`DependencyCycleError`, exit code 1) and conflict reporting (`DependencyConflictError`, exit code 1).
- **Lockfile v2 & Auto-Migration (`skillporter/manifest.py`)**: Extended `skillporter.lock` (`schema_version: 2`) to record `dependencies`, `risk_score`, and `direct` per node with byte-stable serialization across machines and automatic v1 -> v2 migration on read (warns once).
- **Transitive Sync, Atomic Graph Rollback & `skillporter graph` (`cli.py`, `install.py`)**: `sync` installs the full transitive dependency set in topological order; `rollback` restores dependent nodes atomically; added `skillporter graph [--format text|json]`.
- **Community Skill Registry Phase 1 Spec & Client (`docs/registry/SPEC.md`, `registry.py`)**: Versioned registry client contract (`v1.0.0`), ratings/downloads/risk_score metadata, and `skillporter publish [--dry-run]`.
- **Opt-In Privacy-Preserving Telemetry & MCP Framework Recipes (`telemetry.py`, `integrations/mcp-recipes/`)**: Strictly opt-in local analytics (`SKILLPORTER_TELEMETRY=1` / `telemetry.enabled: true`, honors `DO_NOT_TRACK=1`) and runnable MCP recipes for LangChain, CrewAI, and AutoGen.

## [2.3.0] - 2026-11-11

### Added (Workstream 2 — Adoption, Zero-Residue Demo & Explain)
- **`skillporter demo` (`skillporter/demo.py`)**: Scaffolds an isolated temporary workspace with sample skills across `.claude/skills` and `.agents/skills`, demonstrates broken symlink and SHA-256 drift detection and auto-repair (`diagnose` -> `sync` -> diff), and leaves zero residue.
- **`skillporter explain` (`skillporter/explain.py`)**: Translates any diagnostic state (`DRIFT`, `DUPLICATE`, `BROKEN`, `MISSING`, `LOCK_DRIFT`, `CYCLE`, `CONFLICT`, `RISK_THRESHOLD`), validation error, or `sec-*` rule into plain-English cause + suggested fix command.
- **Website & README Comparison Matrix (`website/index.html`, `README.md`)**: Added feature comparison vs. `skillport`, `agent-skill-porter`, and `skill-porter`, and placed the zero-install `uvx skillporter diagnose .` path in the first 10 lines of `README.md`.

## [2.2.0] - 2026-11-11

### Added (Workstream 1 Items 3–5 & Workstream 3 Items 1–3)
- **Experimental Opt-In Dry-Run Sandbox (`skillporter/sandbox.py`)**: `skillporter sandbox run <skill> [--runtime auto|wasm|gvisor|dry-run]` traces proposed file writes, sensitive file reads, network calls, env accesses, and tool invocations without mutating filesystem or network state.
- **Configurable Risk Score Gate (`skillporter.yaml`)**: Added `security.max_risk_score` (and `--max-risk-score`) causing `add` and `sync` to fail closed with exit code 1 when a skill's risk score exceeds the threshold.
- **CI Lockfile Check, Per-Harness Status & GitHub App (`ci_report.py`, `integrations/github-app/`, `action.yml`)**: Added `skillporter lock --check`, per-harness installed-vs-locked state in `skillporter status`, `skillporter ci-report`, SARIF upload workflow, and GitHub App PR webhook bot.

## [2.1.0] - 2026-11-11

### Added & Fixed (Workstream 1 Items 1–2 & v2.0.3 Audit Fixes)
- **NVIDIA SkillSpector Integration & 0–100 Risk Scoring (`skillporter/security.py`)**: Integrated `skillspector` CLI as primary security backend with automatic offline fallback to `skillporter-static`, exposing 0–100 `risk_score`, `recommendation` (`APPROVE`/`CAUTION`/`REJECT`), `category_breakdown`, `engine`, and `engine_version` across `validate`, `scan`, and `inspect`.
- **SARIF 2.1.0 & `--format json|sarif` Output (`security.py`, `cli.py`)**: Added `--format text|json|sarif` to `scan`, `validate`, and `inspect` for GitHub Code Scanning.
- **Recursive Category Collision & Missing `--skill` Fixes (`install.py`, `cli.py`)**: Fixed `doctor --fix` when a skill name matches its parent category directory (e.g. Hermes `skills/web/web`), and made `add --skill` / `inspect --skill` fail closed when any requested skill name is missing.

## [2.0.3] - 2026-11-11

### Fixed (10,000-Session Benchmark Review Remediation)
- **Zipapp & NPX Exit Code Propagation (`scripts/build_standalone.py`, `cli.py`)**: Wired `zipapp.create_archive` to `skillporter.cli:entrypoint` (`raise SystemExit(main())`) so standalone `.pyz`, `install.sh`, and `npx` invocations preserve non-zero exit codes (`1` and `2`).
- **Structural Symlink Escape Enforcement (`install.py`, `security.py`, `cli.py`)**: Added `_verify_no_escaping_symlinks()` and `SecurityReport.has_structural_escape` so escaping symlinks (e.g. `-> /etc/shadow`, `-> /root/.ssh`) are unconditionally blocked even when `--allow-risky` or `--force` is passed.
- **Tamper-Safe `doctor` & `sync` (`cli.py`)**: `doctor` and `sync` now run `scan_skill()` and verify `skillporter.lock` hashes across all copies; `doctor --fix` refuses to replicate tampered/malicious copies and heals from clean locked copies; `doctor` always emits a `Status: HEALTHY` or `Status: UNHEALTHY` verdict line.
- **100% Static Detector Recall (`security.py`)**: Added detection for inline `python -c` / `os.system` (`sec-dynamic-eval`), CSS-hidden instructions (`sec-css-hidden-instruction`), outbound environment variable exfiltration (`sec-env-exfil`), standalone `base64` decode (`sec-base64-decode`), and retained `HIGH` severity for `sec-credential-harvest` and `sec-dynamic-eval` inside `SKILL.md`.
- **CLI Ergonomics (`cli.py`)**: `--harness all` now targets all 19 supported harnesses (with `--harness detected` for detected-only); added `inspect --skill <name>`, `update .`, `pack <skill-name>`, and optional/local-skill `info [target]`.

## [2.0.2] - 2026-11-11

### Fixed (Live Server E2E Verification)
- **Version Probe Timeout Handling (`harnesses.py`)**: Catch `subprocess.SubprocessError` (`TimeoutExpired`) and pass `stdin=DEVNULL` during `skillporter detect --versions` so slow agent CLIs never crash detection.
- **Compatibility Read Duplicate Filtering (`diagnose.py`)**: Only count primary/native paths (`is_compatibility=False`) toward `DUPLICATE` warnings so cross-harness repos containing both `.claude/skills` and `.agents/skills` do not false-positive on Cursor, Copilot, Cline, OpenCode, or Replit.
- **Manifest-Aware Sync Drift Protection (`cli.py`)**: Check `diag.drifted` at the start of `skillporter sync` even when `skillporter.yaml` is present, refusing to overwrite drifted local edits without `--force` or `--prefer`.
- **Rollback History Exclusion of Active Hash (`install.py`, `state.py`)**: Exclude `dest == skill_dir` and `cand.tree_hash == tree_hash` when recording backup snapshots during multi-target `sync --force`, ensuring `skillporter rollback` always restores the pre-sync version.

## [2.0.1] - 2026-11-11

### Security & Reliability Hardening (Multi-Agent Audit & Release Gate)
- **MCP Workspace Boundary (`mcp_server.py`)**: Added `MCPBoundaryError` and `resolve_mcp_path()` constraining all MCP tool file operations to the active workspace root (`Path.cwd()` or `SKILLPORTER_MCP_ROOT`).
- **Adapted Rule Path & YAML Escaping (`formats.py`)**: Validated frontmatter `name` in `_safe_adapted_name()` against path traversal (`../`), collapsed multiline descriptions in `_sanitize_single_line()` to prevent YAML key injection, and added `assess_adaptation_limitations()`.
- **Multi-Skill Batch Transactions & Crash Recovery Journal (`install.py`, `atomic.py`, `state.py`)**: Added `install_many()` for atomic multi-skill batch rollbacks, write-ahead `journal.json` recovery (`recover_interrupted_transactions()`) verified against real subprocess `SIGKILL`, re-entrant cross-platform `workspace_lock()`, and SHA-256 backup integrity verification before `rollback_skill()`.
- **Path Traversal Guard (`install.py`, `harnesses.py`)**: Added `validate_skill_name_segment()` across `install`, `uninstall`, and `rollback_skill` and path validation in `load_adapter_file()`.
- **Archive Decompression Bomb, Duplicate Entry & Git Clone Hardening (`sources.py`)**: Enforced streaming byte/entry caps (`MAX_ARCHIVE_FILES = 1000`, `MAX_SINGLE_FILE_BYTES = 10 MiB`, `MAX_TOTAL_ARCHIVE_BYTES = 50 MiB`), duplicate/case-colliding entry rejection, Windows backslash traversal rejection, git ref option-injection guards, and `git clone -c protocol.ext.allow=never -c core.fsmonitor=false -c core.symlinks=false`.
- **Unified Workspace Status & Sync Drift Protection (`cli.py`)**: Added `skillporter status` (checking manifest and `skillporter.lock` SHA-256 drift), explainable security remediations in `skillporter scan`, and `--prefer <path>` conflict resolution in `skillporter sync`.

## [2.0.0] - 2026-11-11

### Added
- **Universal 19-Harness Adapter Catalog**: Evidence-based support (`NATIVE`, `COMPATIBLE`, `ADAPTED`) and verification tracking for Claude Code, OpenAI Codex, Cursor, GitHub Copilot, Gemini CLI, Google Antigravity, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit Agent, JetBrains Junie, Hermes Agent, OpenClaw, OpenHands, Goose, Continue, and Aider.
- **Declarative Adapter SDK**: `register_adapter`, `unregister_adapter`, and `load_adapter_file` for adding custom/third-party harness definitions safely without executing arbitrary code.
- **Universal Source Resolver (`skillporter add`)**: Install skills directly from GitHub (`owner/repo`, subdirectories, branches, tags, commit hashes), arbitrary Git URLs, `.zip` / `.tar.gz` archives (with Zip-Slip and symlink escape protection), registry slugs, and local directories.
- **SHA-256 Content-Drift & Duplicate Detection**: `diagnose` now computes deterministic SHA-256 tree hashes across all installed copies of a skill, flagging `DRIFT` when copies diverge and `DUPLICATE` when a harness scans multiple directories containing the same skill.
- **Static Security & Supply-Chain Scanner (`skillporter scan`)**: Inspects `SKILL.md`, Markdown files, and bundled scripts for hardcoded secrets, private keys, prompt-injection overrides, hidden zero-width Unicode, `curl | sh` RCE patterns, reverse shells, credential harvesting, and symlink escapes.
- **Project Manifest (`skillporter.yaml`) & Deterministic Lockfile (`skillporter.lock`)**: Added `skillporter init`, `skillporter sync`, and `skillporter lock` for reproducible team installations.
- **Transactional Lifecycle, Ownership & Rollback**: Tracks managed installations in `.skillporter/state.json`, automatically snapshots existing versions into `.skillporter/backups/` before updates, rolls back partial multi-harness installs on failure, and adds `skillporter update` and `skillporter rollback`.
- **Controlled Format Adaptation (`--adapt` / `--preview-adapt`)**: Preview and generate `.cursor/rules/<name>.mdc`, `.github/instructions/<name>.instructions.md`, `.windsurf/rules/<name>.md`, `.continue/rules/<name>.md`, and Aider conventions without mutating `SKILL.md`.
- **Registry Client & Immutable Packager**: Added `skillporter search`, `skillporter info`, `skillporter inspect`, and `skillporter pack` (emitting deterministic `.tar.gz` + `provenance.json`).
- **Native Model Context Protocol Server (`skillporter mcp`)**: Zero-dependency stdio JSON-RPC 2.0 MCP server exposing `skillporter_diagnose`, `skillporter_detect`, `skillporter_scan`, `skillporter_add`, and `skillporter_matrix`.
- **Distribution Channels**: Added `npx skillporter` Node.js package (`npm/`), standalone single-file `.pyz` builder (`scripts/build_standalone.py`), composite GitHub Action (`action.yml`), and Claude Code plugin manifest (`.claude-plugin/plugin.json`).

### Fixed
- **Portable Relative Symlinks**: `--strategy symlink` now creates relative symlinks (`os.path.relpath`) instead of host-bound absolute paths.
- **Hermes Category Discovery**: Enabled `recursive=True` on the Hermes adapter so `$HERMES_HOME/skills/<category>/<name>/SKILL.md` resolves properly.
- **Default Project Diagnosis Scope**: `skillporter diagnose .` no longer falsely fails on user-only paths when diagnosing a project repository.

## [1.0.0] - 2026-11-10

### Added
- Initial release with `diagnose`, `install`, `uninstall`, `validate`, and `matrix` across 5 harnesses (`claude-code`, `codex`, `cursor`, `hermes`, `openclaw`) and 36 functional tests.
