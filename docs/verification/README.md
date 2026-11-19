# First-five-minutes integration: evidence index

Branch `product/first-five-minutes` (base `bdfb9e6`, Skillporter 3.2.0). Integration
commit `6f82970`, 2026-11-19. Everything below was produced on this host with disposable
projects, a synthetic `HOME`, and no live harness or real user configuration touched.

## What was integrated

| Lane | Commit | Effect |
|---|---|---|
| discovery | `c4c35c1` | short first-look output (`status`/`diagnose`/`list`), `list --search/--harness/--managed-only/--unmanaged-only`, drill-down guidance |
| harness-checks | `1022611` | [receiver listings](receivers.md): Codex/OpenCode list installed skills; Codex user scope stays unverified |
| claim-honesty | `20cc110` | `add` states what it verified on disk and what it did not (discovery in the harness) |
| integrity | `c808791` | one target-selection source of truth (`diagnosis.default_harnesses`), real versions, one scan per tree — [integrity.md](integrity.md) |
| removal-preview | `5888568` | `remove` preview/apply parity, one row per destination, shared owners preserved — [removal.md](removal.md) |
| repair-preview | `b4f55af` | `doctor --fix` plans every step, refuses unsafe or unauthorized repairs |
| verification | `b100d46` | published-3.2.0 claim audit and replay probes — [workflows.md](workflows.md) |
| scale | `fb1fcee` | [scale.md](scale.md) baseline, `scripts/scale_benchmark.py` |
| integration fixes | `4fdce70`, `c26b790`, `d404e73`, `cce91bb` | inventory-only `list` lookup, doctor repair targets, non-quadratic validity check, clean corrupt-manifest error |

## Customer workflow, as it now behaves

Full transcript: [evidence/cli-samples.txt](evidence/cli-samples.txt) (project with one
unmanaged Claude-only skill, then a two-harness install, then a removal preview).

```
$ skillporter status
skillporter 3.2.0 · environment status (project)  [HEALTHY]
  Skills:             1 total (0 synced, 1 unmanaged)          # 12 lines, 710 B, exit 0

$ skillporter list
hello  untracked  no       claude-code, cline, cursor, github-copilot (+2)   # 4 lines, 223 B

$ skillporter diagnose
Filesystem checks only; runtime discovery was not checked.
1 skill(s) found · no findings                                 # 5 lines, 300 B, exit 0

$ skillporter add <src> --harness claude-code --harness codex --offline
Verified 2 destination(s) on disk: byte-identical to the source (sha256), source left intact.
Not verified: whether each harness discovers or loads the skill (no runtime check).
```

An unversioned, single-copy skill is reported `untracked`, not `1.0.0`, and it is not called
damaged for lacking copies in harnesses nobody asked for. After a shared `.agents/skills`
directory exists, the same skill is again listed as "not visible to" the nine harnesses that
read that directory (see Limits). `doctor` prints the same evidence scope, labels its table
"HARNESSES (ON DISK)" and ends with `HEALTHY (no issues found by filesystem checks)`.

## Measurements

Same case set as [scale.md](scale.md): WSL2 Ubuntu 24.04, ext4, Python 3.12.3, i7-8850H.
Baseline rows are the scale lane's recorded single samples at a 60 s cap; final rows are
medians of `--repeats 3` at the same 60 s cap on the integrated tree
([raw](evidence/scale-final.csv)). [evidence/scale-baseline-timeout-20.csv](evidence/scale-baseline-timeout-20.csv)
is a separately recorded baseline pass with a 20 s cap, kept because it shows the same cells
failing before the cap was raised.

| skills | command | baseline s | final s | final stdout B | final lines | final peak RSS KiB |
|---|---|---|---|---|---|---|
| 10 | status text / json | 2.89 / 2.72 | 1.69 / 2.03 | 1,970 / 14,621 | 25 / 481 | 29,688 |
| 10 | diagnose text / json | 2.35 / 2.19 | 1.62 / 1.08 | 1,208 / 44,479 | 9 / 1,085 | 29,688 |
| 10 | list text / json | 1.60 / 2.67 | 1.35 / 2.18 | 785 / 3,535 | 13 / 184 | 29,736 |
| 100 | status text / json | 6.67 / 7.71 | 2.31 / 2.81 | 1,956 / 113,171 | 29 / 4,288 | 29,676 |
| 100 | diagnose text / json | 7.42 / 7.02 | 2.13 / 2.02 | 1,209 / 267,634 | 9 / 5,540 | 30,064 |
| 100 | list text / json | 9.45 / 4.72 | 1.57 / 1.78 | 716 / 35,323 | 14 / 1,822 | 29,736 |
| 1000 | status text / json | timeout / timeout | 5.29 / 5.11 | 1,963 / 1,098,671 | 29 / 42,358 | 38,128 |
| 1000 | diagnose text / json | 30.72 / 31.87 | 4.84 / 4.56 | 1,212 / 2,499,184 | 9 / 50,090 | 41,840 |
| 1000 | list text / json | 45.52 / 41.97 | 2.56 / 1.79 | 719 / 353,203 | 14 / 18,202 | 33,960 |
| 5000 | status text / json | timeout / timeout | 16.15 / 17.86 | 1,968 / 5,478,671 | 29 / 211,558 | 75,140 |
| 5000 | diagnose text / json | timeout / timeout | 14.05 / 13.68 | 1,214 / 12,417,184 | 9 / 248,090 | 107,832 |
| 5000 | list text / json | timeout / timeout | 6.40 / 6.92 | 720 / 1,766,003 | 14 / 91,002 | 66,624 |

`timeout` = killed at the 60 s cap with no output. Read single cells as ±2x on this host
(scale.md finding 7). Two effects overlap here: less repeated work (one tree hash per copy,
one listing per harness path, indexed validity, inventory-only `list`) and much smaller
default text output (findings preview only; `--verbose` restores the full tables).

**Filtered lookup** ([raw](evidence/filtered-search.txt)), 5000-skill fixture:
`list --search scale-004321` → 1.85 s, exit 0, 1 row, 460 B stdout, 56,080 KiB RSS;
`--search nomatch-xyz` → 1.61 s, `[]`. The baseline has no filter: `--search` exits 2
(`unrecognized arguments`, 0.71 s), and its only equivalent is the full `list --json`, which
timed out at 60 s and took 41–46 s at 1000 skills.

**Corrupt `skillporter.yaml`** (`{`): baseline exits 1 with a ~2 KB `JSONDecodeError`
traceback and empty stdout; this branch exits 2 with
`error: corrupted skillporter.yaml at <path>: ... (repair skillporter.yaml or delete it to start over)`.

## Compatibility and scope of the change

- **JSON contracts unchanged.** `status`, `diagnose`, `list`, `doctor` (text + `--json`,
  project and user scope) produce the same key/type shape on `bdfb9e6` and on this branch; only
  values and documented labels changed ([raw](evidence/json-shape.txt)).
- **Config and fixture sources untouched.** No diff against `bdfb9e6` in `pyproject.toml`,
  `package.json`, `Dockerfile`, `install.sh`; test fixtures and `skillporter.yaml` handling are
  the same files apart from `manifest.py` error wrapping.
- **Nested and shared discovery** (probe): `$HERMES_HOME/skills/<category>/<name>/SKILL.md` is
  found at user scope with identical names in full and inventory scans; a duplicate name in two
  categories is reported as a duplicate instead of twice; `.agents/skills/<name>` is one copy
  visible to the 14 harnesses that read that path.
- **Preview/apply parity.** `remove --dry-run` wrote nothing and applied the same two
  destinations, removed the shared copy once for eight harnesses, and preserved the source.
  `doctor --fix --dry-run` and `--fix` produce the same `repair_plan` in the repair-preview tests.
- **No widened repair.** Tests pin that a marker-only harness is never a repair target, that
  `--harness` is the only target when given, and that an unrecorded user-scope drift is refused
  rather than copied across harnesses (`tests/test_doctor_repair_preview.py`).
- **Bundled zipapp** `npm/bin/skillporter.pyz` rebuilds byte-identically from source
  (`sha256 f6ba9629…` at the integration commit).

## Known limits

1. **Unsolicited-harness verdict is still noisy.** Once `.agents/skills` exists for any skill,
   an unrelated Claude-only skill is reported "not visible to: antigravity, codex, gemini-cli,
   goose, junie, openclaw, openhands, roo-code, zed" and `status` flips to NEEDS ATTENTION.
   The observation is true; whether it is damage is a product decision this branch does not make.
2. **No live-discovery claim.** Nothing here shows a harness loading a skill at runtime. The
   receiver evidence is scoped in [receivers.md](receivers.md) (Codex user scope unverified) and
   [field-review.md](field-review.md) (Hermes project scope needs a trust decision made by the
   user; Skillporter reports success before that condition is met).
3. **CLI output shape changed deliberately** (summary first, `--verbose` for tables), so text
   byte counts are not comparable like-for-like with the baseline.
4. **Synthetic fixture only.** Three files per skill; real `references/` trees cost more per
   hash. Windows NTFS, user-scope scale, lockfile-drift at scale and concurrent runs were not
   measured.
5. **Symlink tests** cannot run on this Windows host without the symlink privilege; they are
   exercised by CI on Linux/macOS.

## CI on this branch

`gh workflow run ci.yml --ref product/first-five-minutes` on this branch runs the repository's
own gates. Two runs were needed: the first one
([44501558612](https://github.com/Shanmukh-l33t/skillporter/actions/runs/44501558612)) failed a
single assertion on every platform — it expected `doctor --fix` to delete a dangling link that
the integrated repair engine now refuses to touch — and nothing else in it failed. The
expectation, the `--fix` help text and the troubleshooting guide were aligned, and the later runs
on the merged tree report:

- `test` matrix (ubuntu-22.04 3.9, ubuntu 3.10–3.13, macos 3.12, windows 3.12): **all success**
  — `ruff check .`, `python -m pytest tests/ -q`, standalone zipapp `--version` on each cell.
- `packaging, SAST & dogfood` (wheel/sdist + `twine check`, clean-venv install, standalone
  zipapp + SHA256SUMS, `npx` package, `bandit -ll`): **success**.
- `standalone installer` (ubuntu) and `secret & supply-chain scan`: **success**. The macOS
  installer job depends on GitHub's macOS runner queue on this account; its state is reported as
  recorded on the run page, and a job that stays queued is never counted as a pass here.

## Reproduce

```bash
# scale (same machine, filesystem, sizes and cap as docs/verification/scale.md)
TMPDIR=/tmp python3 scripts/scale_benchmark.py --sizes 10 100 1000 5000 --repeats 3 --timeout 60

# filtered lookup: build the same fixture, then
python -B -S -m skillporter list --search scale-004321 . --no-color --json

# workflows (disposable home, nothing installed)
HOME=$(mktemp -d) HERMES_HOME=$(mktemp -d) python -m skillporter status
```

Probe transcripts in `evidence/` were produced by small scripts run from the checkout with
`HOME`/`USERPROFILE`/`HERMES_HOME` pointed at a scratch directory; they are listed here by
output rather than source because each one re-derives from the commands above.