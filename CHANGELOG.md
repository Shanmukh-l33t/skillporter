# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `consolidate`, `context`, `new`, `lint`, `preview`, `test`, `suggest`, `insights`, `policy`, `update --check` and `scan --ai-review`, plus five read-only MCP tools (18 in total). See the new guides under `docs/`.
- `remove --keep-manifest`; `skillporter.policy.yaml` project policy; capability declarations in `SKILL.md`.

### Changed
- `remove` and `uninstall` without `--harness` now preview and require confirmation (`-y` in scripts). They also drop the skill from `skillporter.yaml` and `skillporter.lock`.
- `consolidate --rollback` refuses to overwrite hand edits without `--force` and snapshots current files first.
- `import` no longer fans out to every harness in a package; it writes only to recorded, detected or configured harnesses.
- Seven adapters moved to `RUNTIME_VERIFIED` on captured evidence; Cursor moved down to `FIXTURE_TESTED`.
- An invalid `skillporter.policy.yaml` is an error instead of being silently ignored.

### Fixed
- Policy now applies to `--scope user`, `sync --prefer`, non-bundled `import` and `allowed_harnesses` for `move`, `self-skill` and `doctor --fix`.
- The scanner and installer share one file list, so nothing under `node_modules`, `.venv` or similar is copied unscanned.
- A registry token containing control characters is rejected and never printed; non-HTTP(S) and userinfo registry URLs are refused.
- `consolidate --rollback` can no longer restore files from a doctored backup path; `--apply` refuses to write through symlinks that leave the workspace.
- MCP tools reject unknown arguments (a `dry_run` flag was previously ignored and wrote files); deeply nested JSON no longer kills the server.
- The scanner now recognizes `eval "$(curl ...)"`, process substitution, `sh -c "$(wget ...)"`, `python -c "$(curl ...)"` and download-then-run as remote execution, and resolves aliased imports such as `from subprocess import run` when inferring capabilities.
- `sync` is idempotent: unchanged copies are reported as unchanged and no backup is taken. `doctor` and `doctor --fix` now agree, and `--fix` stays within the harnesses the skill was installed to.
- `doctor --fix` keeps a skill's original source; `add .` no longer recurses; `suggest` no longer reports unverified catalog entries as scanned.

## [3.1.0] - 2026-11-14

### Added
- **Portable `.skillpack` Environments (`skillporter/portability.py`)**: Added `skillporter export` and `skillporter import` for packaging managed skills, provenance, lockfile hashes, and named profiles into SHA-256 verified offline `.tar.gz` bundles, automatically excluding `.env*`/key files, blocking embedded credentials on export, and running bounded `safe_extract_tar` + static security checks prior to import.
- **Unified Environment Model & Comparison (`skillporter/environment.py`)**: Redesigned `skillporter status` to reconcile `skillporter.yaml`, `skillporter.lock`, `state.json`, active profile, managed, unmanaged, orphaned, duplicate, and drifted skills; added `skillporter diff` to compare workspaces against `.skillpack` archives, directories, or `profile:<name>`.
- **Granular Harness Control (`skillporter/commands/harness_cmd.py`, `skillporter/install.py`)**: Added `skillporter harness {list,inspect,status}`, `skillporter move`, `skillporter adopt`, `skillporter outdated`, `--exclude-harness`, `compatible` target selector, `--on-conflict {fail,skip,overwrite}`, `--isolated` dedicated harness paths, and scope-validated custom `harness_paths`.
- **Named Environment Profiles (`skillporter/profiles.py`)**: Added `skillporter profile {save,list,show,use,delete}` with `--prune` and durable `.skillporter/store/` caching for local harness-resident skills.
- **Official AI Agent Skill & Expanded MCP Tools (`skillporter/bundled_skill/`, `skillporter/mcp_server.py`)**: Added `skillporter self-skill install` and four workspace-bounded MCP tools (`skillporter_status`, `skillporter_diff`, `skillporter_export`, `skillporter_import`).
- **CLI Ergonomics (`skillporter/ui.py`, `skillporter/cli.py`)**: Grouped workflow help, global `-q`/`--quiet`, `-v`/`--verbose`, and `--no-color` flags, scalable table truncation on large skill sets, and next-step guidance.

### Fixed
- **User-Scope Discovery & Scan Caching (`skillporter/diagnose.py`)**: Fixed `diagnose(scope="user")` to discover user-level harness directories instead of `cwd`, eliminated 8x redundant `.agents/skills` SHA-256 walks, and eliminated false-positive missing-harness warnings on intentional single-harness installs.
- **Windows Cross-Process Workspace Lock Race (`skillporter/atomic.py`)**: Prevented `PermissionError` during `open()`/`flush()` when another Windows process holds the mandatory byte-0 `msvcrt.locking` lock.

## [3.0.1] - 2026-11-14

### Fixed
- **npm package metadata for registry ownership**: the published `3.0.0` tarball was built before `mcpName` existed in `package.json`, so `registry.modelcontextprotocol.io` rejected the listing with `NPM package '@shanmukhdheekonda/skillporter' is missing required 'mcpName' field`. This patch republishes the package metadata (no code changes) so the MCP registry can verify package ownership and accept `server.json`.

## [3.0.0] - 2026-11-14

### Security (P0 & P1 Hardening)
- **MCP Workspace Boundary & Scope Isolation (`skillporter/mcp_server.py`)**: Removed caller-supplied absolute-path fallback in `skillporter_diagnose`; enforced strict workspace boundary resolution across all MCP tools (blocking `../`, symlink escapes, UNC paths, Windows drive paths, NUL bytes, and relative/URI source escapes) and gated `scope="user"` behind explicit `SKILLPORTER_MCP_ALLOW_USER_SCOPE=1` (`--allow-user-scope`).
- **MCP Strict Runtime Validation & Default-Deny Writes (`skillporter/mcp_server.py`)**: Replaced truthy `bool()` coercion with strict JSON type/enum/harness validation; separated read tools (`detect`, `diagnose`, `scan`, `inspect`, `matrix`) from mutating tools (`add`, `install`, `sync`, `remove`), which now default-deny unless `--allow-writes` or `SKILLPORTER_MCP_ALLOW_WRITES=1` is set; added JSON-RPC `-32700`/`-32600` error handling on malformed stdio messages.
- **Conflict Force Separated from Risk Acceptance (`cli.py`, `commands/*`, `mcp_server.py`, `audit.py`)**: `--force` / `force=true` now only overrides destination conflicts and never bypasses security blocking. Added security scan gating to `skillporter install` and `skillporter update`, explicit `accept_risk` / `--allow-risky` controls, and secret-scrubbed audit logging in `.skillporter/audit.jsonl`.
- **Installer Supply-Chain Integrity (`install.sh`, `scripts/build_standalone.py`, `.github/workflows/publish.yml`)**: Removed silent fallback to mutable `main`; enforced immutable release tag validation, `SHA256SUMS.txt` verification, fail-closed provenance verification (`gh attestation verify`, `SKILLPORTER_SHA256`, or detached OpenSSL `SHA256SUMS.txt.sig`), structural zipapp validation before execution, and same-directory atomic `mv -f`.
- **Multi-Layer Static Security Engine (`skillporter/security.py`, `skillporter/scanner_analyzers.py`)**: Added Python AST security analysis (alias resolution, `shell=True`, `pickle`/`marshal`, dynamic imports, encoded exec, `socket`+`dup2` reverse shells, credential file access), JS/TS checks (`new Function`, `vm`, `execSync`, remote `import()`), Markdown comment-smuggling/exfiltration/delegation rules, bounded Base64/Hex/PowerShell `-EncodedCommand` inspection, cross-file staged payload correlation, completeness tracking (`INCOMPLETE_ASSESSMENT` on truncated/unreadable files), confidence levels, finding deduplication, and `external_scanner_status`.
- **Archive & Transaction Crash Hardening (`skillporter/sources.py`, `skillporter/install.py`)**: Added Unicode NFC collision detection, Windows reserved device/ADS/trailing-dot rejection, ZIP special-mode rejection, TAR setuid stripping, `O_CREAT | O_EXCL | O_NOFOLLOW` extraction, escaping-symlink parent directory rejection, and uncommitted multi-target `SIGKILL` rollback in `recover_interrupted_transactions()`.

### Added & Improved (P1 & P2)
- **Reproducible Lockfiles (`skillporter/manifest.py`, `skillporter/resolver.py`, `skillporter/commands/sync.py`)**: Added `LockfileError` fail-safe validation on corrupted JSON and unsupported `schema_version`, per-file `file_hashes`, `pin_state` (`PINNED_COMMIT` / `PINNED_CONTENT` / `UNPINNED_MUTABLE`), `reproducible` flag, `adapter_version`, commit-pinned `sync` across moved branches, upstream `tree_hash` integrity verification, and cross-process `workspace_lock` around `sync` and `lock`.
- **Safe Shared `.agents/skills` Removal & 19-Adapter Conformance (`skillporter/install.py`, `skillporter/harnesses.py`)**: `remove` / `uninstall` preserves shared `.agents/skills/<skill>` directories when other installed harnesses still depend on them while cleaning up harness-specific duplicates; added `FIXTURE_TESTED` verification tier and full 19-adapter lifecycle conformance suite.
- **Modular CLI Architecture & `skillporter audit` (`skillporter/commands/*`, `skillporter/cli.py`)**: Extracted command modules (`add`, `remove`, `sync`, `scan`, `audit`, `registry`, `doctor`), added `skillporter audit`, added `--dry-run` and `--json` across `install`, `remove`, `sync`, `update`, `rollback`, and `doctor`, hardened `action.yml` against GitHub Actions expression injection, and gated `publish.yml` with cross-OS verification + Sigstore artifact attestations.

## [2.4.0] - 2026-11-11

### Added
- Semver dependency resolver (`skillporter/resolver.py`), `skillporter.lock` schema v2 with v1 auto-migration, `skillporter graph`, Phase 1 registry client contract (`publish`), opt-in local telemetry (`telemetry.py`), and framework MCP recipes.

## [2.3.0] - 2026-11-11

### Added
- Zero-residue interactive `skillporter demo` and plain-English `skillporter explain`.

## [2.2.0] - 2026-11-11

### Added
- Experimental opt-in dry-run sandbox (`skillporter sandbox run`), configurable `security.max_risk_score`, `skillporter lock --check`, and `skillporter ci-report`.

## [2.1.0] - 2026-11-11

### Added & Fixed
- NVIDIA SkillSpector integration with 0–100 risk scoring, SARIF 2.1.0 output, and recursive category collision fixes.

## [2.0.0] - 2026-11-11

### Added
- 19-harness adapter catalog, universal source resolver (`add`), SHA-256 content-drift detection, transactional backups/rollback, `skillporter.yaml` & `skillporter.lock`, and stdio MCP server.

## [1.0.0] - 2026-11-10

### Added
- Initial release with `diagnose`, `install`, `uninstall`, `validate`, and `matrix` across 5 harnesses.
