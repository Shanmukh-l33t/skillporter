---
title: "Agent skill management questions, answered"
heading: "Common questions about managing agent skills"
description: "Short answers about installing, pinning, scanning and rolling back SKILL.md packages across 19 harnesses, coding and autonomous, including what a static scan cannot prove."
kicker: "FAQ"
faq:
  - q: "What is Skill Porter?"
    a: "Skill Porter is a package manager for AI agent skills. It installs a SKILL.md package into the directories your harnesses read, validates it against the Agent Skills specification, runs a static security scan, pins the result in a lockfile, and can roll it back later."
  - q: "What is a SKILL.md skill?"
    a: "A skill is a directory with SKILL.md at its root, plus optional scripts/, references/ and other assets. The file holds a YAML frontmatter block and Markdown instructions that the harness loads into the model's context."
  - q: "How is Skill Porter different from copying skill folders by hand?"
    a: "Hand copies quietly diverge. Skill Porter resolves the source once, writes every destination in a single transaction, and writes .agents/skills once for the eight harnesses that use it as their primary directory."
  - q: "How do I install Skill Porter?"
    a: "Run it through uvx or npx, or install it with uv tool install or pipx install. Python 3.9 or newer is required, and the package has no runtime dependencies; the standalone installer covers Linux and macOS only."
  - q: "What is skillporter.lock, and why run lock --check?"
    a: "skillporter.lock records what is installed: the resolved Git commit, one SHA-256 over the whole skill directory, a hash per file, the pin state and the adapter version."
  - q: "What happens when copies of a skill drift?"
    a: "Drift means two copies of one skill have different content, usually after someone edits .claude/skills/<skill> and forgets .agents/skills/<skill>."
  - q: "How does rollback work?"
    a: "Installs are staged under .skillporter/tmp/ with a write-ahead journal, so a failed install restores the destinations it already wrote."
  - q: "Does Skill Porter need network access?"
    a: "Only to fetch a source you name from a Git remote or URL, and git is required for GitHub installs. Scanning, validation, locking, diagnosing and rollback read local files."
  - q: "Does Skill Porter upload anything?"
    a: "No. It runs locally, needs no account, and nothing leaves the machine during install, scan or sync. Telemetry is off by default."
  - q: "What does the security scan actually check?"
    a: "The built-in engine reads files and never executes them. It parses Python ASTs and JavaScript or TypeScript, inspects Markdown for instruction overrides and hidden text, and looks for embedded credentials, shell pipes, unsafe deserialization, encoded payloads, cross-file staged execution and symlink escapes."
  - q: "Does a clean scan mean a skill is safe?"
    a: "No. Every report is labeled STATIC_SECURITY_ASSESSMENT, and NO_DETECTED_FINDINGS means exactly that: nothing matched."
  - q: "Which harnesses does Skill Porter support?"
    a: "19 adapters: Claude Code, OpenAI Codex, Cursor, GitHub Copilot, Gemini CLI, Google Antigravity, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit Agent, JetBrains Junie, Hermes Agent, OpenClaw, OpenHands, Goose, Continue and Aider."
  - q: "Does Skill Porter work on Windows?"
    a: "Yes. It runs on Python 3.9 or newer on Windows, and CI runs the same checks on Linux, macOS and Windows. Install with uv, pipx or npx, because the standalone install.sh is Linux and macOS only."
  - q: "Can I run Skill Porter in CI?"
    a: "Yes. Three checks cover most of it: validate for the specification, scan --max-risk-score 30 for the static assessment, and lock --check for pinned content."
  - q: "Is Skill Porter free, and what license is it under?"
    a: "Yes. It is open source under the MIT license, so you can use, modify and redistribute it, including commercially. The source is on [GitHub](https://github.com/Shanmukh-l33t/skillporter), the package is on PyPI as skillporter and on npm as @shanmukhdheekonda/skillporter, and there is no account or key to obtain."
  - q: "How do I report a security vulnerability?"
    a: "Report it privately through GitHub Security Advisories on the [repository](https://github.com/Shanmukh-l33t/skillporter), not in a public issue."
---

## Getting started

### What is Skill Porter?

Skill Porter is a package manager for AI agent skills. It installs a `SKILL.md` package into the directories your harnesses read, validates it against the Agent Skills specification, runs a static security scan, pins the result in a lockfile, and can roll it back later. It ships as a local command line tool and MCP server with no runtime dependencies, and it covers 19 harnesses.

### What is a SKILL.md skill?

A skill is a directory with `SKILL.md` at its root, plus optional `scripts/`, `references/` and other assets. The file holds a YAML frontmatter block and Markdown instructions that the harness loads into the model's context. That is why a skill counts as a supply-chain package rather than a note: many of them bundle scripts the agent is told to run.

### How is Skill Porter different from copying skill folders by hand?

Hand copies quietly diverge. Skill Porter resolves the source once, writes every destination in a single transaction, and writes `.agents/skills` once for the eight harnesses that use it as their primary directory. SHA-256 hashes show which copy changed, `skillporter remove` keeps a shared copy while another harness still owns it, and the lockfile makes the result reproducible. Symlinks break in Docker, CI, worktrees and Windows clones; real files do not.

### How do I install Skill Porter?

Run it through `uvx` or `npx`, or install it with `uv tool install` or `pipx install`. Python 3.9 or newer is required, and the package has no runtime dependencies; the standalone installer covers Linux and macOS only. The demo builds a broken workspace in a temporary directory and deletes it, so you can try the tool before pointing it at a repository.

```bash
uvx skillporter demo
pipx install skillporter
skillporter add anthropics/skills --harness all --dry-run
```

## Using it

### What is skillporter.lock, and why run lock --check?

`skillporter.lock` records what is installed: the resolved Git commit, one SHA-256 over the whole skill directory, a hash per file, the pin state and the adapter version. Commit it next to `skillporter.yaml`. `skillporter lock --check` writes nothing and exits 1 when the lockfile is stale or the files on disk no longer match it, which is what makes it a usable CI check.

### What happens when copies of a skill drift?

Drift means two copies of one skill have different content, usually after someone edits `.claude/skills/<skill>` and forgets `.agents/skills/<skill>`. `skillporter diagnose` hashes every copy and reports `DRIFT`, `MISSING` or `DUPLICATE`. A plain `sync` then stops instead of choosing a winner. Name the authoritative copy with `--prefer`; the copies about to be replaced are snapshotted to `.skillporter/backups/` first.

```bash
skillporter diagnose .
skillporter sync --force --prefer .agents/skills/pdf
```

### How does rollback work?

Installs are staged under `.skillporter/tmp/` with a write-ahead journal, so a failed install restores the destinations it already wrote. `update` and a forced `sync` copy the previous version into `.skillporter/backups/` first. `skillporter rollback pdf` restores the newest snapshot and its dependencies, verified by SHA-256, and `--backup-id` selects an older one. Ten snapshots are kept per skill.

```bash
skillporter rollback pdf
```

## Security

Agent skills are untrusted input. These answers cover what Skill Porter checks and where the checks stop; the [security model](/docs/security) has the full detail.

### Does Skill Porter need network access?

Only to fetch a source you name from a Git remote or URL, and `git` is required for GitHub installs. Scanning, validation, locking, diagnosing and rollback read local files. `--offline`, or `SKILLPORTER_OFFLINE=1`, forces the built-in scanner and skips the optional external engine. No account or login is involved at any point.

### Does Skill Porter upload anything?

No. It runs locally, needs no account, and nothing leaves the machine during install, scan or sync. Telemetry is off by default. If you enable it, events are appended to `.skillporter/telemetry.jsonl` inside the workspace with a hashed workspace id and no paths, repository URLs, usernames or skill contents. `DO_NOT_TRACK=1` disables it whatever else is set.

### What does the security scan actually check?

The built-in engine reads files and never executes them. It parses Python ASTs and JavaScript or TypeScript, inspects Markdown for instruction overrides and hidden text, and looks for embedded credentials, shell pipes, unsafe deserialization, encoded payloads, cross-file staged execution and symlink escapes. Findings roll into a deterministic 0 to 100 risk score that gates `add`, `install`, `update` and `sync`. `--format sarif` writes a SARIF report for code scanning.

### Does a clean scan mean a skill is safe?

No. Every report is labeled `STATIC_SECURITY_ASSESSMENT`, and `NO_DETECTED_FINDINGS` means exactly that: nothing matched. Prompt injection written in ordinary prose, content a URL serves only at runtime, deeper obfuscation and the host's own tool permissions all sit outside its reach. Use the scan to remove known hazards and to make review faster, not as the only control.

## Compatibility

Skillporter ships one adapter per harness and records how each was verified. The [harness matrix](/docs/harnesses) lists every directory, compatibility path and known limitation.

### Which harnesses does Skill Porter support?

19 adapters: Claude Code, OpenAI Codex, Cursor, GitHub Copilot, Gemini CLI, Google Antigravity, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit Agent, JetBrains Junie, Hermes Agent, OpenClaw, OpenHands, Goose, Continue and Aider. Seventeen read `SKILL.md` natively, Continue reads it through a compatibility path, and Aider needs an adapted conventions file. `skillporter matrix` prints the same table, including which adapters are runtime verified.

### Does Skill Porter work on Windows?

Yes. It runs on Python 3.9 or newer on Windows, and CI runs the same checks on Linux, macOS and Windows. Install with `uv`, `pipx` or `npx`, because the standalone `install.sh` is Linux and macOS only. The default copy strategy writes real files, which survives Windows clones where symlinks are often not preserved.

```bash
npx @shanmukhdheekonda/skillporter diagnose .
```

## Project

### Can I run Skill Porter in CI?

Yes. Three checks cover most of it: `validate` for the specification, `scan --max-risk-score 30` for the static assessment, and `lock --check` for pinned content. Exit code 1 means a finding and exit code 2 means the command could not run, so a pipeline can tell a failed check from a broken one. SARIF output feeds GitHub code scanning, and a composite action wraps all three.

```bash
skillporter validate .
skillporter scan . --max-risk-score 30
skillporter lock --check
```

### Is Skill Porter free, and what license is it under?

Yes. It is open source under the MIT license, so you can use, modify and redistribute it, including commercially. The source is on [GitHub](https://github.com/Shanmukh-l33t/skillporter), the package is on PyPI as `skillporter` and on npm as `@shanmukhdheekonda/skillporter`, and there is no account or key to obtain.

### How do I report a security vulnerability?

Report it privately through GitHub Security Advisories on the [repository](https://github.com/Shanmukh-l33t/skillporter), not in a public issue. Include the release, the command you ran and a minimal reproduction. The security policy states an acknowledgement within 72 hours and a remediation timeline within 14 days, and it lists the supported versions.
