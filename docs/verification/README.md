# Verification evidence

Every file here was produced by running the CLI, the receiver harness, or the test suite. Labels follow
`product-claim-audit`: **Runtime verified** (the consuming system returned the expected result),
**Integration verified** (two real components, disposable environment), **Fixture verified** (controlled
input, real code), **Code reviewed**, **Not verified**, **Broken**.

## The complaint this round started from

For the follow-up candidate, see [Release-readiness verification](release-readiness.md).

One unversioned skill in `.claude/skills/hello`, no manifest, no state, isolated HOME, Windows 11,
median of three runs (`scripts/`-style probe kept beside this repo's evidence):

| | baseline `bdfb9e6` | `product/final` |
|---|---|---|
| `status` | exit 1, 17 lines, 6.99 s, `[NEEDS ATTENTION]` | exit 0, 12 lines, 0.78 s, `[HEALTHY]` |
| `diagnose` | exit 1, 10 lines, 3.14 s, "not visible to: codex" | exit 0, 4 lines, 0.45 s |
| 35 skills, `status` | exit 1, 76 lines, 5.59 s | exit 0, 12 lines, 1.44 s |
| 35 skills, `list --search …` | exit 2 (flag absent), 5.17 s | exit 0, 4 lines, 0.65 s |

The false finding is gone because an unrequested harness is no longer judged; `diagnose --harness codex`
still reports `missing from expected paths for: codex` and exits 1.

## What was verified against something other than our own code

| Claim | Label | Evidence |
|---|---|---|
| Hermes lists a user-scope install and stops listing it after removal | Runtime verified | `field-review.md` (real `find_all_skills` in a disposable `HERMES_HOME`) |
| Hermes project scope requires workspace trust; 3.2.0 said `HEALTHY` without it | Broken at baseline. Now `status`, `diagnose` and the docs state the prerequisite, and the verdict is qualified; the trust decision itself is still the user's | `field-review.md` |
| Codex 0.170.0 lists project-scope installs (`skills/list`, scope `repo`); OpenCode 1.19.6 lists both scopes | Runtime verified | `receivers.md` |
| Codex user scope at `~/.agents/skills` | Not verified — isolation limit, not a failure | `receivers.md` |
| Claude Code listing | Not verified — no offline listing surface exists | `receivers.md` |
| Published PyPI wheel, npm tarball, release asset digests, and installed CLI | Integration verified | `workflows.md` (hashes recomputed from the registries) |
| Local add → status → lock → export/import → rollback → doctor repair → remove | Integration verified | `workflows.md` + `evidence/` |
| `remove --dry-run` and apply agree; shared `.agents` copy reported once with its readers | Integration verified | `removal.md` |
| `doctor --fix --dry-run` prints the plan the apply executes | Fixture verified | `integrity.md`, `tests/test_doctor_repair_preview.py` |
| Scale at 10/100/1,000/5,000 skills | Integration verified, one host | `scale.md` |
| Skill **activation** (the agent actually uses the skill) | Not verified anywhere — would need a model run per harness | — |
| macOS | Not verified — no Mac on this host; Windows + WSL Ubuntu only | — |
| Timing | Timings in this file are one host's numbers, not characteristics: an independent run on the same machine measured 1.5–2.1 s at one skill and 3.4 s at 300. Treat the before/after ratio and the line counts as the result; treat absolute seconds as machine-specific. | — |

## Files

- `product-decisions.md` — what the first five minutes must answer, and the checks that can falsify each choice.
- `field-review.md` — independent Hermes receiver audit with a replay recipe and acceptance checks.
- `receivers.md` — Codex and OpenCode receiver listings, including what stayed unverified.
- `workflows.md` — feature-by-feature verification of the published 3.2.0 artifact, plus `evidence/`.
- `integrity.md` — the workspace-integrity fixes and their measurements.
- `removal.md` — preview/apply parity and shared-path ownership.
- `scale.md` — benchmark script, baseline table, and the after-the-fix table.
- `probe.py`, `probe_hermes.py` — the disposable-environment drivers used for the journeys above.

## Known limits

- Windows symlink tests need Developer Mode; the one symlink case is deselected here and covered on ext4.
- Five suite tests fail on this host for reasons unrelated to this work (network git clone, registry access,
  symlink privilege); `workflows.md` names them so they are not mistaken for regressions.
- 5,000 skills runs in ~19 s with a 5.5 MB JSON payload; usable, not instant.
## Defects found in this pass that are still open

Found by the published-artifact verification (`workflows.md`), re-checked on `product/final`:

| # | Defect | Status |
|---|---|---|
| F1 | `add` → `init` → `sync` → `lock` left `lock --check` failing "source mismatch" while `doctor` said HEALTHY | **Fixed** in `996b25f`: `init` keeps the installed source; regression test `test_init_keeps_the_installed_source_so_the_lock_check_passes` |
| F2 | `profile use` writes 8 directories / 15 harness entries but prints 5, and the profile header disagrees with its skill list | open (cosmetic in the profile report, not in what is written) |
| F3 | `pack` is not byte-reproducible: gzip header mtime makes `archive_sha256` differ for identical content | open |
| F4 | after `adopt` then `move`, `outdated` reports ERROR because the tracked source is the removed location | open |
| F5 | `remove --dry-run` printed one line per harness, not per destination | **Fixed**: one line per destination with every reader named |
| F6 | `init` records `claude-code, codex, cursor` even when the install targeted other harnesses | open |
| F7 | `consolidate --rollback` snapshot fails on 260-character paths (WinError 3) | open |
| F8 | `docs/TESTING.md` claims 198 tests / 16 modules; the checkout has 567 / 36 | open (documentation only) |

F2–F8 are recorded rather than fixed: none of them blocks the first-five-minutes workflow, and each needs its own
fixture. They are the first tickets for the next round, not a claim that this pass covered the whole product.

## Independent audit (separate session, clone of `996b25f`)

An Astra auditor that wrote none of this code reproduced the checks above and found eight issues. Its report lives in
that clone (`docs/verification/independent-audit.md`); this is what changed in response:

| # | Finding | Resolution |
|---|---|---|
| D1 | A duplicate-only workspace showed `[NEEDS ATTENTION]`, exit 1, and **zero findings**; `diagnose` said clean | Fixed: duplicates are a finding naming each path and the reason (`6a5e919`) |
| D2 | `status` text counted lock drift + findings while `--json` kept them apart | Fixed: separate `Lock drift:` and `Findings:` counts, matching the JSON keys |
| D3 | `doctor --fix --dry-run` rewrote `.skillporter/lock` and cleared `.skillporter/tmp` via crash recovery | Fixed: a preview no longer runs recovery; verified byte-identical tree before/after |
| D4 | A corrupted `skillporter.yaml` was silently ignored (exit 0) and `sync` then wrote files | Fixed: unrecognisable lines are a config error, exit 2, nothing written |
| D5 | Two evidence files quoted `Installation verified.`, which this build no longer prints | Annotated as captured from published 3.2.0, with the current wording |
| D6 | `docs/harnesses/README.md` claimed Claude Code runtime evidence that `receivers.md` could not reproduce | Annotated: a tier records the original observation, not a re-check |
| D7 | Older audit ledgers say 1 runtime-verified harness, the registry says 8 | Left as historical records; the registry and matrix are the current source |
| D8 | `status` printed `[HEALTHY]` for a Hermes project skill with no trust caveat | Fixed: `status` now prints the trust prerequisite beside the verdict |

The auditor's own limits stand: no activation, no live harness discovery, no macOS/Linux, no published-artifact checks in
its pass — those rows are labelled `not verified` there and in this file.
