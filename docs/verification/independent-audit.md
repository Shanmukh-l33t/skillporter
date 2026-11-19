# Independent audit — Skillporter 3.2.0 (clone `996b25f`)

> Copied from the auditor's clone of `996b25f`. D1, D3 and D4 below were fixed afterwards; see
> `README.md` for the resolution table. The verdict sentence is the auditor's, not the author's.

**Verdict (at 996b25f):** The core lifecycle is sound and the headline complaints are genuinely fixed — but the tool is **not release-clean**:
a workspace whose only problem is a duplicate copy is reported unhealthy with zero findings, `diagnose` calls the same
workspace clean, a corrupted `skillporter.yaml` is silently ignored instead of failing with exit 2, and two verification
documents still quote output the CLI no longer prints. Fix those four before publishing a "verified" claim.

Host: Windows 11, Python 3.14.9, venv `.venv`, CLI run as `.venv/Scripts/python -m skillporter`.
Every child process had its own disposable `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA`/`HERMES_HOME`/`XDG_*`/`TMP*`;
no symlinks created, no model calls, no network. Fixtures and probe driver:
`C:/Users/ImMandatory/AppData/Local/hermes/cache/scratch/audit3/` (`probe.py`, `c1.py`…`c8.py`).

## Matrix

| Claim | Label | Command | Observed | Scope |
|---|---|---|---|---|
| Unversioned `.claude/skills/hello`, no manifest: `status` exits 0 and does not mention codex | Fixture verified | `status` | exit 0, `[HEALTHY]`, "1 total (0 synced, 1 unmanaged)" | Windows, isolated HOME |
| Same fixture: `diagnose` exits 0, no codex | Fixture verified | `diagnose` | exit 0, "1 skill(s) found · no findings" | " |
| Explicit harness still judged | Fixture verified | `diagnose --harness codex` | exit 1, `skill 'hello' is missing from expected paths for: codex` | " |
| Unversioned skill shows `untracked`, never `1.0.0` | Fixture verified | `status --verbose` | row `hello  untracked  UNMANAGED  no` | " |
| Verdict ↔ counts agree (clean) | Fixture verified | `status` / `status --json` | `[HEALTHY]`, `healthy=true`, 0 findings | " |
| Verdict ↔ counts agree (edited managed copy) | Fixture verified | `status` / `--json` | `[NEEDS ATTENTION]`, 1 finding in JSON | " |
| Verdict ↔ counts agree (duplicate copy) | **Broken** | `status` / `diagnose` | `[NEEDS ATTENTION]`, exit 1, **0 findings**; `diagnose` exit 0 "no findings" | " |
| `doctor --fix --dry-run` writes nothing | Fixture verified, with a caveat | `doctor --fix --dry-run` | all skill/manifest files byte-identical before/after; `.skillporter/lock` rewritten, `.skillporter/tmp` removed | " |
| `doctor --fix` does what the preview said, and is idempotent | Fixture verified | `doctor --fix` ×2 | preview `.claude\skills\hello` sha `5c012869dead` = the one file changed; 2nd run "No changes planned.", 0 files changed | " |
| `remove --dry-run` lists one line per physical destination | Fixture verified | `remove hello --dry-run` | 12 rows = 12 distinct paths; shared `.agents/skills` listed once for 8 readers | " |
| `remove --harness X -y` removes only the previewed destination | Fixture verified | `remove hello --harness claude-code -y` | "Removed 'hello' from 1 destination(s) (source preserved)"; 12 other copies + `src/hello` intact | " |
| Unrelated file keeps its bytes through preview and apply | Fixture verified | `NOTES.txt` around both | `unrelated bytes\n` unchanged | " |
| CI gate: add → init → sync → lock → `lock --check` | Integration verified | `lock --check` | exit 0, "skillporter.lock is up to date and verified (0 drift)." | " |
| `doctor` does not contradict `lock --check` | Fixture verified | `doctor` | exit 0, `HEALTHY`, "Content drift: 0 skill(s)" | " |
| Exit 0 clean | Fixture verified | `status`, `diagnose` | 0, 0 | " |
| Exit 1 explicit missing harness | Fixture verified | `diagnose --harness codex` | 1 | " |
| Exit 2 corrupted `skillporter.yaml`, no traceback | **Broken** | `status`/`lock`/`sync` on invalid YAML | exit 0/0/0, no message, `lock`+`sync` **wrote files** | " |
| Exit 2 unknown harness | Fixture verified | `diagnose --harness nonsense-harness` | 2, `error: unknown harness 'nonsense-harness'` | " |
| `status --json` / `diagnose --json` / `list --json` valid and uncapped | Fixture verified | 30-skill fixture | valid JSON; 30 rows / 30 / 30; human `list` capped at 10 rows | " |
| 300 skills under 5 s | Integration verified, one host | `status`/`diagnose`/`list`/`list --search` ×3 | 3.42 / 1.86 / 1.24 / 0.88 s median (status cold run 10.86 s) | " |
| Docs distinguish adapter evidence from a live check | Code reviewed + fixture | `add`, `diagnose`, `matrix` | `add` prints "Not verified: whether each harness discovers or loads the skill"; `diagnose` prints "Filesystem checks only; runtime discovery was not checked." | " |
| Skill **activation** in a harness | Not verified | — | no model call in scope | out of scope |
| macOS / Linux behaviour | Not verified | — | Windows host only | — |

## Defects

### D1 (high) — duplicate-only workspace: unhealthy verdict, zero findings, and `diagnose` disagrees

```
mkdir -p p/.claude/skills p/src && (write p/src/hello/SKILL.md, p/.claude/skills/hello/SKILL.md)
python -m skillporter add p/src/hello --harness all --offline      # exit 0
python -m skillporter lock                                          # exit 0
python -m skillporter status        # exit 1, [NEEDS ATTENTION], state DUPLICATE, NO "Findings:" section
python -m skillporter diagnose      # exit 0, "1 skill(s) found · no findings"
python -m skillporter status --json # healthy=false, attention_skills=["hello"], findings=[]
```

`healthy` is computed from skill status (`skillporter/environment.py:379`) but the findings list is assembled only from
`diag.findings` + `lock_drift` (`:356`), and `diagnose` never turns `duplicates` into a finding. So the header says a
problem exists and both the human and JSON finding lists say none does — the exact "verdict vs counts" contradiction.

### D2 (low) — `status` reports two different finding counts

```
python -m skillporter status        # "Findings:           2"   (lockfile drift + content drift)
python -m skillporter status --json # "findings": [ <content drift only> ]
```
Text counts `lock_drift + findings` (`environment_cmd.py:103`), JSON exposes `lock_drift` as a separate key. Defensible
shape, undocumented, and a CI script counting `findings` sees 1 where the terminal says 2.

### D3 (low) — `doctor --fix --dry-run` is not strictly zero-write

```
python -m skillporter doctor --fix --dry-run
```
Before/after over the whole project: every skill copy, `skillporter.yaml`, `skillporter.lock`, `state.json` identical;
`.skillporter/lock` content changed and a leftover `.skillporter/tmp` directory disappeared. The lock file accumulates
stale PIDs (`23144 / 21908 / 19760` in one fixture). Read-only `status`/`diagnose` do **not** touch it, so this is the
write-path lock acquisition running under `--dry-run`. No user data affected, but "nothing written" is literally false
and the PID list grows per run.

### D4 (medium) — corrupted manifest is silently ignored, never exit 2

```
printf 'skills:\n\t- name: hello\n   broken: [unclosed\n:::\n' > p/skillporter.yaml
python -m skillporter status   # exit 0
python -m skillporter lock     # exit 0 — wrote skillporter.lock
python -m skillporter sync     # exit 0 — wrote lock and installed a skill into codex
```
`manifest.load_manifest` swallows `ValueError/TypeError` and returns `None` (`skillporter/manifest.py:515-521`), so a
typo'd or truncated config is indistinguishable from "not initialized". A user who mistypes `skillporter.yaml` gets a
silent downgrade to disk discovery, and `sync` then acts on it. The exit-code contract ("2 = usage/operational error")
does not hold for the most likely config error there is.

### D5 (medium, docs) — `Installation verified.` survives in the verification docs but not in the CLI

3.2.0 prints:
```
Verified 1 destination(s) on disk: byte-identical to the source (sha256), source left intact.
Not verified: whether each harness discovers or loads the skill (no runtime check).
```
`tests/test_p0_mandatory_regressions.py:305,322` and `tests/test_v2_ecosystem.py:456` assert the old string is gone.
Yet `docs/verification/receivers.md:37` and `docs/verification/workflows.md:67` still quote `Installation verified.` as
what `add` prints. Those two evidence files describe a build this commit cannot produce; a reader takes them as current.

### D6 (medium, docs) — two verification documents disagree about Claude Code

`docs/harnesses/README.md:14,60` — Claude Code `RUNTIME_VERIFIED`, evidence "the init event lists the skill".
`docs/verification/receivers.md` — Claude Code listing: "Not verified — no offline listing surface exists".
The stricter document is the evidence; the looser one is the claim. One of them is wrong, and both are linked from
`docs/verification/README.md`.

### D7 (low, docs) — stale audit ledgers contradict the shipped registry

`docs/audits/INDEPENDENT_REVIEW.md:33` and `docs/audits/HARNESS_COMPATIBILITY_AUDIT.md:29` say `RUNTIME_VERIFIED` is
1 harness (Hermes), with Claude Code/Codex/Cursor at `INTEGRATION_TESTED`. The registry, `skillporter matrix`, README and
`docs/harnesses/README.md` all say 8. Direction is conservative (the audits under-claim), but three documents about the
same label cannot all be current.

### D8 (medium, docs/UX) — `status` still says HEALTHY for an untrusted Hermes project skill

```
p/.hermes/skills/hidden/SKILL.md only
python -m skillporter status    # exit 0, [HEALTHY] — no trust caveat anywhere
python -m skillporter diagnose  # exit 0, prints "Hermes project skill discovery requires project trust; trust was not checked."
```
`docs/verification/README.md` claims the prerequisite was "documented after" the field review. It is documented in
`diagnose`, README prose and `docs/HARNESS_COMPATIBILITY.md` — not in `status`, which is the command the verification
index itself measures. Someone who runs `status` and sees HEALTHY still concludes the skill is reachable.

## Docs vs code: what I checked and what held

- README:177 "An adapter is never marked `RUNTIME_VERIFIED` unless it has been tested against a live harness runtime" —
  backed insofar as the registry only carries those 8 values, and `add`/`diagnose` print an explicit
  "Not verified … (no runtime check)" line. **Held.**
- README harness table cell `Hermes Agent | .hermes/skills/ | RUNTIME_VERIFIED` — overstated at cell level: the evidence
  is user scope only (`docs/harnesses/README.md:25`). The paragraph at README:200 correctly qualifies it
  ("filesystem-verified until that trust decision exists"), so the page is defensible only if a reader reaches that line.
  **Overstated in the table, mitigated in prose.**
- `docs/verification/README.md` timing table (`status` 0.76 s at 35 skills) — **not reproduced**: 1.5–2.1 s at 1 skill,
  7.16 s for `status --verbose`, 3.42 s median at 300. Same order, different absolute numbers; treat those timings as
  host-specific, not characteristic.
- `docs/verification/README.md` "Skillporter said `HEALTHY` without it" (Hermes trust) — still true for `status`, see D8.

## What I could not verify

- **Activation** by any harness (needs a model run) — every row above stops at bytes-on-disk or the CLI's own verdict.
- **Runtime discovery** for any harness (`list`/RPC of Codex, Claude Code, Hermes) — out of the 25-minute, no-network scope.
- **Broken-symlink handling** — no symlink privilege on this host; that case is `not verified`, not broken.
- **macOS/Linux** — Windows-only run.
- **`install.sh`, npm tarball, PyPI wheel, release asset digests** — clone installed editably, as instructed; the published
  artifacts can differ from `996b25f`.
- **Concurrency** of `.skillporter/lock` (the stale-PID accumulation in D3 hints at it, but I did not race two processes).

## Replay

```
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
# each check: .venv/Scripts/python C:/Users/ImMandatory/AppData/Local/hermes/cache/scratch/audit3/cN.py
```
`probe.py` holds the isolated-env runner (`run()`, `tree()`, `skill()`); `c1`…`c8` are one script per check, in order.