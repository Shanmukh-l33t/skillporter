# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-11

### Security & Reliability Hardening (Multi-Agent Audit)
- **Path Traversal Guard (`install.py`, `harnesses.py`)**: Added `validate_skill_name_segment()` across `install`, `uninstall`, and `rollback_skill` and path validation in `load_adapter_file()` to prevent `../` or backslash traversal outside harness roots.
- **Staged Directory Replacement & Full Transaction Restoration (`install.py`, `atomic.py`)**: Replaced in-place `shutil.rmtree` with staged swaps in `.skillporter/tmp/txn-<id>/` and `workspace_lock()` advisory locking; partial failures now restore pre-existing overwritten destinations as well as removing newly created ones.
- **Archive Decompression Bomb & Git Clone Hardening (`sources.py`)**: Enforced streaming byte/entry caps (`MAX_ARCHIVE_FILES = 1000`, `MAX_SINGLE_FILE_BYTES = 10 MiB`, `MAX_TOTAL_ARCHIVE_BYTES = 50 MiB`), Windows backslash traversal rejection, git ref option-injection guards, and `git clone -c protocol.ext.allow=never -c core.fsmonitor=false -c core.symlinks=false`.
- **Stop-at-Skill-Root Discovery & Symlink Loop Protection (`frontmatter.py`, `security.py`)**: `discover()` stops recursing once `SKILL.md` is found in a directory and tracks `(st_dev, st_ino)` inodes; `compute_tree_hash()` uses `os.walk(..., followlinks=False)`.
- **Line-Anchored YAML Frontmatter & Multi-Copy Validation (`frontmatter.py`, `diagnose.py`)**: Fixed inline `---` splitting, UTF-8 BOM handling, and tab-indentation detection (`frontmatter-tab-indentation`); `diagnose()` now validates every discovered copy of a skill and exposes explicit `FOUND` / `VALID` / `COMPATIBLE` / `INSTALLED` / `VERIFIED` / `UNVERIFIED` / `MISSING` states in `skillporter doctor`.
- **Sync Drift Protection (`cli.py`)**: `skillporter sync` refuses to overwrite drifted copies without `--force`, and syncs from the newest copy after snapshotting backups when `--force` is passed.

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
