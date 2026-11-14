# SkillPorter Product Evolution & Architecture Specification

Version baseline audited: `3.0.1` (`cd48cfe4ca79a9c940332195459a03da5aa09346`)

## 1. Phase 1 Audit: Actual Repository State vs. Developer Reality

### 1.1 Strengths to Preserve (Non-Negotiable Foundations)

1. **Zero Runtime Dependencies**: Pure Python 3.9+ standard library implementation. Runs immediately via `uvx`, `pipx`, `npx`, or standalone `.pyz` without dependency conflicts.
2. **19 Verified Harness Adapters (`skillporter/harnesses.py`)**: Explicit `support_status` (`NATIVE`, `COMPATIBLE`, `ADAPTED`, `PARTIAL`, `UNSUPPORTED`, `UNVERIFIED`), `verification_level`, non-destructive `DetectionSpec`, and shared-path deduplication across `.agents/skills` (shared by 8 harnesses).
3. **Crash-Safe Filesystem Transactions (`skillporter/install.py`, `skillporter/atomic.py`)**: Cross-process workspace locks (`flock` on POSIX, `msvcrt` on Windows), write-ahead `journal.json` recovery on `SIGKILL`, and automatic rollback snapshots under `.skillporter/backups/`.
4. **Multi-Layer Static Supply-Chain Scanner (`skillporter/security.py`, `skillporter/scanner_analyzers.py`)**: Inspects Python ASTs, JavaScript/TypeScript, Markdown prompt-injection/hidden-CSS/bidirectional-Unicode patterns, bounded archives (Zip-Slip/Tar-Bomb protection), and emits SARIF 2.1.0. Clearly separates conflict override (`--force`) from security risk acceptance (`--allow-risky`), while never allowing structural symlink/path escapes to be overridden.
5. **Reproducible Lockfile v2 (`skillporter/manifest.py`) & Semver Graph (`skillporter/resolver.py`)**: Tracks `resolved_commit`, `tree_hash`, per-file SHA-256 `file_hashes`, and `pin_state`.
6. **Hardened MCP Server (`skillporter/mcp_server.py`)**: Workspace-bounded JSON-RPC 2.0 stdio server with default-deny writes (`--allow-writes`) and secret-scrubbed `.skillporter/audit.jsonl` logging.

### 1.2 Real Defects, Gaps, and UX Friction Found by Live Execution

Running actual commands against both project workspaces and a live developer machine with 300+ user-scope skills exposed concrete issues:

1. **Broken `--scope user` Discovery (`diagnose.py`)**: `diagnose(root, scope="user")` called `discover(root)` on the current working directory instead of discovering skills installed across user-level harness paths (`~/.claude/skills`, `~/.agents/skills`, `$HERMES_HOME/skills`). Consequently, `skillporter list --scope user` and `skillporter status --scope user` ignored real user-installed skills and misreported workspace skills as missing in user harnesses.
2. **Redundant Directory Hashing**: Shared paths like `.agents/skills` are scanned independently for 8 harnesses during a single `diagnose()` pass, multiplying SHA-256 disk reads by 8x.
3. **Unscalable CLI Output (`status`, `list`, `add`, `sync`, `--help`)**:
   - `skillporter status` prints all skills horizontally on one comma-separated line per harness (`skill1=INSTALLED_UNLOCKED, skill2=MISSING...`), which wraps unreadably past 5 skills and collapses completely at 50+ skills.
   - `skillporter --help` prints a flat 29-command list with no task grouping and lacks global `-q/--quiet`, `-v/--verbose`, and `--no-color` controls.
   - Mutating commands (`install`, `sync`, `remove`, `update`) print raw path lines without summarizing what changed, what was skipped, whether attention is needed, or what command to run next.
   - `status` does not distinguish managed skills, unmanaged on-disk skills, orphaned lock/state entries, missing manifest targets, and active environment profiles.
4. **Incomplete Harness Control**:
   - No `--exclude-harness` option (forcing users to enumerate 15+ `--harness` flags to skip one agent).
   - No `compatible` target selector (to target only `NATIVE` and `COMPATIBLE` harnesses without lossy rule adaptation).
   - No `skillporter harness` command family (`list`, `inspect`, `status`) separating Supported, Compatible, Detected, Selected, and Configured states.
   - No `skillporter move` command to relocate a skill between harnesses without manual install-then-remove choreography.
   - No `--on-conflict {fail,skip,overwrite}` policy for idempotent batch operations where unmanaged skills already exist.
   - No safe custom path overrides per harness for non-standard setups.
5. **No Whole-Environment Portability (`export` / `import` / `diff`)**:
   - `skillporter pack` packages a single skill directory for registry publishing, not a developer's multi-skill, multi-harness environment. Developers cannot move their setup across machines or compare two environments (`skillporter diff`).
6. **No Named Environment Profiles (`profile`)**:
   - Developers cannot switch cleanly between named setups (such as `frontend`, `backend`, `security-review`) without manually rewriting `skillporter.yaml`.
7. **Outdated Detection & Unmanaged Skill Adoption Missing**:
   - `skillporter update --dry-run` reports `would-update` even when local `tree_hash` already matches upstream. There is no `skillporter outdated` command to check upstream drift non-destructively.
   - Existing skills in `.claude/skills` or `~/.agents/skills` show `managed: no` with no `skillporter adopt` workflow to bring them under lockfile, backup, and export management.
8. **AI Agent Skill (`skills/skillporter/SKILL.md`) Lags Product Capabilities**:
   - Still pinned at `3.0.0` (64 lines), lacks natural-language-to-CLI mapping for selective harness exclusion, `.skillpack` portability, environment diffing, profile switching, and dry-run-before-mutate safety protocols. Furthermore, users installing via `pipx` or `uvx` lack a `skillporter self-skill` command to bootstrap the official SkillPorter skill into their agents without cloning the Git repository.

---

## 2. Phase 2 & 3: Product Evaluation & Ruthless Prioritization

Every proposed capability was evaluated across problem solved, practical daily value, frequency of use, target users, technical feasibility, complexity, maintenance burden, security, and backward compatibility.

### P0: Foundational (Must Ship Immediately)

| Capability | Problem Solved | Value & Frequency | Security & Compatibility |
|---|---|---|---|
| **Fix `--scope user` Discovery + Shared Location Caching** | User-level `list`, `status`, `diagnose`, and `export` fail to discover user-installed skills and hash `.agents/skills` 8x. | Critical; affects every global install user daily. | 100% backward-compatible; preserves strict project vs. user scope isolation. |
| **Unified Environment Model (`environment.py`) & Redesigned `status` + `diff`** | Developers lack a single source of truth reconciling manifest, lockfile, `state.json`, and on-disk harness state, or comparing two environments. | Daily control-center command for individuals and teams. | Read-only inspection; preserves existing JSON keys while adding structured breakdowns. |
| **CLI DX Overhaul (Grouped Help, `-q`/`-v`/`--no-color`, Actionable Summaries, Large-List Scaling)** | Flat 29-command help, noisy or cryptic command outputs, horizontal overflow on large skill sets. | Touches 100% of interactive CLI sessions while keeping `--json` and exit codes intact. | Preserves `EXIT_OK=0`, `EXIT_PROBLEM=1`, `EXIT_ERROR=2` and all existing JSON schemas. |
| **Portable Environment Packaging (`export` & `import` `.skillpack`)** | Moving skills, lockfiles, harness mappings, and local custom skills to another machine or teammate requires manual reinstallation. | Anchor differentiator for multi-machine and team onboarding workflows. | Uses bounded `safe_extract_tar`, SHA-256 per-file & tree verification, secret scrubbing on export, and mandatory static security scan before import writes. |
| **Granular Harness Control (`harness list/inspect/status`, `--exclude-harness`, `--on-conflict`, `move`, custom paths)** | Cannot exclude specific harnesses, inspect detected vs. configured state cleanly, skip conflicts in batch mode, or move skills safely across shared paths. | High; used whenever configuring multi-agent workspaces. | Explicit opt-in behavior; never installs silently into unselected harnesses or overwrites unmanaged files without permission. |

### P1: High-Value Everyday Workflows (Ship in This Evolution)

| Capability | Problem Solved | Value & Frequency | Security & Compatibility |
|---|---|---|---|
| **Official AI Agent Skill v3.1 + `self-skill` Bootstrap + MCP Parity** | Developers want Claude Code, Codex, Cursor, or Hermes to manage SkillPorter cross-harness operations safely with real verification. | High viral and daily ergonomic leverage; zero business-logic duplication (calls CLI/core directly). | Enforces `--dry-run` preview before destructive/overwrite operations; MCP keeps `--allow-writes` default-deny gate. |
| **Named Environment Profiles (`profile list/save/use/show/delete`)** | Switching between role-specific skill sets (`security-review`, `frontend`, `minimal`) requires manual YAML editing. | Medium-high for polyglot engineers and consultants. | Uses standard `ProjectManifest` YAML files under `.skillporter/profiles/`; zero custom DSL. |
| **Unmanaged Skill Adoption (`adopt`)** | Existing skills in `.claude/skills` or `.agents/skills` cannot be backed up, updated, or exported as managed entries without manual reinstall. | Essential onboarding bridge for developers with pre-existing skills. | Runs spec validation and static security scan before adopting. |
| **Upstream Version & Hash Check (`outdated` + accurate `update --dry-run`)** | Developers cannot tell which skills actually changed upstream before running `update`. | Weekly maintenance workflow. | Read-only temporary fetch; never executes upstream code. |

### P2: Advanced Capabilities (Supported Selectively Where Clean)

1. **Custom Harness Path Overrides (`harness_paths` in `skillporter.yaml` or `SKILLPORTER_HARNESS_PATHS`)**: Supported with strict scope-boundary validation (project overrides must stay inside project root; user overrides must stay inside user home or explicit env root) so malicious manifests cannot write arbitrary host files!
2. **Cross-Harness Distinct Version Awareness**: Supported when harnesses use distinct directories (for example `.claude/skills` vs `.cursor/skills` when isolated), with an explicit architectural warning when two requested harnesses share `.agents/skills` on disk so SkillPorter never misleads the user.

### P3: Explicitly Rejected or Deferred (Challenging Scope Creep)

1. **Cloud Account Sync / Hosted Environment Store (REJECTED)**: Violates local-first trust, introduces credential/privacy liability, and duplicates what `.skillpack` archives + Git dotfiles already accomplish offline and for free.
2. **Background Filesystem Watcher Daemon (REJECTED)**: Background daemons silently mutate files during `git rebase`/`checkout`, drain laptop battery, and violate explicit predictability. Fast on-demand `status`, `sync`, and CI `lock --check` are superior.
3. **Local HTTP Daemon for Agent Control (REJECTED)**: Opens localhost port attack surface (browser SSRF / DNS rebinding). Direct CLI invocation (`--json`) and stdio MCP (`skillporter mcp`) require zero open network sockets.
4. **Hosted Marketplace Web App with Fake Social Proof (REJECTED)**: Keep the existing clean static seed/JSON registry client contract without unverified marketplace bloat or synthetic vanity counters.

---

## 3. Phase 4: Packaging Architecture Tradeoff & Shared Internal Model

### 3.1 `.skillpack` Format Evaluation

We evaluated four candidate designs for `skillporter export` and `skillporter import`:

1. **Source-Reference Manifest Only**: Tiny file (~2 KB), but fails completely offline, breaks when private Git repos lack credentials on the destination machine, and loses local custom skills (`./skills/team-conventions`) that have no remote URL.
2. **Lockfile-Only Restoration**: Ensures cryptographic hash parity, but still requires live network access to every upstream repository and cannot carry local-only skills.
3. **Raw Filesystem Tarball**: Copies `.claude/`, `.agents/`, `.cursor/` verbatim, which duplicates shared skills, hardcodes OS-specific user paths, risks leaking `.env` or secret files, and breaks when the destination machine has a different set of installed harnesses.
4. **Selected Architecture: Hybrid Self-Contained `.skillpack` Bundle (Deterministic `.tar.gz`)**:
   - Archive layout:
     - `skillpack.json`: Canonical JSON manifest (`schema_version: 1`, `format: "skillporter-pack"`, `skillporter_version`, `created_at`, `scope`, `active_profile`, `manifest` config, `lockfile` snapshot, `skills` map with `version`, `source`, `resolved_commit`, `harnesses`, `strategy`, `tree_hash`, `file_hashes`, `dependencies`, and `bundle_sha256`).
     - `skills/<skill-name>/...`: Clean, deduplicated copy of each exported skill tree (stored once per unique `(skill_name, tree_hash)` regardless of how many harnesses read it).
   - **Why Hybrid Wins**:
     - **100% Offline Restoration**: Every skill's files are inside `skills/<name>/`, so `skillporter import` works on air-gapped machines and for local/private skills without network access.
     - **Full Upstream Continuity**: Preserves `source`, `resolved_commit`, and `skillporter.lock` metadata so `skillporter outdated`, `update`, and `audit` continue working after import.
     - **Cross-Machine & Cross-OS Harness Adaptation**: On import, SkillPorter inspects the destination machine's detected harnesses, maps skills to compatible paths on Linux/macOS/Windows, warns clearly if a source harness is not installed locally, and lets the user filter via `--harness` / `--exclude-harness` or preview via `--dry-run`.
     - **Defense-in-Depth Security**:
       - **Export**: Rejects or strips `.git/`, `__pycache__/`, `.env*`, private keys, and scans exported skills for embedded credentials (`sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key`), blocking secret leakage unless `--exclude-secrets` / remediation is applied (never silently exporting live credentials). Never includes `audit.jsonl` or host environment variables.
       - **Import**: Extracts exclusively through bounded `safe_extract_tar()` (blocking `..`, absolute paths, symlinks, FIFOs/devices, duplicate case-folded entries, and decompression bombs), verifies every skill's `tree_hash` and per-file `file_hashes` against `skillpack.json` (detecting bit-rot or archive tampering), and runs `scan_skill()` static security checks before staging transactional writes. Never executes scripts inside imported skills.

### 3.2 Shared Internal Architecture

Instead of isolated command scripts, all new and upgraded commands share four cohesive core modules:

1. `skillporter/environment.py`:
   - `SkillEnvironmentState`: Unified view of one skill across `manifest`, `lockfile`, `state.json`, and on-disk harness locations (`status` classification: `HEALTHY`, `DRIFTED`, `MISSING_INSTALL`, `UNMANAGED`, `ORPHANED`, `DUPLICATE`, `CONFLICT`).
   - `EnvironmentSnapshot`: Captures the complete desired vs. actual state of a project, user home, profile, or `.skillpack` archive, and computes deterministic `EnvironmentDiff` objects (`added`, `removed`, `version_changed`, `content_changed`, `harness_changed`).
2. `skillporter/portability.py`:
   - Implements `export_skillpack()`, `inspect_skillpack()`, `plan_import_skillpack()`, and `import_skillpack()` on top of `EnvironmentSnapshot`, `safe_extract_tar`, `scan_skill`, and `install_many`.
3. `skillporter/profiles.py`:
   - Manages `.skillporter/profiles/<name>.yaml` and `.skillporter/active_profile` using `ProjectManifest` serialization so profiles require zero new config syntax.
4. `skillporter/ui.py` & `skillporter/commands/common.py`:
   - Shared CLI output primitives (`OutputConfig` honoring `--json`, `-q/--quiet`, `-v/--verbose`, `--no-color`, `NO_COLOR`), grouped `--help` formatter, compact table/summary renderers with automatic large-list truncation (`--verbose` to expand), and `Next steps:` contextual guidance.
   - Enhanced `resolve_target_harnesses()` supporting `all`, `detected`, `compatible`, comma-lists, and `--exclude-harness`.

---

## 4. Phase 5: Testable Implementation Milestones

1. **Milestone 1 (Core & CLI DX)**: Fix `--scope user` discovery + location scan caching in `diagnose.py`; add custom safe `harness_paths` support; upgrade `ui.py`, `common.py`, grouped `--help`, global `-q`/`-v`/`--no-color`; build `environment.py` and ship upgraded `status` + new `diff` command.
2. **Milestone 2 (Harness Control & Lifecycle)**: Ship `skillporter harness {list,inspect,status}`, `--exclude-harness`, `compatible` selector, `--on-conflict {fail,skip,overwrite}`, `skillporter move`, and `skillporter adopt`.
3. **Milestone 3 (Portable Environments)**: Build `portability.py` and ship `skillporter export` and `skillporter import` (`.skillpack` creation, secret guard, integrity verification, missing-harness detection, conflict policy, `--dry-run`, offline restore).
4. **Milestone 4 (Profiles & Version Intelligence)**: Build `profiles.py` (`skillporter profile {list,save,use,show,delete}`) and ship `skillporter outdated` + accurate `update --dry-run` version/hash diffing.
5. **Milestone 5 (AI Agent Skill & MCP Parity)**: Upgrade `skills/skillporter/SKILL.md`, bundle it for `skillporter self-skill`, and add `skillporter_status`, `skillporter_diff`, `skillporter_harnesses`, `skillporter_export`, `skillporter_import` to `mcp_server.py`.
6. **Milestone 6 (End-to-End Verification & Docs)**: Execute all 19 required workflow tests, cross-OS/lock/archive regression tests, `ruff`, `bandit`, standalone `.pyz` build, and update `README.md` and `docs/`.
