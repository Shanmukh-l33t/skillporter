# AGENT 4 — QA AND TEST AUTOMATION AUDIT

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Role**: Lead QA & Test Automation Engineer

---

## 1. Existing Test Suite Baseline

- **Total tests**: 85 passing (`0.49s` on Python 3.12 Linux; also verified in CI on Ubuntu Python 3.9–3.13, macOS Python 3.12, and Windows Python 3.12).
- **Test files**:
  - `tests/test_skillporter.py` (32 tests: v1 core validation, matrix, diagnose, install/uninstall, CLI exit codes).
  - `tests/test_regressions.py` (4 tests: duplicate row suppression, user-home isolation).
  - `tests/test_v2_ecosystem.py` (24 tests: 19 harnesses, drift, duplicates, relative symlinks, format adaptation, security scanner, rollback, git `add`, `init`/`sync`/`lock`/`doctor`, MCP JSON-RPC, NPX launcher).
  - `tests/test_archive_security.py` (16 tests: Zip-Slip, Tar-Slip, Windows backslash traversal, symlinks/hardlinks, git ref injection).
  - `tests/test_atomic_writes.py` (9 tests: crash-safe atomic file replacement and temp cleanup).

---

## 2. Missing Test Coverage & Edge Cases Identified

1. **Pre-existing Destination Restoration on Partial Install Failure**:
   - `test_transactional_install_rolls_back_on_partial_failure` only tested rolling back a *newly created* directory (`not existed_before`). It did **not** test what happens when Target 1 already has v1 installed, `install(..., force=True)` overwrites Target 1 with v2, and Target 2 fails (`OSError` / read-only or symlink conflict). Currently, Target 1 is left with v2 instead of rolling back to v1!
2. **Path Traversal in `uninstall` / `install`**:
   - No test tried `uninstall(tmp_path, "../../victim", ["codex"])` or `install(..., skill_name_override="../victim")`.
3. **Archive Bomb / Size Limit Enforcement**:
   - No test verified rejection of oversized archive members (>10 MiB) or excessive file counts (>1,000 files).
4. **Frontmatter Inline `---` and Tab Indentation**:
   - No test checked `SKILL.md` with `---` inside a description string (`description: "A --- B. Use when testing."`) or tab indentation in YAML frontmatter.
5. **Nested `SKILL.md` Inside `references/` or Symlink Cycles**:
   - No test verified that a `SKILL.md` placed inside `<skill>/references/example/SKILL.md` is ignored by `discover()` and `scan_location()`, or that a circular directory symlink (`ln -s . loop`) does not cause an infinite loop.
6. **Multi-Copy Validation in `diagnose()`**:
   - No test verified that if `.agents/skills/foo/SKILL.md` is valid and `.claude/skills/foo/SKILL.md` has invalid frontmatter, `diagnose()` still flags the invalid frontmatter in the second copy.
7. **Drift Protection During `skillporter sync`**:
   - No test verified that `skillporter sync` refuses to blindly clobber a user's modified skill copy when two copies in the workspace have drifted without `--force`.
8. **Concurrent Lock Acquisition**:
   - No test verified `workspace_lock` behavior across overlapping operations.

---

## 3. QA Action Plan

Add a dedicated `tests/test_hardening_audit.py` suite covering all 8 gap areas above with deterministic, isolated `tmp_path` fixtures that run on Linux, macOS, and Windows.
