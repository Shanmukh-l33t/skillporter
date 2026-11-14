---
title: "What is an agent skill?"
heading: "What is an agent skill, and why it needs a manager"
description: "An agent skill is a directory with a SKILL.md file. Here is the format, the directory each harness reads, and where copying skills by hand breaks down."
date: "2026-11-12"
---

## The short answer

An agent skill is a directory with a `SKILL.md` file in it. That file starts with a YAML frontmatter block holding at least a `name` and a `description`, followed by Markdown instructions. The directory may also hold `scripts/`, `references/` and assets. A harness scans its skills directory, reads the frontmatter of everything it finds, and pulls the body of a skill into the model's context when a task matches that skill.

The agent gains a capability by reading files. Nothing is compiled or installed into the agent itself, which is why skills spread quickly: any text an agent can read is a candidate capability.

## What the directory looks like

```text
release-notes/
├── SKILL.md
├── scripts/
│   └── collect_changes.py
└── references/
    └── house-style.md
```

`SKILL.md` is the only required file. It begins with frontmatter:

```yaml
---
name: release-notes
description: Drafts release notes from merged pull requests. Use when the user asks for a changelog, a release summary, or what shipped since the last tag.
license: MIT
allowed-tools: Read Grep Bash
---
```

Then the instructions, as ordinary Markdown: what to read, in what order, what to produce, and what to leave alone.

Two frontmatter rules are enforced rather than suggested. `name` must match the directory name, and may not exceed 64 characters. `description` may not exceed 1,024 characters. Both limits come from the Agent Skills specification, and `skillporter validate` reports `name-directory-mismatch` and `description-too-long` when a skill breaks them.

Other recognized fields include `license`, `compatibility`, `metadata` and `version`. `allowed-tools` is a space separated string naming the tools the skill expects to use.

## Why every harness reads a different directory

There is no single agreed location for skills. Skillporter's registry records a project level directory and a user level directory per harness. Its 19 entries, as published in the [harness matrix](/docs/harnesses):

| Harness | Project directory |
|---|---|
| Hermes Agent | `.hermes/skills` |
| Claude Code | `.claude/skills` |
| OpenAI Codex | `.agents/skills` |
| Cursor | `.agents/skills` |
| GitHub Copilot | `.github/skills` |
| Gemini CLI | `.agents/skills` |
| Google Antigravity | `.agents/skills` |
| Windsurf | `.windsurf/skills` |
| Cline | `.cline/skills` |
| Roo Code | `.roo/skills` |
| OpenCode | `.opencode/skills` |
| Zed | `.agents/skills` |
| Replit Agent | `.agents/skills` |
| JetBrains Junie / AI Assistant | `.junie/skills` |
| OpenClaw | `.openclaw/skills` |
| OpenHands | `.agents/skills` |
| Goose | `.agents/skills` |
| Continue | `.continue/skills` |
| Aider / AiderDesk | `.aider-desk/skills` |

Eight of them use `.agents/skills` as their primary project path. Six more read it as a documented compatibility path. Claude Code is not among either group: it reads `.claude/skills` and nothing else. A skill placed only in `.agents/skills` is invisible to it.

Support type is a separate axis. Seventeen harnesses read `SKILL.md` natively, Continue reads it through a compatibility loader, and Aider needs a controlled conversion: the core CLI requires `--read` or an adapted `CONVENTIONS.md`.

### The fragmentation problem

Use three harnesses and one skill needs three copies. Hand-made copies stop being equal the first time someone edits one, so two agents in the same repository follow different instructions for the same task.

The copy count grows with the team, not just the number of tools. Every new machine, every CI checkout and every upstream update repeats the work, and each repetition can copy from a stale directory.

Shared directories add a quieter failure. Because 14 harnesses read `.agents/skills` in some capacity, that directory has several owners: delete a skill for one and you delete it for the rest. Install into both `.agents/skills` and `.cursor/skills` and Cursor lists it twice.

None of this is a defect in any one harness. Each chose a path, and the paths do not agree. What is missing is something that knows all of them at once.

## Progressive disclosure, and why the description decides everything

Skills load in layers, because context is finite and 40 skills would not fit in any of it.

1. The frontmatter is indexed. Name and description are read for every skill the harness discovers.
2. The body is loaded when the skill is selected. The instructions arrive only after a task matches.
3. `references/` and `scripts/` are read when the instructions point at them, or executed when the skill needs a result.

Only the first layer is always present, so `description` is not documentation. It is the trigger. "Helps with documents" tells the model nothing about when to reach for it, and a skill nobody can find never runs.

That is why the validator checks description quality. It warns on `description-vague` below 20 characters, and on `description-no-trigger` when the text never says when the skill applies. A useful description states what the skill does and when to use it, in one sentence, with the trigger spelled out.

The layers also explain a harness limit worth knowing: Cline expects the `SKILL.md` body to stay under 5,000 tokens. Detail that does not fit belongs in `references/`, where it costs nothing until it is read.

## The practical workflow

Manual copies are the problem. Four commands cover the loop that replaces them.

Install from a source, for every harness at once:

```bash
skillporter add anthropics/skills --skill pdf --harness all
skillporter add ./skills/release-notes --harness claude-code --harness codex --dry-run
```

`add` resolves the source into a temporary directory, validates the skill against the specification, runs the static assessment, then plans one destination per adapter. Harnesses that share `.agents/skills` share a single write, and all destinations land in one transaction. `--dry-run` stops after the plan and prints it.

Find out what each harness can actually see:

```bash
skillporter diagnose .
```

`diagnose` reports which harnesses see each skill, plus drift between copies, duplicates and broken symlinks. It answers "why is this skill missing in Claude Code" without the table above.

Check the content before trusting it:

```bash
skillporter scan .
skillporter scan . --max-risk-score 30
```

`scan` runs the static assessment over every skill in the workspace and produces a risk score from 0 to 100. `--max-risk-score` turns a threshold into a failing exit code, which makes the check usable in CI.

Then pin the result and verify the pin:

```bash
skillporter lock
skillporter lock --check
```

`lock --check` writes nothing. It exits 1 when `skillporter.lock` is stale, or when the files on disk no longer match the hashes recorded in it, so a stale copy fails a build instead of quietly reaching an agent.

## A skill is a dependency, so treat it like one

A skill is instructions plus, often, executable scripts, loaded into an agent with your permissions in your repository. That makes it a supply chain surface, not a text file. Instructions can tell an agent to read a credential file; scripts can do it directly.

So read before you install. Open `SKILL.md`, read the description and the body, look at what is in `scripts/`, and check `allowed-tools` against what the task needs. That review is the only step that reasons about intent.

The static scan is a filter, not a sandbox. It finds known dangerous patterns: `eval` and `shell=True`, credential file reads, hidden Unicode, override phrasing, encoded payloads split across files. It cannot tell you what a skill will do once a model is driving it, and a clean result does not prove a skill is safe at runtime. It also cannot follow a URL that serves harmless content at scan time and something else later.

Use the scan to reject the obvious, use the lockfile to catch silent changes, and use your own reading for everything else.

Skillporter's documentation covers [skill management](/docs/skill-management) and the [full harness registry](/docs/harnesses), and [scanning agent skills before install](/blog/scanning-agent-skills-before-install) goes deeper on what the assessment does and does not see.