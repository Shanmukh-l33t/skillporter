# Configuration

skillporter has no config file. Everything is a flag, so behaviour is explicit
and reproducible in CI.

## Environment variables

| Variable | Effect | Default |
|---|---|---|
| `HERMES_HOME` | Hermes profile home used to resolve `$HERMES_HOME/skills` | `~/.hermes` |
| `HOME` | Base for user-scope installs on POSIX | OS default |

No API keys are read. The tool makes no network requests.

## Common invocations

```bash
# CI gate: fail if any skill is unreachable in the harnesses we ship for
skillporter diagnose . --harness claude-code --harness codex

# Validate every SKILL.md in a monorepo
skillporter validate .

# Machine-readable report for a dashboard
skillporter diagnose . --json > skills-report.json

# Local dev: one source of truth via symlinks
skillporter install skills/foo --harness claude-code --strategy symlink
```
