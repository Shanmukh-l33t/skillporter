# skillporter

**Find out why your Agent Skill doesn't load — and fix it for every harness.**

[![PyPI](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-36%20passing-brightgreen)](tests/)

Every AI coding harness reads skills from a **different directory**:

| Harness | Reads | Ignores |
|---|---|---|
| Claude Code | `.claude/skills/` | `.agents/skills/` |
| OpenAI Codex | `.agents/skills/` | `.claude/skills/` |
| Cursor | `.agents/`, `.cursor/`, `.claude/`, `.codex/` | — (most permissive) |
| Hermes | `$HERMES_HOME/skills/` | everything else |
| OpenClaw | `.openclaw/skills/` | everything else |

So a skill you wrote once silently works in one harness and is invisible in the
next. People work around this with hand-made symlinks — which then break in git
worktrees, Docker build contexts, and fresh clones.

**skillporter tells you exactly which harnesses can see each skill, why the
others can't, and fixes it** — with copy-based installs that survive Docker and
CI, not fragile symlinks.

```
$ skillporter diagnose .

SKILL      claude-code     codex           cursor          hermes
----------------------------------------------------------------------
my-helper  yes             MISSING         yes             MISSING

findings:
  - skill 'my-helper' is not visible to: codex, hermes (visible to: claude-code, cursor)

$ skillporter install .claude/skills/my-helper --harness codex
created   codex        /repo/.agents/skills/my-helper  (copy via .agents/skills)

$ skillporter diagnose .
my-helper  yes             yes             yes             MISSING
```

## Why this exists

Built after reading the same complaint across many independent threads:

- [agentskills/agentskills#15](https://github.com/agentskills/agentskills/issues/15) — *"Claude is looking at `.claude/skills/` and GitHub Copilot is looking at `.github/skills/`… create symlinks that match the specific folder of each harness"* (130 comments)
- [thn-inc/claude-tweaks#3000](https://github.com/thn-inc/claude-tweaks/issues/3000) — skill resolution misses the `.agents/skills` layout *when the symlink is absent*, plus a **git worktree** variant
- [openclaw/openclaw#14593](https://github.com/openclaw/openclaw/issues/14593) — skill install fails inside Docker
- [squne121/loop-protocol](https://github.com/squne121/loop-protocol/issues) — separate issues to replace a Codex skill symlink and to make `.agents/skills` a *fail-closed* bridge
- [graysurf/agent-runtime-kit](https://github.com/graysurf/agent-runtime-kit/issues) — tracking skill prune/sync drift

Existing sync tools copy files and claim success. None of them answer *"why
isn't it loading?"* — which is the actual question.

## Install

```bash
pip install skillporter
# or, from source
git clone https://github.com/Shanmukh-l33t/skillporter && cd skillporter
python -m venv .venv && .venv/bin/pip install -e .
```

No runtime dependencies. Python 3.9+.

## Quick start

```bash
# 1. What can each harness actually see right now?
skillporter diagnose .

# 2. Who reads from where? (verified against vendor docs)
skillporter matrix

# 3. Install one skill into the harnesses you use
skillporter install path/to/my-skill --harness claude-code --harness codex

# 4. Validate SKILL.md files against the Agent Skills spec
skillporter validate .

# 5. Remove it again
skillporter uninstall my-skill --harness codex
```

Every command exits **0** when clean and **1** when it finds a real problem, so
it drops straight into CI.

## Commands

### `diagnose [path]`

Prints a skill × harness reachability matrix, broken symlinks, and spec
violations. `--json` for machine-readable output, `--harness` to limit scope.

Project-scoped by design: diagnosing a repo reports **that repo**, not whatever
you happen to have installed in your home directory.

### `install <skill> --harness <name>`

| Flag | Purpose |
|---|---|
| `--strategy copy` | **default.** Real directories — survives Docker, CI, archives, `git archive`. |
| `--strategy symlink` | Single source of truth for local dev. Refused on Windows. |
| `--scope project\|user` | Repo-relative or `$HOME`-relative. |
| `--force` | Replace an existing install (never deletes something it can't identify). |

Installing for `codex` and `cursor` together writes **once** — they share
`.agents/skills`, and duplicating it makes Cursor report the skill twice.

### `matrix`

The harness → path table above, generated from the code, with `verified` vs
`expected` clearly separated. `--json` for tooling.

### `validate [path]`

Full Agent Skills [specification](https://agentskills.io/specification) checks:
name charset/length/directory match, description length and trigger wording,
`compatibility` cap, `metadata` typing, body size budget.

## Compatibility

| Platform | Install path | Tested | Status |
|---|---|---|---|
| Claude Code | `.claude/skills/`, `~/.claude/skills/` | Yes | Supported |
| OpenAI Codex | `.agents/skills/`, `~/.agents/skills/` | Yes | Supported |
| Cursor | `.agents/`, `.cursor/`, `.claude/`, `.codex/` (+ user) | Yes | Supported |
| Hermes Agent | `$HERMES_HOME/skills/<category>/<name>` | Yes | Supported |
| OpenClaw | `~/.openclaw/skills/` | No | Expected (community convention) |

"Tested" means the path registry is covered by a regression test that asserts
the vendor's published locations. Paths marked *Expected* have not been
confirmed against that project's docs — verify before relying on them.

skillporter is a plain Python CLI, so it can also be used as a **skill** itself
from any harness: see [`skills/skillporter/SKILL.md`](skills/skillporter/SKILL.md).

## The `.agents/skills` bridge

The ecosystem is converging on `.agents/skills` as the shared location (Codex
reads it, Cursor reads it, and several projects are actively migrating to it).
The layout that works today:

```
repo/
├── .agents/skills/my-skill/SKILL.md   # canonical copy (Codex + Cursor)
└── .claude/skills/my-skill          -> ../../.agents/skills/my-skill
```

`skillporter install <skill> --harness codex --harness claude-code` produces a
copy-safe version of exactly that, and `diagnose` verifies it.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean / success |
| 1 | Findings (unreachable skill, spec violation, broken symlink) |
| 2 | Usage error (bad path, unknown harness, unsafe overwrite) |

## Troubleshooting

**"My skill shows up twice in Cursor."** You installed into both
`.agents/skills` and `.cursor/skills`. Cursor reads both; keep one.

**"It works locally but not in Docker."** The install is a symlink and the
build context dropped it. Re-install with `--strategy copy`.

**"Codex still doesn't see it."** Confirm the file is at
`.agents/skills/<name>/SKILL.md` — the directory name must match the `name`
field. `skillporter validate` catches this.

**"diagnose says MISSING for hermes."** Hermes is profile-scoped
(`$HERMES_HOME/skills`). Use `--scope user` and ensure `HERMES_HOME` is set.

## Limitations

- OpenClaw paths are unverified against upstream docs.
- Windows symlink installs are refused by design (unreliable without elevation).
- `install` never edits your source skill; it only writes into harness dirs.
- Nested category folders are followed for Cursor (recursive) but not for
  Claude Code/Codex, which use direct child directories.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Tests must pass and `ruff check .` must
be clean before a PR is considered.

## Security

See [SECURITY.md](SECURITY.md). Please do not open public issues for
vulnerabilities.

## License

MIT — see [LICENSE](LICENSE).
