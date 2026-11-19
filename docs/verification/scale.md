# Skillporter scale verification

Baseline: `bdfb9e684f4f6a9eb9eafd6f94f6bd9446ec4511` (Skillporter 3.2.0), 2026-11-19 UTC.
WSL2 Ubuntu 24.04.1 LTS, kernel `6.6.87.2-microsoft-standard-WSL2`, Python 3.12.3,
Intel Core i7-8850H (12 logical CPUs), 31,971 MiB visible RAM. Both the CLI source copy
and fixtures ran on Ubuntu's native ext4 volume, not `/mnt/c`.

## Reproduce on the integrated checkout

From the integrated checkout root in Ubuntu or WSL Ubuntu (Python 3.9+, GNU `time`, GNU `timeout`):

```sh
git rev-parse HEAD
TMPDIR=/tmp python3 scripts/scale_benchmark.py --sizes 10 100 1000 5000 --repeats 3 --timeout 60 > scale.csv
# one bounded command at one size, when a full 5000 pass would run past the cap:
TMPDIR=/tmp python3 scripts/scale_benchmark.py --sizes 5000 --commands diagnose --timeout 240 > diagnose-5k.csv
```

Use the same machine, filesystem, size/order, and limits for comparison. `--sizes` also
accepts larger counts. Each sample is a fresh `python -B -S -m skillporter <command> . --no-color`
process; JSON samples add `--json`. The runner copies the checkout package into scratch and
uses a fresh temporary project, home, and a `PATH` with no harness executables. It replaces
the child environment instead of inheriting local harness settings or telemetry opt-ins.
No Skillporter install, remote fetch, or real home write is needed.

- **Mixed fixture:** `scale-000000` onward in `.agents/skills` (shared by Codex, Cursor, and others).
  Even IDs are managed via seeded `state.json` with real shared-copy hashes; odd IDs are unmanaged.
  Every fifth ID (starting at 0) also has a `.claude/skills` copy; every tenth ID has an edit only
  in that copy's `references/deep/guide.md`, so half the secondary copies drift. Every copy has
  `SKILL.md` and two nested files (544 payload bytes combined, plus the edit where applicable).
  IDs ending in 9 lack the required description in `SKILL.md`. One dangling relative symlink sits
  in the shared path if supported (it is not counted as a named skill). `skillporter.yaml` selects
  Codex and Cursor. No lockfile is seeded.
- **Invalid project manifest:** after the smallest default fixture's mixed runs, replace its
  `skillporter.yaml` with `{` plus a newline and run each JSON command once. Kept separate so a
  parse failure doesn't hide actual discovery costs.
- **Measurement:** sequential `status`, `diagnose`, `list`, text then JSON, once per size by default
  (`--repeats 3` in the command above, once per cell below).
  Wall time includes process startup and writes to an ext4 stdout file, not fixture creation,
  measurement post-processing, or terminal rendering. GNU `time %M` reports process peak RSS
  in KiB. Stdout counts are raw bytes and LF characters; stderr is separate. Filesystem caches
  are not flushed. Each command gets 60 s by default, then TERM, then KILL after 5 s if needed. `timeout`
  rows keep elapsed time and any partial output counts; RSS is blank, not zero. The first
  completed JSON sample for each command and size checks fixture behavior against real CLI output.

## Baseline results

One sample per cell, seconds wall clock, peak RSS from GNU `time`:

| skills | command | format | result | exit | seconds | stdout B | stdout lines | peak RSS KiB |
|---|---|---|---|---|---|---|---|---|
| 10 | status | text | exit | 1 | 2.889 | 4,178 | 43 | 29,516 |
| 10 | status | json | exit | 1 | 2.722 | 14,271 | 481 | 29,636 |
| 10 | diagnose | text | exit | 1 | 2.354 | 5,923 | 34 | 29,640 |
| 10 | diagnose | json | exit | 1 | 2.188 | 42,479 | 1,085 | 29,724 |
| 10 | list | text | exit | 0 | 1.596 | 919 | 12 | 29,656 |
| 10 | list | json | exit | 0 | 2.669 | 3,535 | 184 | 29,540 |
| 100 | status | text | exit | 1 | 6.666 | 8,345 | 86 | 29,508 |
| 100 | status | json | exit | 1 | 7.714 | 113,271 | 4,288 | 29,672 |
| 100 | diagnose | text | exit | 1 | 7.417 | 33,283 | 142 | 29,644 |
| 100 | diagnose | json | exit | 1 | 7.016 | 262,934 | 5,540 | 29,724 |
| 100 | list | text | exit | 0 | 9.450 | 2,077 | 33 | 29,528 |
| 100 | list | json | exit | 0 | 4.718 | 35,323 | 1,822 | 29,528 |
| 1000 | status | text | timeout | 124 | 60.007 | 0 | 0 | (killed) |
| 1000 | status | json | timeout | 124 | 60.005 | 0 | 0 | (killed) |
| 1000 | diagnose | text | exit | 1 | 30.717 | 306,883 | 1,222 | 32,444 |
| 1000 | diagnose | json | exit | 1 | 31.873 | 2,467,484 | 50,090 | 39,864 |
| 1000 | list | text | exit | 0 | 45.523 | 2,078 | 33 | 33,112 |
| 1000 | list | json | exit | 0 | 41.967 | 353,203 | 18,202 | 34,388 |

### 5000 skills

At the 60 s cap, all six `status`/`diagnose`/`list` cells were `timeout`, exit 124, 60.0 s,
0 stdout bytes, 0 lines, no RSS (killed mid-run). A second pass with `--commands diagnose
--timeout 240` completed both formats:

| skills | command | format | result | exit | seconds | stdout B | stdout lines | peak RSS KiB |
|---|---|---|---|---|---|---|---|---|
| 5000 | diagnose | text | exit | 1 | 144.326 | 1,522,883 | 6,022 | 58,548 |
| 5000 | diagnose | json | exit | 1 | 94.132 | 12,265,484 | 248,090 | 94,236 |

`status` and `list` were not re-run above the cap, so their 5000-skill cost is only bounded:
greater than 60 s each. The invalid-manifest probe at 5000 skills fails in 1.317 s, the same order
as at 10 skills (0.9-2.9 s).
Nothing was printed by any timed-out cell because all three commands build their whole payload
before writing, so a killed run leaves an operator with no output at all rather than partial output.

### Invalid project manifest

`skillporter.yaml` replaced with `{`: every command dies with an uncaught `JSONDecodeError`,
exit 1, empty stdout, ~2 KB traceback on stderr.

| skills | command | format | result | exit | seconds | stdout B | stderr B |
|---|---|---|---|---|---|---|---|
| 10 | status | json | exit | 1 | 2.241 | 0 | 1,785 |
| 10 | diagnose | json | exit | 1 | 2.875 | 0 | 2,038 |
| 10 | list | json | exit | 1 | 2.483 | 0 | 2,005 |

At 1000 skills the same three commands fail in 1.6-1.9 s and `diagnose` at 5000 fails in 1.3 s, so
the failure is cheap and independent of skill count - the parse error lands before discovery.

Exit 1 on the mixed fixture at every size is the fixture, not a harness fault: it contains seeded
drift, ten-percent invalid frontmatter, and a dangling link, so `status` and `diagnose` correctly
report `NEEDS ATTENTION`. `list` exits 0 because its surface is inventory, not health.

## Findings

1. **Every command grows linearly in skill count, with no absolute cost anyone would call fast.**
   Startup alone is 0.9-2.9 s at 10 skills (interpreter plus the 166 stdlib and package modules
   `skillporter.cli` pulls in, no third-party imports under `-S`). `diagnose` goes 2.2 s -> 7.0 s ->
   31.9 s -> 94-144 s for 10 -> 100 -> 1000 -> 5000 skills (~31 ms per skill at 1000; 5x the skills
   for 3-4.5x the time at 5000, i.e. no superlinear blow-up, just a large constant). `list` goes
   2.7 s -> 4.7 s -> 42.0 s. `status` goes 2.7 s -> 7.7 s -> over 60 s. The shape is fine; the
   constant is the problem.
2. **`status` is the slowest and does strictly more work than `diagnose`.** It runs `diagnose`,
   then re-walks every skill's first copy through `compute_tree_hash` again
   (`skillporter/environment.py:268`) and re-validates each skill against every collected issue
   (`skillporter/diagnose.py:131`, `is_skill_valid` loops all issues per skill). A 300-skill
   cProfile probe (under load, so absolute times are inflated; shares are the signal) spent
   41.3 s of 41.9 s inside `capture_environment`, of which `compute_tree_hash` took 20.7 s across
   **1,560 calls for 360 on-disk skill directories** (~4.3 hashes per directory),
   `detect_harnesses` 10.1 s (almost all of it `shutil.which` over 18 detection binaries), and
   `is_skill_valid` 8.1 s (18%). The 1,560:360 ratio is the direct cost of recomputing hashes that
   discovery already computed and discarded.
3. **Output volume is a second scaling axis with the same 50-lines-per-skill slope.** `diagnose
   --json` is 2.47 MB / 50,090 lines at 1000 skills and 12.27 MB / 248,090 lines at 5000 - about
   2.4-2.5 KB and 50 lines per skill at both sizes - versus 307 KB / 1.5 MB of text. `list --json`
   is 353 KB at 1000. Any consumer that buffers or re-renders per skill hurts more than the CLI does.
4. **Peak memory tracks the output payload, not the skill count.** RSS is 29.5 MiB at 10 skills,
   39.9 MiB for `diagnose --json` at 1000, 58.5 MiB for text at 5000, and 94.2 MiB for JSON at 5000
   (~14 KiB per skill above 1000). Text at 5000 holds 35 MiB less than JSON because the JSON path
   serializes the whole document to one string first. Trimming redundant hashing buys wall time;
   trimming the payload is what buys memory.
5. **Timeout rows produce zero output.** Because each command prints only after building its full
   payload, capping a run at 5000 skills yields an empty stdout. Partial results or streaming
   output would be a behaviour change, not a measurement artifact.
6. **A corrupt `skillporter.yaml` takes down read-only commands.** `status`, `diagnose`, and `list`
   all die with a raw traceback (`json.decoder.JSONDecodeError`) and empty stdout instead of a
   one-line error, even though the malformed file only carries project config.
7. **Repeat variance on this host is large.** The same cell moved by up to ~2x between passes
   (`list` text at 1000 skills: 25.2 s in one pass, 45.5 s in another that competed with a profiler
   probe; `diagnose` text at 100: 5.1 s vs 7.4 s; the 10-skill cells re-ran in 0.87-2.05 s on an
   idle host versus 1.6-2.9 s under load, with byte-identical stdout). Read single cells as +/-2x
   on this machine and use `--repeats 3` on an idle one. This Windows host runs other agent work;
   the numbers are a relative baseline, not a hardware benchmark.
8. **The fixture behaved as designed, so the timings mean what they claim.** Every completed JSON
   sample passed the built-in assertions: discovered-name set equals the requested count, managed
   set equals the even IDs, drifted set equals every tenth ID, invalid count equals one in ten,
   every skill is reachable from the shared `.agents/skills` path by at least the two manifest
   harnesses, the dangling link appears in findings while a supported symlink exists, and the
   invalid-manifest runs produce no payload.

## Limits

Discovery and hashing costs are a function of directory entries per skill, so the three-files-per-skill
fixture understates real repositories: a skill with 20 files or a large `references/` tree costs more
`stat`/`read` per tree hash, and the redundant-hash finding in item 2 gets proportionally worse.
Not covered: lockfile drift at scale (no lockfile seeded), user-scope runs, concurrent invocations,
Windows NTFS runs, `--verbose` rendering of 5000-row tables, and network/registry paths. No
application code was changed for this report; findings 2, 5, and 6 are observations for a follow-up,
not fixes.

## After the fixes (product/final, same host and script)

Same fixture, same machine, one sample per cell (`--repeats 1 --timeout 240`), WSL Ubuntu, Python 3.12.3,
CLI run from a native ext4 copy at `/tmp/sp-rc`:

| skills | command | format | exit | seconds | stdout B | stdout lines |
|---|---|---|---|---|---|---|
| 100 | status | text | 1 | 1.456 | 716 | 14 |
| 100 | diagnose | text | 1 | 0.9 | 889 | 9 |
| 100 | list | text | 0 | 1.0 | 353 | 12 |
| 1,000 | status | text | 1 | 10.662 | 1,938 | 29 |
| 1,000 | status | json | 1 | 10.910 | 1,098,271 | 42,358 |
| 1,000 | diagnose | text | 1 | 9.228 | 1,121 | 10 |
| 1,000 | diagnose | json | 1 | 7.725 | 2,808,978 | 64,326 |
| 1,000 | list | text | 0 | 4.236 | 719 | 14 |
| 5,000 | status | text | 1 | 19.207 | 1,943 | 29 |
| 5,000 | status | json | 1 | 16.860 | 5,478,271 | 211,558 |
| 5,000 | diagnose | text | 1 | 14.112 | 1,123 | 10 |
| 5,000 | diagnose | json | 1 | 13.650 | 13,970,178 | 319,126 |
| 5,000 | list | text | 0 | 8.835 | 720 | 14 |

What changed: `status` at 1,000 skills no longer times out (baseline: >60 s, diagnose alone 31.9 s) and the
whole 5,000-skill collection completes in under 20 s instead of timing out at every command. Human output
stays at 10–29 lines at every size because the cap and the `... and N more` hint are structural, not a
side effect of having few problems.

Still a limit: time to run `status` grows roughly linearly (≈3.4 ms/skill), so 5,000 skills is ~19 s, and
the JSON payload at 5,000 is 5.5 MB (`status`) / 14 MB (`diagnose`). Deferring per-skill validation out of
the summary path is the next step; it was not done here because `status` uses validity in its own verdict.
