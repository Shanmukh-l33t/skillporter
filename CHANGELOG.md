# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

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
