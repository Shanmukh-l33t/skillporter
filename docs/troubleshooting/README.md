# Troubleshooting

Start with the health check:

```bash
skillporter doctor .
```

`doctor` reports a chain of states for each skill and harness: `FOUND`, then `VALID` or `INVALID`, then `COMPATIBLE` or `ADAPTED`, then `INSTALLED` or `MISSING`. For any code you do not recognize:

```bash
skillporter explain DRIFT
```

## A skill shows `MISSING` for a harness

That harness does not read the directory the skill is in. Claude Code reading only `.claude/skills` is the most common case.

```bash
skillporter info claude-code
skillporter sync
```

`info` lists every path the harness scans. `sync` or `doctor --fix` installs the missing copy.

## A skill shows `DRIFT`

Two copies have different content. Decide which copy is right, then:

```bash
skillporter sync --force --prefer .agents/skills/<skill>
```

The replaced copies are snapshotted to `.skillporter/backups/`. A plain `skillporter sync` refuses to overwrite drifted copies, so a manual edit is never lost silently. See [Synchronization](../synchronization/README.md).

## A skill shows `DUPLICATE`

One harness finds the same skill in two directories it scans. Cursor reading both `.agents/skills/<skill>` and `.cursor/skills/<skill>` is the usual cause. Keep the shared copy:

```bash
skillporter remove <skill> --harness cursor
```

Skillporter removes the Cursor-only copy and preserves `.agents/skills/<skill>` for the other harnesses.

## A broken symlink is reported

The link's target no longer exists. This is common after `git worktree`, a Docker build or a Windows clone.

```bash
skillporter doctor --fix
```

Prefer `--strategy copy`, the default, in environments that do not preserve symlinks.

## A skill shows `INVALID`

The `SKILL.md` frontmatter breaks the specification. Two frequent causes:

- `frontmatter-tab-indentation`: replace tab characters with spaces in the YAML block.
- `name-directory-mismatch`: the `name:` field must equal the parent directory name.

```bash
skillporter validate .
```

## Installation is blocked by the security policy

`add`, `install`, `update` and `sync` run the static assessment before writing. See exactly what was found:

```bash
skillporter scan <path>
skillporter explain <finding-code>
```

If you have reviewed the findings and accept them, pass `--allow-risky`. The decision is recorded in the audit log. `--force` does not bypass a security block, and structural escapes cannot be accepted.

## The scan reports `INCOMPLETE_ASSESSMENT`

A file was larger than 2 MiB or could not be read, so the scanner could not inspect everything. Inspect the file yourself. Skillporter will not approve a skill it could not fully read.

## `lock --check` fails in CI

The lockfile no longer matches the workspace. Run it locally to see which entry differs:

```bash
skillporter lock --check
```

If the change is intended, run `skillporter sync` and commit the updated `skillporter.lock`. If it is not, something modified a skill outside Skillporter.

## An update went wrong

```bash
skillporter rollback <skill> --dry-run
skillporter rollback <skill>
```

## The standalone installer refuses to install

`error: refusing to install unattested artifact` means no authenticity check was available. Install and sign in to the GitHub CLI, or pin the digest with `SKILLPORTER_SHA256`. See [Installation](../installation/README.md).

`error: invalid SKILLPORTER_VERSION` means the value is not an immutable release tag. Use a tag such as `v3.0.0`.

## An MCP tool call is refused

Write tools are disabled unless the server runs with `--allow-writes`, and paths outside the workspace root are always rejected. See [MCP integration](../mcp/README.md).

## Still stuck

Open an issue at [github.com/Shanmukh-l33t/skillporter/issues](https://github.com/Shanmukh-l33t/skillporter/issues) with the output of `skillporter --version` and `skillporter doctor . --json`. For a suspected vulnerability, use a private security advisory instead.
