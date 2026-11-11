# Final Release Gate Checklist — Skillporter v2.0

**Audited Commit**: `8001082bd1b46ebed22bca6990b80b98a095f3a7` (plus release-gate verification tests & `diagnose()` auto-recovery hook)
**Date**: 2026-11-11
**Host Environment**: Linux `6.8.0-149-generic` x86_64 (Python `3.12.3` and Python `3.14.9`, Node.js `v26.12.1`)

---

## 1. Ten-Point Release Gate Verification Matrix

| # | Verification Item | Method & Test Reference | Actual Result | Status |
|---|---|---|---|---|
| **1** | **Real subprocess termination during transactional installation** | Spawned child `subprocess.run([sys.executable, ...])` executing `install(..., force=True)` that sends `os.kill(os.getpid(), signal.SIGKILL)` (`returncode == -9`) immediately after moving `dest` to `prev-*` (`tests/test_release_gate.py::test_real_subprocess_sigkill_mid_swap_and_automatic_recovery`). | Child terminated with `-9` (`SIGKILL`); write-ahead `journal.json` and `prev-*` preserved intact in `.skillporter/tmp/txn-*`. | **PASS (Verified Live on Linux)** |
| **2** | **Recovery from an interrupted directory swap** | Called `diagnose(tmp_path)` (and `recover_interrupted_transactions(tmp_path)`) immediately after the `SIGKILL` crash above (`tests/test_release_gate.py` & `tests/test_hardening_audit.py`). | `diagnose()` and `install()` automatically restored `dest` from `prev-*` with matching SHA-256 `v1_hash` and removed the stale `txn-*` directory. | **PASS (Verified Live on Linux)** |
| **3** | **Cross-process locking on Windows** | Inspected `atomic.py:workspace_lock` `_IS_WINDOWS` branch (`fh.seek(0)`, 1-byte initialization, `msvcrt.LK_NBLCK` retry loop, `TimeoutError`, and `LK_UNLCK`) and unit-tested via `tests/test_release_gate.py::test_windows_msvcrt_lock_branch_behavior`. **Honest platform note**: Commit `8001082` has not yet been pushed to the GitHub Actions `windows-latest` runner (per the no-push instruction), so native Windows kernel multi-process locking on this commit is unit-verified on Linux, not kernel-executed on Windows. | Unit test verified byte-0 seek, 3-attempt retry recovery, and `TimeoutError` on persistent contention. Native Windows kernel run pending push to CI. | **PASS (Unit-Verified; Native Windows Pending CI Push)** |
| **4** | **Cross-process locking on Linux** | Spawned background `subprocess.Popen` holding `workspace_lock(tmp_path)` (`flock LOCK_EX`); parent process verified `TimeoutError` on `timeout_s=0.15`, sent `SIGKILL` to holder, and verified immediate kernel lock release and re-acquisition (`tests/test_release_gate.py::test_linux_cross_process_lock_contention_and_crash_release`). | Contention raised `TimeoutError` at 0.15s; `SIGKILL` released kernel `flock` immediately; subsequent lock acquisition succeeded. | **PASS (Verified Live on Linux)** |
| **5** | **Archive path collisions on case-insensitive filesystems** | Tested `.zip` with `my-skill/SKILL.md` + `my-skill/skill.md` and `.tar` with `my-skill/SKILL.md` + `my-skill/./SKILL.md` (`tests/test_hardening_audit.py::test_zip_and_tar_reject_duplicate_and_case_colliding_entries`). | Both rejected with `SourceError: duplicate or case-colliding ... entry` before extraction. | **PASS (Verified Live)** |
| **6** | **Sync conflicts involving multiple modified files** | Tested drifted copies where child script `scripts/run.py` was modified, tested equal tree-wide `st_mtime_ns` refusal under `sync --force`, and verified `--prefer <path>` resolution (`tests/test_hardening_audit.py::test_sync_handles_equal_mtimes_child_script_edits_and_prefer_flag`). | Unforced `sync` refused to overwrite; equal-mtime `sync --force` refused to guess; `--prefer` synced deterministically and snapshotted backups. | **PASS (Verified Live)** |
| **7** | **Backup integrity verification** | Tampered with `.skillporter/backups/<skill>/<id>/<skill>/SKILL.md` on disk and invoked `rollback_skill()` (`tests/test_hardening_audit.py::test_rollback_rejects_corrupted_backup_snapshot`). | `rollback_skill()` detected SHA-256 mismatch against `chosen.tree_hash` and raised `InstallError: backup ... is corrupted` without touching the working install. | **PASS (Verified Live)** |
| **8** | **Standalone PYZ execution** | Built `dist/skillporter.pyz` (`scripts/build_standalone.py`) and executed `python3 dist/skillporter.pyz diagnose <tmp>` and `./dist/skillporter.pyz --version` (`tests/test_release_gate.py::test_standalone_pyz_and_npm_wrapper_diagnose_and_scan`). | Exited `0`, output `skillporter 2.0.0` and `no findings`. | **PASS (Verified Live)** |
| **9** | **npm wrapper execution** | Executed `node npm/bin/skillporter.js scan <tmp>` and `node npm/bin/skillporter.js --version` (`tests/test_release_gate.py::test_standalone_pyz_and_npm_wrapper_diagnose_and_scan`). | Exited `0`, delegated to bundled `skillporter.pyz`, output `PASSED`. | **PASS (Verified Live)** |
| **10** | **Wheel and source distribution installation in clean environments** | Created two isolated virtualenvs (`clean-wheel-venv` and `clean-sdist-venv`); installed `dist/skillporter-2.0.0-py3-none-any.whl` (`--no-index`) and `dist/skillporter-2.0.0.tar.gz` (`--no-binary :all:`), then ran `skillporter --version`, `skillporter validate .`, and `skillporter scan .`. | Both clean virtualenvs installed with 0 external dependencies and passed `validate` and `scan` with exit code `0`. | **PASS (Verified Live)** |

---

## 2. Quality, Security & Packaging Gates

- **Test Suite**: `106 passed in 1.25s` (`tests/test_skillporter.py`, `tests/test_regressions.py`, `tests/test_v2_ecosystem.py`, `tests/test_archive_security.py`, `tests/test_atomic_writes.py`, `tests/test_hardening_audit.py`, `tests/test_release_gate.py`).
- **Ruff Linter**: `ruff check .` -> `All checks passed!` (0 warnings/errors).
- **Bandit SAST**: `bandit -r skillporter -ll -q` -> `0 High, 0 Medium findings`.
- **Twine Package Check**: `twine check dist/*.tar.gz dist/*.whl` -> `PASSED` for both wheel and sdist.
- **Gitleaks Secret Scan**: `gitleaks detect --source . -v` -> `0 leaks found` across all commits.
- **Git Tree Hygiene**: `git status --porcelain` is clean; `.venv/`, `dist/`, `build/`, `*.egg-info/`, and `.skillporter/` are gitignored and excluded from tracked files.

---

## 3. Evidence-Based Release Verdict

**VERDICT: RELEASE CANDIDATE** (Ready to promote to `PRODUCTION READY` as soon as this final commit runs through the `windows-latest` and `macos-latest` GitHub Actions matrix on push, since native Windows/macOS kernels were not executed locally for the post-`ec8205f` commits).
