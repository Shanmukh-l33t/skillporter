# Instruction files and context

Most developers who use more than one coding agent keep several instruction files: `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`, `.windsurfrules`, `.clinerules`, `CONVENTIONS.md` and others. They drift apart, repeat each other and sometimes contradict each other. `skillporter consolidate` finds them, reports the overlap and conflicts, and can keep them in step from one canonical source. `skillporter context` shows what a given agent will actually receive.

Neither command needs any installed skill, so they are useful even if you never use third-party skills.

## Preview first

```bash
skillporter consolidate
```

With no flags the command is read-only. It discovers instruction files in the workspace and reports:

- which agent each file belongs to (the `--json` report also includes precedence);
- how much content overlaps between files;
- directives that contradict each other, such as `Always use pnpm` against `Always use npm`;
- backticked paths that no longer exist in the repository;
- lines it could not classify, which are kept verbatim and counted so nothing is dropped silently;
- path-scoped rule files, which are listed but never rewritten.

Add `--verbose` to print the native files it would generate, or `--json` for a machine-readable report.

## Applying a consolidation

```bash
skillporter consolidate --apply
```

`--apply` writes a canonical source to `.skillporter/instructions/canonical.md`, plus per-agent additions under `.skillporter/instructions/agents/`, then regenerates the native instruction files for the agents it discovered. Use `--harness` to also generate files for specific agents that do not have one yet.

What `--apply` does and does not do:

- It copies every discovered original into `.skillporter/backups/instructions/` first. `--rollback` restores those originals.
- Running it again with nothing changed writes nothing and takes no new backup.
- It refuses to write through a symlink that leaves the workspace.
- It refuses to run when two instructions contradict each other, unless you pass `--force`. Resolve the conflict in the source files instead.
- It keeps fenced code blocks, Markdown tables, nested lists, blockquotes and short lines that are not full sentences.
- It keeps the headings your directives sat under as `## Heading` groups. Text that is not a directive, such as a title or a short line like `Node >= 24`, is kept verbatim under `Preserved Unclassified Lines` and counted in the preview, and the originals stay in the backup.
- Files with path scoping, such as a Cursor rule with `globs` or a Copilot instruction with `applyTo`, are not touched.
- It rewrites the existing instruction files it manages, after taking the backup. It does not delete them.

Agent-specific lines, for example a rule that mentions a Claude subagent, stay in that agent's file and are not copied to the others. The classification uses keywords, so review the preview before applying.

## Detecting manual edits

Generated files are tracked by SHA-256 in `.skillporter/instructions/state.json`.

```bash
skillporter consolidate --status
```

reports which generated files were changed by hand, with the lines added and removed. A later `--apply` stops on a modified file instead of overwriting it. You then choose:

```bash
skillporter consolidate --reconcile
skillporter consolidate --apply --force
skillporter consolidate --rollback
```

`--reconcile` merges the added lines into the canonical source and regenerates every target. A contradictory manual edit is still blocked. `--force` overwrites the edit. `--rollback` restores the originals from the first backup. It refuses to run while a managed file has unreconciled hand edits unless you pass `--force`, and it first saves the current files to a new backup so nothing is lost. It only restores files that match known instruction file names, and only from `.skillporter/backups/instructions/` inside the workspace.

## What an agent actually receives

```bash
skillporter context --harness claude-code
skillporter context --harness cursor
```

For each harness, `context` lists the instruction files that apply in precedence order, the files that belong to other agents and are ignored, the skills reachable from that harness, and an estimate of the tokens loaded at startup. The token figures are a four-characters-per-token estimate, not a tokenizer count, and the output says so.

## Harness notes

- **Aider** does not load `CONVENTIONS.md` on its own. Start it with `aider --read CONVENTIONS.md`, or add `read: CONVENTIONS.md` to `.aider.conf.yml`. `consolidate` prints this reminder and does not edit your aider config. This was checked against aider 0.86.2.
- **Windsurf** rules written by `consolidate` declare `trigger: always_on`. Existing Windsurf, Cline, Roo and Continue rules that are scoped by `trigger: glob`, `globs` or `paths` are treated as path-scoped and are never rewritten.

## Limits

- Directive extraction is line based. Long free-form prose is kept, but it is not understood, so check the preview before applying.
- Conflict detection covers mutually exclusive tool choices such as package managers, test runners and indentation style. It does not understand arbitrary contradictions.
- Precedence follows each vendor's documented file order. It describes which files an agent reads, and cannot tell you which instruction the model chooses to follow.

See the [CLI reference](../commands/README.md) for every option.
