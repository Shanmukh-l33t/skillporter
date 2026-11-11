# Multi-Agent Engineering & Security Audit Summary

_Date: 2026-11-11 · Baseline: `5ed7207b35f8b7b71655e94d45bdcb6db25cb329` (85 tests) · Post-Audit: 95 tests_

This document synthesizes the independent investigations of the 7-specialist engineering team:
- [ARCHITECTURE_REVIEW.md](../ARCHITECTURE_REVIEW.md) — Agent 1 (Principal Software Architect)
- [PYTHON_CODE_REVIEW.md](../PYTHON_CODE_REVIEW.md) — Agent 2 (Python Backend Specialist)
- [SECURITY_AUDIT.md](../SECURITY_AUDIT.md) — Agent 3 (Defensive Security Engineer)
- [QA_AUDIT.md](../QA_AUDIT.md) — Agent 4 (QA & Test Automation Engineer)
- [HARNESS_COMPATIBILITY_AUDIT.md](../HARNESS_COMPATIBILITY_AUDIT.md) — Agent 5 (Agent Harness Compatibility Specialist)
- [PRODUCT_UX_AUDIT.md](../PRODUCT_UX_AUDIT.md) — Agent 6 (Product & Developer Experience Engineer)
- [INDEPENDENT_REVIEW.md](../INDEPENDENT_REVIEW.md) — Agent 7 (Independent Red-Team Reviewer)

---

## 1. Confirmed Bugs Discovered & Fixed

| ID | Priority | Module | Finding | Fix & Regression Test |
|---|---|---|---|---|
| **SEC-01 / BUG-PY-01** | **P0** | `install.py` | `uninstall()`, `install()`, and `rollback_skill()` joined `skill_name` directly onto the harness base path without segment validation (`skillporter remove ../../victim`). | Added `validate_skill_name_segment()` rejecting path separators, `..`, `.`, and verifying `candidate.parent.resolve() == resolved_base`. Tested in `test_uninstall_and_install_reject_path_traversal_skill_name`. |
| **BUG-PY-02 / RT-01** | **P0** | `install.py` | `_copy_skill` deleted existing destinations *before* copying and `install()` only rolled back newly created directories (`not existed_before`). A mid-transaction failure after overwriting Target 1 left Target 1 permanently mutated or deleted. | Implemented `_stage_and_copy_skill` and `_stage_and_link_skill` staging inside `.skillporter/tmp/txn-<id>/` and moving pre-existing targets to `prev-<id>` slots restored on exception. Tested in `test_partial_failure_restores_preexisting_overwritten_destination`. |
| **SEC-02 / BUG-PY-09** | **P0** | `sources.py` | `safe_extract_zip` and `safe_extract_tar` streamed unbounded bytes (`shutil.copyfileobj`) and unlimited entries, allowing decompression bombs (Zip-Bomb / Tar-Bomb). | Added `_copy_bounded()` enforcing `MAX_ARCHIVE_FILES = 1000`, `MAX_SINGLE_FILE_BYTES = 10 MiB`, and `MAX_TOTAL_ARCHIVE_BYTES = 50 MiB`. Tested in `test_zip_and_tar_decompression_bomb_and_file_count_limits`. |
| **SEC-03** | **P0** | `sources.py` | `git clone` did not explicitly disable `protocol.ext`, `core.fsmonitor`, or `core.symlinks` via `-c` flags. | Passed `-c protocol.ext.allow=never -c core.fsmonitor=false -c core.symlinks=false` to `git clone`. |
| **BUG-PY-06 / RT-02** | **P0** | `frontmatter.py`, `security.py` | `discover()` used `root.rglob("SKILL.md")`, which recursed inside a skill's own `references/` subdirectories and could follow symlink cycles; `compute_tree_hash` used `rglob("*")` instead of `os.walk(..., followlinks=False)`. | Rewrote `discover()` to prune directories once `SKILL.md` is found and track `(st_dev, st_ino)` inodes; updated `compute_tree_hash()` to `os.walk(..., followlinks=False)`. Tested in `test_discover_stops_at_skill_root_and_handles_symlink_loops`. |
| **BUG-PY-10 / DX-02** | **P0** | `cli.py` | `skillporter sync` unconditionally passed `force=True` using the first alphabetical skill path (`.agents/skills`), silently overwriting user edits in `.claude/skills`. | `sync` now checks `diag.drifted` and refuses to overwrite drifted copies unless `--force` is passed (which syncs from the newest mtime and snapshots backups). Tested in `test_sync_refuses_to_overwrite_drifted_copies_without_force`. |
| **BUG-PY-04 / PY-05** | **P1** | `frontmatter.py` | `split_frontmatter` used `text.split("---", 2)`, which split on inline `---` inside YAML strings; tab indentation in YAML was ignored instead of flagged. | Implemented line-anchored `^---` / `^...` splitting, UTF-8 BOM handling, tab-indentation error (`frontmatter-tab-indentation`), and `Issue.category` (`spec`, `recommendation`, `harness-compatibility`). Tested in `test_frontmatter_inline_triple_dash_and_tab_indentation_and_bom`. |
| **BUG-PY-07** | **P1** | `diagnose.py` | `diagnose()` skipped `validate()` on secondary copies of a skill (`if name in seen: continue`), missing corrupted frontmatter in mirrored copies. | `diagnose()` now validates every discovered copy of a skill and aggregates errors across all copies in `is_skill_valid()`. Tested in `test_diagnose_validates_secondary_skill_copies`. |
| **SEC-04 & SEC-05** | **P1** | `harnesses.py`, `security.py` | `load_adapter_file()` did not reject `..` in project/user adapter paths; `scan_skill()` flagged byte-0 UTF-8 BOM as `sec-hidden-unicode` and missed `base64 -d \| sh` and `curl --data @file`. | Added path traversal checks in `load_adapter_file()`, stripped byte-0 BOM before Unicode check, added `sec-obfuscated-exec` and `sec-data-exfil`, and capped per-file scan reads at 2 MiB. Tested in `test_custom_adapter_rejects_traversal_paths` and `test_security_scanner_detects_base64_pipe_and_data_exfil`. |
| **COMPAT-01 / DX-01** | **P1** | `diagnose.py`, `cli.py` | `doctor` did not expose explicit lifecycle states (`FOUND`, `VALID`, `COMPATIBLE`, `INSTALLED`, `VERIFIED`, `UNVERIFIED`, `MISSING`) or exact remediation commands. | Added `HarnessReport.explicit_states()` and upgraded `skillporter doctor` (text and `--json`). Tested in `test_doctor_explicit_lifecycle_states_and_remediations`. |

---

## 2. Disagreements & Orchestrator Resolutions

1. **Adding `PyYAML` vs Hardening the Built-in Frontmatter Parser**:
   - *Proposal*: Consider adding `PyYAML` for YAML parsing.
   - *Red-Team Challenge (Agent 7)*: Adding `PyYAML` breaks the zero-dependency guarantee that powers the 52 KB standalone `skillporter.pyz` zipapp, PEP-668-safe `install.sh`, and zero-install `npx` wrapper, while `SKILL.md` frontmatter only uses 6 top-level fields defined by `agentskills.io`.
   - *Resolution*: Keep zero external runtime dependencies; fix line-anchored `---` splitting, BOM handling, tab-indentation rejection, and list/map parsing directly in `frontmatter.py`.
2. **Where to Place Staging Directories During Transactional Swaps**:
   - *Proposal (Agent 1)*: Stage in `dest.parent / f".{dest.name}.staging"`.
   - *Red-Team Challenge (Agent 7)*: If `SIGKILL` interrupts the process, a leftover hidden directory inside `.claude/skills/` containing `SKILL.md` could be discovered by recursive scanners.
   - *Resolution*: Stage inside `.skillporter/tmp/txn-<id>/` (which is excluded from `discover()` and all harness scan paths) AND ignore dot-prefixed entries inside `scan_location()`.
