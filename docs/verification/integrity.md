# Workspace Integrity: Scan/Status Accuracy Verification

Scope: `skillporter/diagnose.py`, `skillporter/environment.py`, `skillporter/harnesses.py` (detection),
`skillporter/commands/doctor.py` (consumers). CLI formatting, parsers and README are untouched.

All evidence below comes from disposable temporary projects. No real user files were read or modified.

## Symptoms and root causes

| Symptom | Root cause | Fix |
| --- | --- | --- |
| Every committed `.claude/skills/x` was reported "not visible to codex" in a repo with no `.codex`, `.agents` or `cursor` directory | `diagnose()` fell back to the hardcoded `claude-code, codex, cursor` set whenever no manifest existed, so absent harnesses were treated as required | The default requirement set is now the manifest harnesses, else only harnesses whose scanned path exists on disk. Explicit `--harness` still means "require exactly these". |
| `status` selected `codex`/`hermes`/`openclaw` as "active targets" of an empty workspace | `status` built targets from `CORE_HARNESS_NAMES` (plus detected harnesses) instead of the requirement set `diagnose()` had just computed | `status`/`doctor` reuse `Diagnosis.default_harnesses`; `capture_environment` no longer unions the core set |
| Unversioned skills showed `VERSION 1.0.0` | `SkillEnvironmentEntry.version` defaulted to `1.0.0`, and manifest/state/lock values only overrode that placeholder | Version is `""` unless the on-disk frontmatter (single value across copies) or, for absent skills, state/lock/manifest declares one. Copies declaring different versions are reported as lock drift. |
| `status` said `HEALTHY` while a skill was reported `DUPLICATE` | `healthy`/`attention_skills` enumerated a status allowlist that omitted `DUPLICATE` | Both use the complement: every status other than `SYNCED`/`UNMANAGED` needs attention. |
| `.claude/skills` symlinked to a missing worktree was logged as content drift and as a broken harness path | `scan_location()` tested `exists()` before `is_symlink()`, and `Location.status` returned `missing`; such a root has no copies, so `status` also emitted `missing on disk` lock drift and `doctor` printed "content drift: 1" | A dangling harness root is now `broken` with the link recorded, contributes no copies, and produces only the broken-link finding. `doctor` reports no drift for it. |
| `doctor` counted a real drift it could never repair ("found before repair: 1, repaired: 0") | The lockfile "missing on disk" sentence was matched by the `{name} ` prefix test and classified as hash drift | `lock_drifted` is driven by an explicit set of skills whose on-disk hash actually differs |
| The same skill tree was listed and hashed repeatedly per command | `.agents/skills` is scanned once per adapter with its own recursion mode; copies are re-hashed by `doctor`/`environment` after `diagnose()` already hashed them | `Diagnosis.tree_hash()` memoizes hashes and `scan_location()` shares one memoized directory listing. Repeated scans within one diagnosis: 1 hash per copy, 1 listing per directory, 1 `detect_harnesses()` call in `status`. |

## Regression tests

`tests/test_environment_integrity.py` (new) and one adjusted expectation in `tests/test_skillporter.py`:

- `test_claude_copy_does_not_require_absent_default_targets` — committed `.claude` copy is healthy; explicit
  `--harness codex` still reports it missing; `doctor --fix` creates no `.agents` directory.
- `test_status_reports_only_known_versions` — unversioned skill reports `""`, declared `1.0.0` wins over a
  manifest claim of `2.3.0`.
- `test_duplicate_skill_needs_attention_even_if_hashes_match` — identical copies in two harness paths are
  `DUPLICATE`, unhealthy, and not reported as drift.
- `test_shared_location_lists_and_hashes_once_per_status` — one status run = 1 hash per copy, 1 listing of
  `.agents/skills`, 1 detection pass; after an edit the count is exactly 2; nested (`cursor` recursive)
  and flat (`codex`) reachability stay distinct.
- `test_dangling_harness_root_is_broken_not_content_drift` — `broken` status, no drift, preview leaves the
  link, `--fix` removes it and nothing else.
- `test_missing_locked_copy_is_not_a_content_mismatch` — deleted copy is `ORPHANED` with "missing on disk"
  lock drift, not hash drift.
- `test_add_repair_and_remove_real_shared_install` — real `add --dry-run` (no writes), `add`, `lock`,
  verified edit, `status` drift, `doctor --fix --dry-run` leaving the file untouched, `doctor --fix`
  restoring the exact bytes and leaving the lockfile byte-identical, `lock --check` clean,
  `remove --harness cursor` preserving the shared copy for `codex`, final `remove` deleting only the
  install and leaving the upstream source untouched.

Commands (Windows, Python 3.14; and Linux/WSL Python 3.12 for real symlinks):

```bash
python -m pytest tests -q
ruff check skillporter tests
# Linux-only symlink coverage (ext4/WSL)
python3 -m pytest tests/test_environment_integrity.py
```

Results:

- Windows: every test module was run (the full single run was split per module because one pre-existing
  test blocks on network git). All new and neighbouring suites pass. The only failures are environmental
  and reproduce on the untouched baseline commit `bdfb9e6` in a separate worktree:
  `tests/test_instructions_hardening.py` (5) + `tests/test_portability_fixes.py`
  (`test_fetched_source_structural_escape_is_never_overridable`) + `tests/test_skillporter.py`
  (`test_diagnose_detects_broken_symlink`) all fail at `symlink_to` with `WinError 1314` on an
  unprivileged Windows account; `tests/test_redteam_audit_fixes.py::test_large_instruction_analysis_completes_under_300ms`
  is a wall-clock assertion (`0.356s` vs `0.35s`) on an untouched module;
  `tests/test_second_pass_security_review.py::test_lock_check_detects_manifest_source_repointing_to_untrusted_repo`
  hangs cloning `https://github.com/...` on the baseline too.
- Linux (WSL, ext4, real symlinks): `tests/test_environment_integrity.py tests/test_regressions.py`
  = **11 passed**, including the dangling-symlink case Windows cannot create.

## Real CLI evidence (disposable project)

Fixture: `skillporter.yaml` with `claude-code, codex, cursor`; two skills added for all three harnesses;
`skillporter lock`; one byte appended to `.agents/skills/release-notes/SKILL.md`.

Before repair — real drift is detected, and only `VERSION` values that exist are shown:

```text
$ skillporter status
  Active targets:     claude-code, codex, cursor
  Skills summary:     2 total (2 synced, 0 unmanaged, 0 needing attention)
  deploy-checklist  1.2.0    SYNCED  yes
  release-notes     1.2.0    SYNCED  yes

$ skillporter doctor
Content drift:      1 skill(s)
  release-notes     DRIFTED  b3efad2d060b  2   claude-code, codex, cursor
Issues found:
  - skill 'release-notes' has content drift across copies: .agents/skills/release-notes (b3efad2d), .claude/skills/release-notes (5980fd2f)
  - lockfile drift: 'release-notes' at .agents/skills/release-notes (b3efad2d) differs from skillporter.lock (5980fd2f)
Status: UNHEALTHY (2 issue(s) found).   [exit 1]
```

Preview changes nothing; apply restores the locked bytes and the follow-up is clean:

```text
$ skillporter doctor --fix --dry-run
Content drift:      1 skill(s)      [exit 1]

$ skillporter doctor --fix
Content drift:      0 remaining (found before repair: 1, repaired: 1)
Repairs applied:
  ~ release-notes -> codex (.agents\skills\release-notes, sha256:5980fd2f8387)
Status: HEALTHY (all checked skills reachable, valid, and hash-verified).   [exit 0]

$ skillporter status
  Skills summary:     2 total (2 synced, 0 unmanaged, 0 needing attention)   [exit 0]
```

Shared-path removal keeps the copy for the remaining owner:

```text
$ skillporter remove release-notes --harness cursor
- Removed 'release-notes' from 0 destination(s) (source preserved)
  = cursor         preserved-shared ...\project\.agents\skills\release-notes
  Note: shared .agents/skills directory retained for active sibling harness(es)

$ skillporter diagnose
no findings — every skill is reachable and synchronized across checked harnesses.   [exit 0]
```

Committed `.claude`-only skill, no manifest, no other harness directories:

```text
$ skillporter diagnose
no findings ...   [exit 0]
$ skillporter diagnose --harness codex
  - skill 'release-notes' is not visible to: codex (visible to: claude-code)   [exit 1]
```

## Compatibility

No JSON key was removed or renamed. Behaviour changes visible in JSON:

- `status`/`environment` `skills[*].version` is `""` when nothing declares a version (was `"1.0.0"`).
- `status` `selected_harnesses`, `per_harness`, and `doctor` `checked_harnesses` only list harnesses that
  are actually installed/declared, instead of the core set by default.
- `status` is unhealthy when a skill is `DUPLICATE` (previously `healthy: true`).
- `diagnose --json` `findings` no longer contains "not visible to: codex/cursor" for harnesses that are
  not present at all unless they are named with `--harness`.

## Known limits

- Hash/listing memoization is per `Diagnosis` object: two separate commands still re-scan (freshness is
  preserved deliberately; a cross-command cache would report stale hashes after an edit).
- Duplicate copies are reported and counted as needing attention; no automatic dedupe is added.
- A harness root that is a symlink to a live target is followed; only dangling links are broken.