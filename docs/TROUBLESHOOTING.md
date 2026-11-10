# Troubleshooting

## A skill shows `MISSING` for a harness

Run `skillporter matrix` and check the harness's project path. Then look at the
file location the matrix claims (`.claude/skills/<name>/SKILL.md`,
`.agents/skills/<name>/SKILL.md`, …). The path is almost always the problem, not
the skill.

## It works locally, not in Docker or CI

You installed with `--strategy symlink`, and the build context dropped the link.
Re-install with the default copy strategy:

```bash
skillporter install path/to/skill --harness codex --force
```

## Cursor lists the same skill twice

The skill exists in two of Cursor's four roots (it reads `.agents`, `.cursor`,
`.claude`, `.codex`). Keep one; remove the others.

## `name` does not match directory

The spec requires the frontmatter `name` to equal the containing directory name.
`skillporter validate` reports this as `name-directory-mismatch`.

## Hermes reports MISSING

Hermes is profile-scoped. Use `--scope user` and make sure `HERMES_HOME` points
at the profile you are actually running.

## `install` refuses to overwrite

That is deliberate. Existing directories and symlinks are never replaced
silently — pass `--force` once you have checked what is there.

## Exit code 1 from `diagnose` in CI

That is the contract: 1 = findings. Fail the job, read the findings, fix, re-run.
