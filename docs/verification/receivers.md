# Receiver validation: Codex, OpenCode, Claude Code (2026-11-19)

> Captured against **published 3.2.0** from PyPI/npm/GitHub. On the branch under test, `add` reports
> `Verified N destination(s) on disk …` and `Not verified: whether each harness discovers or loads the skill`;
> every quoted `Installation verified.` line below belongs to 3.2.0.

Independent check of what the receiving harness lists, using each harness's own discovery API. Candidate `69bdc31e59e5fae0a30e94df710a3cf96059c784` (Skillporter 3.2.0). Windows 11 26300, git-bash, Python 3.14.9, npm 12.2.2. **Verdict: Codex project, OpenCode project and OpenCode user scope list the exact installed name and description, before/after/remove. Codex user scope was not observable under isolation and stays unverified.**

## Method

Harnesses were installed only into a disposable npm prefix (`npm install --prefix <scratch>/bin --cache <scratch>/npm-cache`, official registry packages), with all child state inside one scratch directory: `HOME`/`USERPROFILE` = `<scratch>/home`, `CODEX_HOME` = `<scratch>/codex-home`, `XDG_CONFIG_HOME` = `<scratch>/home/.config`, plus disposable `project` and unrelated `other` working directories. Skillporter ran from the checkout (`python -m skillporter`, `PYTHONPATH`), never an installed copy. No model call, no login, no credential, no user/global install, no live profile or trust setting touched, no workspace trust altered, no exploit workflow.

Discovery oracles, both the harness's own non-model surfaces:

- Codex: `codex app-server` JSON-RPC over stdio — `initialize`, `initialized`, then `skills/list` with `{"cwds":[<cwd>],"forceReload":true}`. The method and parameter names came from `codex app-server generate-json-schema --out …` (offline, 0.170.0).
- OpenCode: `opencode debug skill` (JSON array of name, description, location).
- Claude Code: no offline listing subcommand exists in `claude --help` (2.1.328); not exercised, no claim.

Both harnesses resolve user scope from the OS profile on Windows rather than `$HOME`: with `CODEX_HOME` unset, Codex listed skills from the real profile; OpenCode ignored `$HOME` until `XDG_CONFIG_HOME` was set. That is why the isolated user-scope legs set those variables explicitly.

Each leg ran in order: receiver list (empty) → `skillporter add <fixture> --harness <h> --scope <s> --dry-run` → receiver list → `skillporter add …` → receiver list in the project and in the unrelated cwd → `skillporter remove <name> --harness <h> --scope <s> -y` → receiver list, plus source-preserved and installed-path checks.

## Results

| Receiver | Scope | Skillporter destination | Listed before | Listed after add (exact) | Listed after remove |
|---|---|---|---|---|---|
| codex-cli 0.170.0 | project | `project/.agents/skills/<name>` | absent | name `receivers-probe-codex`, description `codex receivers fixture receivers-probe-codex.`, `scope: "repo"`, `enabled: true`; absent in the unrelated cwd | absent |
| codex-cli 0.170.0 | user | `home/.agents/skills/<name>` | absent | **not listed** (see below) | absent |
| opencode 1.19.6 | project | `project/.opencode/skills/<name>` | absent | name `receivers-probe-opencode`, description `opencode receivers fixture receivers-probe-opencode.`, location `…/project/.opencode/skills/receivers-probe-opencode/SKILL.md`; absent in the unrelated cwd | absent |
| opencode 1.19.6 | user | `home/.config/opencode/skills/<name>` | absent | same exact name and description, location `…/home/.config/opencode/skills/receivers-probe-opencode/SKILL.md` | absent |
| claude 2.1.328 | — | — | — | no offline listing surface | — |

`--dry-run` wrote nothing in every leg (destination absent immediately afterwards), `add` and `remove` exited 0, each install landed at the destination printed by `add`, and the fixture source survived removal in both harnesses.

### Codex user scope: unverified, not failed

With `CODEX_HOME=<scratch>/codex-home`, the same `SKILL.md` placed by hand at `<CODEX_HOME>/skills/<name>` was listed as `scope: "user"`, while the Skillporter-written copy under `home/.agents/skills` was not. Pointing `CODEX_HOME` at `home/.agents` — the parent of Skillporter's target — made that copy list as `scope: "user"`. So the installed content is loadable and the path is only reachable by this binary when `CODEX_HOME` is the `.agents` parent; the 0.170.0 binary does contain a `user-agent-skills`/`.agents/skills` scope label, so a user-level root may exist under the real profile. Confirming that would need a write to the live user profile, which was out of scope. On a normal install (`CODEX_HOME` unset, default `~/.codex`) Skillporter's codex user destination is `~/.agents/skills`, not `$CODEX_HOME/skills`; whether Codex reads it there is untested here.

### Installer report vs receiver visibility

`skillporter add` printed `Installation verified.` in every leg, including Codex user scope where this receiver listed nothing. That matches the field review: the installer's verification covers bytes at the destination, not visibility in the harness. Nothing here promotes or demotes an adapter's tier beyond its own evidence guide.

## Errors and limits

The npm build in use does not run package postinstall scripts; `opencode` needed `node postinstall.mjs` and `claude` needed `node install.cjs` inside the scratch prefix before they would start. No other failure occurred. Observed: discovery/listing only, one CLI version each, project and user scope only, Windows only (WSL was checked for tooling but carried no harness binary, so nothing was run there). Not tested: prompt inclusion, skill activation, `$CODEX_HOME/skills` as a Skillporter target, admin/system scopes, symlink installs, Claude Code entirely, any live profile.

## Replay

Fixture: a directory `<src>/<name>/SKILL.md` with `name: receivers-probe-<harness>` and a unique description line. Then, from the scratch directory with the variables above exported:

```
codex app-server                     # JSON-RPC: initialize, initialized, skills/list {"cwds":[...],"forceReload":true}
opencode debug skill                 # JSON list
python -m skillporter add  <src>/<name> --harness <h> --scope <s> --dry-run
python -m skillporter add  <src>/<name> --harness <h> --scope <s>
python -m skillporter remove <name>     --harness <h> --scope <s> -y
```

Pass condition is the exact fixture name and description appearing in the receiver's own listing only between `add` and `remove`, absent in the unrelated cwd, and the fixture source still present — not a zero exit code.