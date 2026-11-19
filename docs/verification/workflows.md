# Skillporter feature verification — published 3.2.0

> Captured against **published 3.2.0** from PyPI/npm/GitHub. On the branch under test, `add` reports
> `Verified N destination(s) on disk …` and `Not verified: whether each harness discovers or loads the skill`;
> every quoted `Installation verified.` line below belongs to 3.2.0.

Independent product verification of Skillporter as a user receives it, written from source claims, published package
artifacts, the developer test suite, real CLI runs in disposable homes, and a live Hermes runtime. No application code
was edited. Nothing was published, pushed, or installed into a real home directory.

- Date: 2026-11-19 (IST), Windows 11, Python 3.14.9, Node 26.12.1, git 2.56.1
- Checkout under test: `bdfb9e6` (`product/verification`), which declares version `3.2.0` in `pyproject.toml`
- Verifier: Hermes Agent session; commands below are the ones actually run, verbatim apart from path redaction

## Artifacts verified

| Artifact | Identity | Integrity check |
|---|---|---|
| PyPI wheel | `skillporter-3.2.0-py3-none-any.whl` | sha256 `fa17945f…effeb` recomputed and matched PyPI JSON |
| PyPI sdist | `skillporter-3.2.0.tar.gz` | sha256 `ac4f1300…d2786` (PyPI JSON, not executed) |
| npm tarball | `@shanmukhdheekonda/skillporter@3.2.0` | sha512 `GXVfZ5/5…UOg==` recomputed and matched registry |
| GitHub release | tag `v3.2.0`, `skillporter.pyz` | sha256 `206fa938…c0f`, equal to every platform asset digest |
| Installed CLI | wheel installed with `pip --no-index --no-deps` into a fresh venv | `skillporter 3.2.0`, zero runtime requirements |
| Hermes runtime | installed Hermes Agent 2026.9.24 (`hermes_cli.main`), Python 3.14.9 | version banner; real runtime skill loader used |

Package metadata claims checked: `requires_python >=3.9`; only optional `dev` extras (so "zero runtime dependencies"
holds for the wheel); npm `engines.node >=16`; npm `mcpName` = `io.github.Shanmukh-l33t/skillporter` (the MCP registry
ownership claim in `docs/mcp/README.md`).

## Method and isolation

- **Application untouched.** Only `docs/verification/**` was added to the checkout.
- **Disposable environment.** Each probe created a temp root and exported `HOME`, `USERPROFILE`, `HERMES_HOME`,
  `APPDATA`, `LOCALAPPDATA`, `XDG_*` and `TMP*` into it. The child process environment is rebuilt from an allowlist
  (`PATH`, `SYSTEMROOT`, …), so provider tokens, `SKILLPORTER_*` variables and git credentials are not inherited; git is
  started with `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`.
- **Two probes**, both driven against an already-installed executable and asserting on exit codes, byte content and
  on-disk effects:
  - `probe.py <skillporter> --scratch <dir> [journeys…]` — lifecycle, versions, authoring, instructions, dependencies,
    sources, mcp, remote.
  - `probe_hermes.py <skillporter> <hermes-python> --scratch <dir>` — real Hermes skill loader and MCP client.
- **Hermes configuration.** `probe_hermes.py` writes a brand-new `config.yaml` with one `mcp_servers` entry inside the
  disposable `HERMES_HOME`; the real profile at `%LOCALAPPDATA%\hermes` was never read or written for that test.
- **Ordinary use only.** No offensive workflows, no new attack payloads, no destructive operations outside temp dirs, no
  model calls (no credentials, no cost), no harness runtime other than the one already installed.
- **Fixtures** are the tiny skills the probes generate (`release-notes`, `draft-notes`, `notes`, `git-notes`). Remote
  journeys use one real public repository (`anthropics/skills`) pinned to commit `e4bb5d96…`.

Evidence levels used below:

- **LIVE** — real published 3.2.0 CLI, real filesystem/network, disposable home.
- **RUNTIME** — live third-party runtime (Hermes) reading what Skillporter installed.
- **INTEGRATION** — repository test suite (real subprocesses/temp dirs, no live harness).
- **FIXTURE** — repository test suite with a synthetic harness fixture.
- **UNTESTED** — not exercised here, with the reason.

Raw transcripts: `evidence/` in this directory (`cli.txt`, `remote.txt`, `hermes.txt`, `packages.txt`, `npm.txt`,
`pytest-per-module.txt`, `pytest-failures.txt`, `repro-lock-matrix.txt`, `ruff.txt`). Counts: **136 PASS / 6 FAIL** in
`cli.txt`, **4 PASS / 0 FAIL** in `remote.txt`, **14 PASS / 0 FAIL** in `hermes.txt`. Every FAIL is explained under
Findings.

## Verification matrix

Expectation column quotes the product's own claim (README, `docs/commands`, `docs/lockfiles`, `docs/skill-management`,
`docs/mcp`), abbreviated where the claim is long.

### Sources and installation

| Command | Expected (claim) | Evidence | Result |
|---|---|---|---|
| `add <local dir>` | resolve, validate, static scan, plan, transactional install; dedupe shared `.agents/skills` | LIVE | PASS — dry-run wrote nothing; install put byte-identical `SKILL.md` in `.claude/skills` and `.agents/skills` only, no duplicate `.cursor/skills`; `Installation verified.` |
| `add owner/repo --ref <commit> --skill pdf` | fetch without executing bundled scripts, record commit | LIVE | PASS — `pdf` installed in two dirs from `anthropics/skills` pinned to `e4bb5d96…` |
| `add file://<repo>` | Git URL source, resolved commit pinned | LIVE | PASS — lock recorded the fetched commit, `pin_state: PINNED_COMMIT` |
| `add <bare.git>` | bare repository path accepted as Git source | LIVE | PASS |
| `add <archive.zip>` | local archive source | LIVE | PASS — bytes matched the archived skill |
| `add --dry-run` | plan + scan only | LIVE | PASS — workspace hash-identical afterwards |
| `add --harness`, repeatable; `--isolated` | explicit targets; isolated folder only on request | LIVE | PASS |
| `add --exclude-harness` | subtract from selection | LIVE | PASS |
| `add --on-conflict fail\|skip\|overwrite` | `fail` by default, exit 2 naming the destination | LIVE | PASS (`fail`, `overwrite`); `skip` UNTESTED |
| `add --strategy symlink` | relative symlinks, "breaks where symlinks are not preserved" | LIVE | PARTIAL — refused on Windows with exit 2: `symlink strategy is not reliable on Windows; use --strategy copy` (documented trade-off, honest error) |
| `add --scope user` | installs to the home directory | LIVE (Hermes) | PASS — landed in `$HERMES_HOME/skills` |
| `add --adapt` | also writes adapted rule files | UNTESTED | preview/adapt renderers covered by `preview`/`inspect`; `--adapt` not run |
| `add --max-risk-score`, `--allow-risky`, `--engine` | gate on findings; `--force` never bypasses security | UNTESTED here | covered by INTEGRATION security modules (see developer suite); not exercised live because it needs a deliberately unsafe fixture |
| `install <dir>` | same gates as `add`, `--harness` required | LIVE | PASS |
| `remove` / `uninstall` | shared `.agents` copy kept while another harness owns it; `-y` required without a terminal; manifest+lock cleaned | LIVE | PASS — `remove --harness cursor` printed `preserved-shared`; full remove without `-y` exited 2 and deleted nothing; `uninstall -y` removed both copies and kept the source |
| `remove --dry-run`, `--keep-manifest`, `--purge-source` | preview / retain manifest / delete in-workspace source | LIVE (dry-run) | PASS for dry-run; `--keep-manifest` and `--purge-source` UNTESTED (INTEGRATION-covered) |
| `move --from --to [--isolated]` | relocate without deleting the original source | LIVE | PASS — `.claude/skills` copy gone, `.cursor/skills` copy byte-identical |
| `adopt <skill>`, `adopt --all` | take over unmanaged skills after validation + scan | LIVE | PASS — `Adopted 1 skill(s)` and tracking appeared in `list` |
| `outdated`, `outdated <skill>` | compare managed skills to upstream without writing | LIVE | PASS for a live source (`1.0.0` vs `1.1.0`, `OUTDATED`); **FAIL** for an adopted-then-moved skill (`ERROR`, see F4) |
| `update`, `update --check`, `update --dry-run` | preview diff, gate, snapshot, replace; dry-run writes nothing | LIVE | PASS — `--check` reported `MODIFIED instructions: SKILL.md`, no files changed; `update` rewrote both copies to v1.1.0 |
| `rollback <skill>`, `--dry-run`, `--backup-id`, `all` | restore latest snapshot, transactional | LIVE (dry-run + apply) | PASS — dry-run left v2 in place; rollback restored v1 bytes in both copies |
| `self-skill show\|path\|install` | bundled skill installed into selected harness | LIVE | PASS — `harness status` then listed `hermes … .hermes/skills … skillporter` |

### Manifest, lockfile, dependencies

| Command | Expected | Evidence | Result |
|---|---|---|---|
| `init` | write `skillporter.yaml` from found skills/harnesses; `--force` | LIVE | PASS for the write; **FAIL** on the recorded harness set (F6) |
| `sync` | reconcile, resolve dependencies, write lock; honours locked commits; refuses drift without `--force` | LIVE | PASS for reconciliation and refusal (`refusing to re-lock without --force`, exit 1, local edit preserved); **FAIL** as a source of F1 |
| `sync --dry-run` | no writes | LIVE | PASS |
| `lock` | write deterministic lockfile | LIVE | PASS — per-file sha256 and `PINNED_CONTENT`/`PINNED_COMMIT` as documented |
| `lock --check` | exit 1 on stale lock or on-disk drift, write nothing | LIVE | PASS for genuine drift (edited copy → `lockfile drift … locked 9cec307b != disk 367be67c`); **FAIL** on a freshly initialised workspace (F1) |
| `graph`, `graph --json` | resolved graph + topological order; cycle/conflict exit 1 | LIVE (order), INTEGRATION (cycle/conflict) | PASS — `install_order: [base-utils, mid-layer, top-app]`, all three installed transitively, `sync` dry-run wrote nothing, unsatisfiable constraint failed closed with `version conflict` |
| `status`, `list` | unified state, hashes, harnesses | LIVE | PASS |
| `diagnose` | reachability, drift, broken symlinks, duplicates | LIVE | PASS — `no findings — every skill is reachable and synchronized`; drift reported after an edit |
| `doctor`, `doctor --fix --dry-run`, `--fix` | health check, preview, repair with snapshots | LIVE | PASS — dry-run made no change and exited 1; `--fix` restored locked bytes (`repaired: 7`). Note: after repair `lock --check` still failed on the F1 source mismatch while `doctor` said `HEALTHY` |
| `audit` | origins, lockfile integrity, audit log | LIVE | PASS mechanics; exits 1 (`Verdict: ACTION REQUIRED`) because of F1 |
| `init` → `sync` → `lock --check` (documented CI recipe) | gate passes on a clean workspace | LIVE | **FAIL** — see F1 |

### Portable environments and profiles

| Command | Expected | Evidence | Result |
|---|---|---|---|
| `export <file.skillpack>` | self-contained SHA-256 verified archive, strips secrets | LIVE | PASS — 993 B pack, `Exported … SHA-256: 23b25393…`, recorded exactly the three selected harnesses |
| `diff <pack>` | exit 0 identical / 1 differences | LIVE | PASS — `IDENTICAL` in the source project and in the restored project |
| `import <pack>` | validate hashes, scan, restore offline; default targets = recorded harnesses; `--dry-run` lists writes | LIVE | PASS — dry-run wrote nothing; real import restored byte-identical files to the recorded paths only (no `.cline`/`.github`/`.roo` fan-out); conflict without a policy exited 1 and changed nothing; `--on-conflict overwrite` restored package bytes |
| `import --only-detected`, `--preview`, `--no-manifest`, `--max-risk-score` | options | UNTESTED | not exercised |
| `profile save\|list\|show\|use\|delete` | named environments, switching synchronises them | LIVE | PASS for every subcommand; **FAIL** on harness scoping (F2) |

### Authoring, quality and security

| Command | Expected | Evidence | Result |
|---|---|---|---|
| `new --with-references --with-tests` | spec-compliant scaffold | LIVE | PASS |
| `lint --strict` | metadata, links, scripts, limits, security | LIVE | PASS on the scaffold |
| `test` | deterministic `skill.test.yaml` triggers/assertions | LIVE | PASS |
| `preview --harness --adapt-format` | exact native + adapted output, lost capabilities | LIVE | PASS — `cursor-mdc` adapted body printed |
| `inspect --preview-adapt` | structure, scripts, security posture | LIVE | PASS — `PASSED (risk: 0/100 …)` |
| `validate` | spec validation + risk score; errors exit 1 | LIVE | PASS — valid scaffold exit 0, frontmatter-less skill exit 1 |
| `scan --format text\|json\|sarif` | findings and valid SARIF 2.1.0 | LIVE | PASS — JSON parsed; SARIF `version 2.1.0` parsed |
| `scan --ai-review`, `test --model` | advisory review requires consent + credentials | UNTESTED | requires provider credentials / `--yes-send`; intentionally not run |
| `sandbox run` | non-mutating trace, explicitly experimental | LIVE | PASS — `Filesystem mutated: NO (verified by SHA-256 tree hash)` |
| `policy init\|show\|check` | starter policy, display, enforce | LIVE (clean) | PASS; blocking enforcement UNTESTED (INTEGRATION-covered) |
| `pack --out` | deterministic `.tar.gz` + `provenance.json` | LIVE | PARTIAL — payload deterministic, archive bytes are not (F3) |
| `publish --registry --dry-run` | validate, gate, pack, verify contract; no hosted registry | LIVE (dry-run) | PASS — `Target: dry-run (client contract verified)`, no registry file created; live publish UNTESTED |
| `search`, `info` | seed catalog search / harness metadata | LIVE | PASS — `anthropics/skills` found; `info hermes` printed paths and `RUNTIME_VERIFIED` evidence |
| `explain <code>`, `explain --list` | plain-English finding codes + fix commands | LIVE (`DRIFT`) | PASS |
| `ci-report --format json --output` | Markdown/JSON report, non-zero when unhealthy | LIVE | PASS — exit 1, JSON on stdout, Markdown in the file, `bad-doc` listed as a finding |
| `detect --all --versions`, `matrix`, `harness list\|inspect\|status` | 19-harness matrix, detection, paths | LIVE | PASS — 19 rows, `github-copilot` detected via binary shim, `hermes` configured |
| `demo` | zero-residue self-contained demo | LIVE | PASS — exit 0, project hash unchanged |

### Instructions, context, insights

| Command | Expected | Evidence | Result |
|---|---|---|---|
| `consolidate` (read-only) | discover overlap/conflicts, change nothing | LIVE | PASS — inputs byte-identical afterwards, 100 % overlap reported |
| `consolidate --apply`, `--status`, `--reconcile`, `--rollback` | back up, write canonical, detect hand edits, restore | LIVE | PASS — canonical written with a backup snapshot, second reconcile wrote nothing, rollback restored both guides byte-for-byte |
| `context --harness` | active/ignored files, token estimate | LIVE | PASS — `CLAUDE.md (~45 tokens)`, `! ignored in claude-code: AGENTS.md` |
| `suggest` | offline stack detection + graded recommendations | LIVE | PASS — detected Python project + instruction files, recommended the bundled skill |
| `insights`, `--record-usage` | token overhead, opt-in local usage | LIVE | PASS — usage recorded in `.skillporter/usage.jsonl`, per-skill table shown |

### MCP

| Expectation | Evidence | Result |
|---|---|---|
| JSON-RPC 2.0 over stdio, `2024-11-05`, `ping`, 18 tools | LIVE | PASS — ids 1,3,4,5,6,7 answered, no reply to the notification, 18 tool names match the documented list |
| read-only by default; write tools refused with the documented message | LIVE | PASS — `skillporter_install` returned `isError: true`, exact documented text, no file created |
| `--allow-writes` enables writes | LIVE | PASS — install succeeded, `.claude/skills/mcp-notes/SKILL.md` equals the source |
| Hermes native MCP client can use it | RUNTIME | PASS — `hermes mcp test skillporter` → `Connected`, `Tools discovered: 18` over stdio |
| workspace-boundary, closed schemas, malformed input | INTEGRATION | PASS in `tests/test_mcp_*` (not re-attacked here) |

### Hermes runtime (live harness)

| Expectation | Evidence | Result |
|---|---|---|
| `add --harness hermes --scope user` is loadable | RUNTIME | PASS — `skill_view` resolved `sp-hermes-user` from `$HERMES_HOME/skills` with the exact fixture body |
| `add --harness hermes --scope project` is loadable | RUNTIME | PASS after the harness's own security step: an untrusted project skill is not loaded until `hermes skills trust` (exit 0, `1 project skill(s) will load`), then `skill_view` resolved `.hermes/skills/sp-hermes-project` with the exact body — an intentional Hermes guard, not a Skillporter defect |
| `skills list --source local` surfaces both | RUNTIME | PASS — both skills listed, `enabled` |

### Version checks and exit codes

| Expectation | Evidence | Result |
|---|---|---|
| `--version` matches the published version | LIVE | PASS — `skillporter 3.2.0` from wheel, zipapp and npm wrapper |
| Version parity across Python and npm manifests | INTEGRATION | PASS — `test_version_parity_across_python_root_npm_and_subdir_npm` |
| `0` success, `1` finding, `2` usage/runtime error | LIVE | PASS — 1: lock drift, conflict, unhealthy CI report, version conflict; 2: `remove` without `-y`, import conflict, Windows symlink refusal |

## Developer test suite

Run in an isolated home with a freshly created venv (`pytest 9.2.0`, `ruff 0.17.5`), `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
`GIT_CONFIG_GLOBAL=/dev/null`:

```
pytest --collect-only -q       →  567 tests collected (36 modules)
ruff check skillporter tests   →  All checks passed!
```

The monolithic run aborted at ~25 % in this terminal without a summary, so the suite was executed one module per
process, which also localises failures (`evidence/pytest-per-module.txt`):

```
542 passed, 10 failed, 15 skipped   (36 modules, ~14 min)
```

Triage of the 10 failures (`evidence/pytest-failures.txt`) — none is a Skillporter logic defect on this machine:

- **9 × `OSError [WinError 1314] A required privilege is not held by the client`** — tests calling
  `Path.symlink_to()`; this shell has no `SeCreateSymbolicLinkPrivilege` (no Developer Mode / non-elevated). The
  symlink-related assertions in `test_instructions_hardening`, `test_portability_fixes` and `test_skillporter` cannot
  run here. They would also fail on a stock Windows CI runner without developer mode unless skipped.
- **1 × `FileNotFoundError [WinError 3]` in `tests/test_consolidation_stress.py`** — F7, MAX_PATH (path measured at
  exactly 260 chars); the same test passes with `--basetemp=C:/sptmp/pt`.
- One transient failure in `test_redteam_audit_fixes.py` during the monolithic attempt did not reproduce: the module ran
  `8 passed` standalone and again inside the combined rerun.

The 15 skips are the suite's own platform guards (POSIX `SIGKILL`/`flock`, POSIX permission bits, one symlink test).

Side effect worth knowing: `tests/test_mcp_and_integration_gaps.py` and `tests/test_product_evolution_workflows.py`
invoke `scripts/build_standalone.py`, which rewrites the **tracked** `npm/bin/skillporter.pyz` (observed
258 837 → 260 037 bytes). The file was restored with `git checkout --` before this commit; nothing in `skillporter/` or
`npm/` was modified. If a release is cut right after a test run, the committed npm payload is the locally rebuilt one,
not the published one.

## Findings

Ordered by user impact. None of them blocks installation or the core install/sync/rollback path; F1 and F3 contradict
documented workflows.

### F1 — `init` + `sync` can leave `lock --check` failing on a clean workspace (High)

Documented recipe (`README.md` step 4, `docs/lockfiles/README.md`, `docs/ci/README.md`) is `skillporter init`,
`skillporter sync`, `skillporter lock --check` in CI. With the default three-harness selection used throughout the docs
(`claude-code`, `codex`, `cursor`), the check fails immediately after a clean `sync`:

```
$ skillporter add <repo>/src/notes --harness claude-code --harness codex --harness cursor --offline
+ Installed notes across 3 harness(es) …
$ skillporter init
initialized …/skillporter.yaml (1 skill(s), harnesses: claude-code, codex, cursor)
$ skillporter sync
wrote …/skillporter.lock (1 locked skill(s))
$ skillporter lock --check
skillporter.lock check FAILED (1 issue(s)):
  - lockfile source mismatch on 'notes': skillporter.yaml has './.agents/skills/notes'
    != locked '<abs>/src/notes'
exit=1
```

An explicit `skillporter lock` does not reconcile it (same failure), and `audit` then reports
`Verdict: ACTION REQUIRED` for an otherwise healthy workspace. `doctor --fix` reports `HEALTHY` because content hashes
match — the two commands disagree about health.

Narrowed by selection: `claude-code, codex` passes; `claude-code, codex, cursor` fails; `claude-code, codex,
gemini-cli` passes; `claude-code, codex, hermes` passes. So the lockfile records the add-time source while
`init`/`sync` rewrote the manifest to `./.agents/skills/…`, and the reconciliation that works for the other
combinations does not happen for this one. Repro transcript: `evidence/repro-lock-matrix.txt` (all four selections,
same fixture, `lock --check` after `add` → `init` → `sync` → `lock`).

Impact: the headline CI guarantee ("`skillporter lock --check` verifies the lockfile in CI") can fail on a workspace
nobody edited.

### F2 — `profile use` installs beyond the profile's selected harnesses and misreports it (Medium)

A profile saved from a three-harness install then exported and imported into a clean workspace:

```
$ skillporter profile show rel          # harnesses: claude-code, codex, cursor, hermes, openclaw
  skills:
    - name: notes
      harnesses: [antigravity, claude-code, cline, codex, cursor, gemini-cli, github-copilot,
                  goose, junie, openclaw, opencode, openhands, replit, roo-code, zed]
$ skillporter profile use rel
~ Activated profile rel (1 skill(s) synchronized across claude-code, codex, cursor, hermes, openclaw)
   # actual directories created: .claude .agents .cline .github .junie .openclaw .opencode .roo
```

Three separate lists disagree: the profile header (3–5 harnesses), the message (5), and what was written (15 harness
entries / 8 directories, including isolated directories the user never selected). A user who activates a profile to
*reduce* the skill footprint instead grows it, and the console line hides that.

### F3 — `pack` archives are not byte-reproducible, so their published digests differ (Medium)

`docs/commands` and `docs/registry` describe `pack` as producing a "deterministic `.tar.gz`" whose `provenance.json`
carries `archive_sha256` (README: immutable release bundles). Two runs over identical content:

```
packed draft-notes@0.1.0: archive: …/pack1/draft-notes-0.1.0.tar.gz (sha256: f05fed22f2985a96...)
packed draft-notes@0.1.0: archive: …/pack2/draft-notes-0.1.0.tar.gz (sha256: b0d4299d8828dd4d...)
gzip mtime: 1795075395 vs 1795075396
PASS pack tar payloads are equal        # decompressed tar streams are identical
FAIL pack archives are byte-identical   # gzip header mtime differs
```

`tarfile.open(..., "w:gz")` writes the current time into the gzip header even though every `TarInfo.mtime` is zeroed.
Content-level determinism holds; the artifact digest does not. Anyone who re-packs and compares SHA-256, or mirrors the
archive by digest, sees a false change.

### F4 — After `adopt` then `move`, `outdated` reports ERROR for a healthy skill (Low)

```
$ skillporter adopt handwritten
+ Adopted 1 skill(s) … [claude-code, cline, cursor, github-copilot, opencode, replit]
$ skillporter move handwritten --from claude-code --to cursor --isolated
~ Moved handwritten: claude-code -> cursor
$ skillporter outdated handwritten
handwritten  1.0.0  unreachable  90fc266c1bcb  ERROR  ./.claude/skills/handwritten
exit=0
```

The tracked source is still the adopted location that `move` removed, so the skill looks unverifiable. Docs say `move`
relocates "without deleting its source", which is true only when the source is external to the install tree. Cosmetic
for `outdated`, but `update` shares the same resolution path, so an adopted-then-moved skill cannot be updated from its
tracked origin.

### F5 — `remove --dry-run` lists shared destinations once per harness, not once per directory (Low, docs mismatch)

`docs/commands` states that `remove` without `--harness` "first prints the destinations it would delete, once per
directory". Observed dry-run printed nine lines for two directories (eight of them pointing at the same
`.agents/skills/release-notes`), while the confirmation summary on the real run grouped them
(`codex,cursor,gemini-cli,antigravity,zed,replit,openhands,goose`). Nothing was deleted incorrectly; the preview is just
visually inflated and disagrees with the claim.

### F6 — `init` records a different harness set than the install it describes (Low)

```
$ skillporter add <src>/notes --harness claude-code --harness codex --harness hermes --offline
+ Installed notes across 3 harness(es) …
$ skillporter init
initialized …/skillporter.yaml (1 skill(s), harnesses: claude-code, codex, cursor)
$ # lock: installed_targets = ['claude-code', 'codex', 'cursor', 'hermes']
```

The manifest omits `hermes`, the one explicitly requested dedicated folder, and adds `cursor`, which was never
requested (it is the shared `.agents/skills` peer). A teammate running `sync` from the committed manifest therefore
does not reproduce the author's environment — the opposite of the "one manifest … reproducible team sync" claim — and
the selection is invisible in the file a user reviews. Same class of disagreement as F2.

### F7 — Windows path length breaks `consolidate --rollback` snapshots at 260 characters (Low, Windows-only)

`consolidate --rollback` snapshots current instruction files before restoring. When the workspace plus the snapshot
directory pushes a nested instruction file to exactly 260 characters, the snapshot fails:

```
skillporter\instructions.py:1112: in rollback_consolidation
    shutil.copy2(f.abs_path, sdest)
E   FileNotFoundError: [WinError 3] The system cannot find the path specified
```

Reproduced in a deep temp tree (path length 260) and passing unchanged in a short one (`--basetemp=C:/sptmp/pt`), which
identifies it as the MAX_PATH boundary rather than corrupt state. Deep monorepos (`.skillporter/backups/instructions/
<ts>-pre-rollback-<id>/.github/instructions/*.md`) are the realistic exposure; the failure is loud, not silent.

### F8 — `docs/TESTING.md` understates the suite it documents (Low, docs accuracy)

It states "verified by **198 automated tests** across **16 test modules**". The checkout collects **567 tests across 36
modules** (`pytest --collect-only`, `evidence/`). A reader sizing the project's test coverage is misled by a factor of
almost three.

## Not verified here

- **Harness runtimes other than Hermes** — Claude Code, Codex, Copilot, Gemini CLI, OpenCode, Cline, Continue are not
  installed on this machine. Their layouts are covered by `tests/test_adapter_conformance.py` (19 adapters, project and
  user scope) = FIXTURE, and by `docs/audits/harness-runtime-evidence-2026-11-14` (pre-existing evidence, not re-run).
  Treat the README's `RUNTIME_VERIFIED` labels as prior claims, not re-established here.
- **`--strategy symlink`** — refused by design on Windows, so only the refusal is verified.
- **Crash recovery live** — `SIGKILL` mid-swap and `flock` contention tests are POSIX-only and skipped on Windows; the
  Windows `msvcrt` lock branch passed as a unit test. `ENOSPC`/rollback was exercised by INTEGRATION only.
- **`--harness all`** — not run; `import` did fan out to the 15 shared harness entries of a pack, which is the same
  code path but not the flag.
- **Security-gate decisions** — `--max-risk-score`, `--allow-risky`, `policy check` blocking, `--engine`,
  `scan --ai-review`, `test --model`, `publish` against a real registry, GitHub PR comment posting, and `--purge-source`
  were not exercised live (they need a deliberately unsafe fixture, credentials, or an external registry). INTEGRATION
  modules cover them; no new attack content was authored.
- **Windows distribution** — `install.sh` and `skillporter-windows-x64.cmd` were not executed; only the verified
  `skillporter.pyz` was run directly.
- **`consolidate` on `.cursor/rules/*.mdc` scoped rules** and `context` for harnesses other than Claude Code were not
  exercised.

## How to reproduce

```bash
# published CLI (no global install, verified digest)
python -m venv /tmp/sp && /tmp/sp/bin/pip install \
  https://files.pythonhosted.org/packages/1f/32/6853b7e4a97770d3b8f334bfa176bf16d425e5a04bbcd9452cbff424cef/skillporter-3.2.0-py3-none-any.whl

python docs/verification/probe.py /tmp/sp/bin/skillporter --scratch /tmp/sp-work
python docs/verification/probe.py /tmp/sp/bin/skillporter --scratch /tmp/sp-work remote   # network: GitHub
python docs/verification/probe_hermes.py /tmp/sp/bin/skillporter \
  "$(python -c 'import sys; print(sys.executable)')" --scratch /tmp/sp-work                # installed Hermes only
```

Both probes exit non-zero when an anomaly is found and print `PASS`/`FAIL` per assertion plus an `Anomalies:` list; the
`FAIL` lines are F1 (twice: after `sync` and again after repair), F2, F3 and F4.

## Untested risks summary

The parts a user is most likely to hit that this pass does not prove: non-Hermes harness discovery (only fixtures), the
Windows installer path, live registry publishing, and crash recovery on Windows. The parts it does prove: installation
from three public channels, the full ordinary CLI surface in a disposable home, `.skillpack` round-trips, rollback,
dependency resolution, MCP over stdio with a real client, and one real harness loading what Skillporter installed.