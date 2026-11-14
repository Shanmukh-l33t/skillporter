# Getting started

Skillporter is a package manager for AI agent skills. It installs a `SKILL.md` package into the directories your agent harnesses actually read, keeps every copy identical, pins what was installed in a lockfile, and runs a static security assessment before anything is written.

It is a local command-line tool. Nothing is uploaded, and no account is required.

## Requirements

- Python 3.9 or newer. The core has no runtime dependencies.
- `git`, when you install skills from GitHub or another Git remote.
- Linux, macOS or Windows.

## 1. Try it without installing

The demo builds a broken workspace in a temporary directory, repairs it, and deletes it. Nothing is written to your current directory.

```bash
uvx skillporter demo
```

If you use Node instead of `uv`:

```bash
npx @shanmukhdheekonda/skillporter demo
```

## 2. Install the CLI

```bash
uv tool install skillporter
```

`pipx install skillporter` works the same way. See [Installation](../installation/README.md) for every channel, including the verified standalone installer.

## 3. See which harnesses you have

```bash
skillporter detect .
```

`detect` is read-only. It reports each harness it finds and the evidence it used: a binary on `PATH`, a user directory, a project marker or an environment variable.

## 4. Add a skill

```bash
skillporter add anthropics/skills --skill pdf --harness all
```

Skillporter resolves the source, validates the skill against the Agent Skills specification, runs the static security assessment, and only then writes files. Harnesses that share `.agents/skills` receive one copy, not one each.

Preview the plan first if you prefer:

```bash
skillporter add anthropics/skills --skill pdf --harness all --dry-run
```

To target specific harnesses, repeat the flag:

```bash
skillporter add anthropics/skills --skill pdf --harness claude-code --harness codex
```

## 5. Check the workspace

```bash
skillporter diagnose .
```

`diagnose` prints a skill by harness table: `yes`, `MISSING`, `DRIFT` or `DUPLICATE` for each pair. It then lists findings such as a broken symlink or two copies with different content, and exits `1` when there are any, so it works as a CI check.

## 6. Pin what you installed

```bash
skillporter init
skillporter sync
skillporter lock --check
```

`init` writes `skillporter.yaml`. `sync` reconciles the workspace with it and writes `skillporter.lock`. `lock --check` fails when the lockfile no longer matches the files on disk.

## Where to go next

- [Quick start](../quick-start/README.md): the full workflow in one page.
- [Harness compatibility](../harnesses/README.md): the 19 adapters and how each was verified.
- [Security model](../security/README.md): what the scanner checks and what it cannot prove.
- [CLI reference](../commands/README.md): every command and flag.
