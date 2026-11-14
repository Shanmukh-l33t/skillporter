# AGENT 1 — PRINCIPAL SOFTWARE ARCHITECT REVIEW

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Baseline Commit**: `5ed7207b35f8b7b71655e94d45bdcb6db25cb329` (v2.0.0, 85 passing tests)
**Role**: Principal Software Architect

---

## 1. Codebase & Module Boundary Assessment

Skillporter's current architecture consists of 12 focused Python modules under `skillporter/` with zero external runtime dependencies:

- `harnesses.py` — Data-driven registry of 19 harness adapters, detection specs, capabilities, and declarative adapter loader.
- `frontmatter.py` — `SKILL.md` frontmatter parser, validator, and recursive skill discovery.
- `formats.py` — Package structure inspection and controlled rule-file adaptation (`.mdc`, `.instructions.md`, etc.).
- `security.py` — Deterministic SHA-256 tree hashing and static security assessment (`STATIC_SECURITY_ASSESSMENT`).
- `sources.py` — Local, archive (`.zip`/`.tar.gz`), GitHub, Git URL, and registry source resolution.
- `atomic.py` — Crash-safe atomic file writes (`os.replace` with `fsync`) for state, manifest, and lockfile.
- `state.py` — Ownership tracking (`.skillporter/state.json`) and rollback snapshots (`.skillporter/backups/`).
- `manifest.py` — `skillporter.yaml` and `skillporter.lock` parser/serializer.
- `diagnose.py` — Cross-harness reachability, SHA-256 drift, broken symlink, and duplicate-loading diagnosis.
- `install.py` — Installation planning, copy/symlink execution, uninstall, and rollback.
- `registry.py` — Curated seed catalog, bounded remote JSON index client, and deterministic `.tar.gz` packager.
- `mcp_server.py` & `cli.py` / `ui.py` — User and agent interfaces.

### Strengths
1. **Single Authoritative Core**: `npx`, `uvx`, standalone `.pyz`, MCP server, and GitHub Action all invoke the same Python core.
2. **Zero Runtime Dependencies**: Runs on any Python 3.9+ interpreter without C extensions or third-party supply-chain risk.
3. **Data-Driven Harness Registry**: Adding a harness requires adding a `Harness` dataclass entry in `harnesses.py`, not editing `install.py` or `diagnose.py`.

---

## 2. Architectural Weaknesses Identified

### A1. Directory Replacement in `install.py` Is Not Staged or Fully Transactional on Updates
While `atomic.py` made file writes (`state.json`, `skillporter.yaml`, `skillporter.lock`) crash-safe, **directory replacement in `install.py` (`_copy_skill` and `_link_skill`) is not atomic and does not restore overwritten directories on mid-transaction failure**:
- `_copy_skill` runs `shutil.rmtree(dest)` *before* `shutil.copytree(src, dest)`. If `copytree` fails partway through, `dest` is destroyed.
- In `install()`, `created_in_txn` only tracks destinations where `not existed_before`. If Target 1 already existed (`force=True`) and Target 2 fails (`InstallError`), Target 1 is left overwritten with the new version instead of being restored to its pre-transaction state.

### A2. Skill Identity Conflates Directory Basename with Canonical Skill Identity
`discover()` in `frontmatter.py` and `diagnose()` in `diagnose.py` key skills solely by `skill_md.parent.name` and skip subsequent `SKILL.md` files with the same parent directory name (`if name in seen: continue`).
- Consequence 1: Secondary copies of a skill are never validated for frontmatter errors in `diagnose()`.
- Consequence 2: Nested `SKILL.md` files inside a skill's own `references/` or `assets/` subdirectories would be discovered as separate skills because `discover()` uses raw `root.rglob("SKILL.md")` without stopping at a skill root boundary.

### A3. Compatibility vs Verification State Conflation
`HarnessReport` and `diagnose` output `"yes"`, `"MISSING"`, `"DRIFT"`, `"DUPLICATE"`, whereas users and CI need explicit separation between:
- Skill validity (`FOUND`, `VALID`, `INVALID`)
- Harness compatibility (`COMPATIBLE`, `ADAPTED`, `INCOMPATIBLE`)
- Filesystem installation state (`INSTALLED`, `MISSING`, `DRIFT`, `DUPLICATE`, `BROKEN`)
- Evidence level (`VERIFIED` only when runtime-verified, vs `DOC_VERIFIED` / `UNVERIFIED`)

### A4. Lack of Concurrency Locking Around State & Install Transactions
Two concurrent `skillporter` processes operating on the same repository can race on `load_state()` -> `save_state()` (lost update) or simultaneously modify `.agents/skills/<name>`. An advisory lockfile (`.skillporter/lock`) around mutating operations eliminates this race without adding dependencies.

---

## 3. Architectural Recommendations (No Rewrite Needed)

1. **Staged Directory Swap & Full Transaction Rollback (`install.py`)**: Copy into `.staging-<id>` in the destination parent directory, move any existing `dest` to `.old-<id>`, rename `.staging-<id>` -> `dest`, and on any exception in the multi-harness loop, restore every `.old-<id>` back to `dest`.
2. **Stop-at-Skill-Root Discovery & Multi-Copy Validation (`frontmatter.py`, `diagnose.py`)**: Walk directories top-down, stop recursing into a directory once `SKILL.md` is found, guard against symlink cycles via `(st_dev, st_ino)`, and validate every discovered copy.
3. **Explicit Lifecycle & Verification State Model (`diagnose.py`, `cli.py`)**: Expose `FOUND`, `VALID`, `COMPATIBLE`, `INSTALLED`, `VERIFIED`, `UNVERIFIED`, `MISSING` in `Diagnosis` and `skillporter doctor`.
4. **Advisory Workspace Lock (`atomic.py`)**: Add a context-managed `workspace_lock(root)` using `fcntl` (POSIX) / `msvcrt` (Windows).
