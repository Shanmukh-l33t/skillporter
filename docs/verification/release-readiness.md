# Release-readiness follow-up

This candidate builds on `2bcd927`. The original [workflow matrix](workflows.md), [receiver checks](receivers.md), and [scale evidence](scale.md) retain their original scope. A checked path is not a live receiver listing, and a listing is not skill activation.

## What changed and how it was checked

| Workflow | Observed result | Evidence |
|---|---|---|
| Fix a broken copy | `doctor --fix --dry-run` listed one missing Windsurf destination and one stale temp. Preview changed no observed paths, bytes, or mtimes. Apply repaired those items; a second apply had no repair steps. Source and restored SHA-256 matched, `skillporter.lock` stayed identical, and `lock --check` exited 0. | Integration verified on Windows; independent Astra fixture, replayed at `0059132`. Apply may also perform transaction housekeeping. |
| Refuse an unfinished manifest edit | On `2bcd927`, `harnesses: [claude-code, windsurf` could cause `doctor --fix` and `sync` to install for fallback targets. Both this edit and a missing-colon variant now return exit 2 with a line-numbered error, without changing the workspace or advisory lock in the replay. | Independent audit at `e68ebeb`, seven command variants per edit. [`test_doctor_repair_preview.py`](../../tests/test_doctor_repair_preview.py) covers unfinished and unbracketed target lists. |
| Respect assignments during repair and sync | The audit at `e68ebeb` found `doctor --fix` ignored an empty per-skill list and `sync` ignored an excluded target. The integrated follow-up regression checks diagnosis and repair, manifest sync, and `sync --prefer`, including preview paths and the actual writes. Omit a skill's `harnesses` to inherit; use `harnesses: []` to assign it to no targets. | Integration verified in disposable Windows projects by the CLI regressions. Excluding a managed target does not make a directory invisible to another harness that already reads it. |
| Recreate a profile | After export/import and removal of one shared copy, `profile use` reported 1 skill, 3 logical targets, 1 destination written; the second use wrote 0 destinations. Unassigned skills are not listed under `skills_to_sync` in preview. | Independent Windows subprocess replay at `e68ebeb` for counts; [`test_ready_state_workflows.py`](../../tests/test_ready_state_workflows.py) covers counts and assignments. |
| Adopt, move and reproduce | `init → adopt → lock → move → outdated` now gives `UP-TO-DATE` for the moved adopted copy. State, manifest, and lock point to the surviving local copy. Editing and rolling back restored the original skill bytes without recreating the old path. `init` retains managed targets and no longer guesses owners for an untracked shared `.agents` path. | Integration verified on Windows, independently re-run at `e68ebeb`. |
| Pack repeatably | Two `pack` invocations at different times produced identical `.tar.gz` bytes. Both provenance digests matched, and adding the archive restored the two fixture files byte-for-byte. Provenance timestamps are still timestamps. | Independent Windows CLI replay at `e68ebeb`, plus repeatability regression. |
| Restore Windows instruction snapshots | `consolidate --apply` followed by `consolidate --rollback` exited 0 and preserved pre-rollback snapshots (bytes and mtimes) at 260, 273, and 320-character paths. Restored text matched; CRLF-to-LF normalization existed before this pass. | Independent Windows CLI replay at `e68ebeb`; UNC and already-inaccessible source paths were not verified. |
| Duplicate copies | Diagnosis now names the paths and says runtime precedence was not checked. It no longer claims the receiving harness injected both copies. | Windows fixture verified; see `test_duplicate_copy_is_reported_by_diagnose_too`. |

## Scale checkpoint

One fresh process per cell, WSL Ubuntu/ext4 via `python3 scripts/scale_benchmark.py --sizes 10 100 1000 5000 --timeout 50`, against `2bcd927` before this round's workflow fixes. These are synthetic mixed inventories, not live harness sessions or latency targets. The outer run timed out after the last text result; the 5,000-skill `list --json` cell was not captured in this run.

| Skills | `status` seconds / lines | `diagnose` seconds / lines | `list` seconds / lines |
|---:|---:|---:|---:|
| 10 | 1.01 / 27 | 0.75 / 10 | 0.75 / 13 |
| 100 | 0.87 / 36 | 1.05 / 10 | 0.71 / 14 |
| 1,000 | 6.07 / 36 | 3.76 / 10 | 2.55 / 14 |
| 5,000 | 18.75 / 36 | 18.77 / 10 | 6.84 / 14 |

At 5,000 skills `status --json` produced 5,478,271 bytes (69,952 KiB peak RSS); `diagnose --json` produced 13,970,178 bytes (111,436 KiB). A TUI would not solve scan latency. Keep the bounded CLI and machine-readable output; profile scanning before adding an interface. `doctor` exposes the entire repair plan; its output is not capped by the status/diagnose limits.

## Remaining release risks

- `rollback --dry-run` still previews update history only; an actual rollback can restore a verified initial baseline that the preview does not report.
- A move from an external upstream preserves that provenance; the independent audit found a manifest that still referred to the original target could recreate the old destination on the next `sync`. Do not claim all move-and-sync combinations are verified.
- Live receiver evidence is historical and specific to the scope and receiver version in [receivers.md](receivers.md). No new runtime discovery or activation coverage, customer retention evidence, or production release is claimed here.
