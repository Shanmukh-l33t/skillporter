# Policy, capabilities and update review

This page covers the controls that decide what may be installed, and the tools that show what changed before you accept an update. All of it runs locally.

## Capabilities

A skill can declare what it needs in its frontmatter:

```yaml
---
name: release-notes
description: Draft release notes from merged pull requests.
capabilities:
  - filesystem_read
  - shell_exec
---
```

The recognized names are `network`, `shell_exec`, `filesystem_read`, `filesystem_write`, `env_access`, `script_exec`, `subagent_fork` and `hooks`. Common spellings such as `shell-exec` and `Shell Exec` are normalized. An unrecognized name is reported by `skillporter lint` as `invalid-capability`, so a typo does not silently disable a check.

Skillporter compares what a skill declares with what static analysis infers from its files. A skill that declares no network access but ships a script that downloads from a server is reported as a mismatch.

This is an audit, not enforcement. A declaration is not a sandbox, and Skillporter cannot stop a harness from running what a skill contains. Enforcement depends on the harness.

## Project policy

```bash
skillporter policy init
skillporter policy check
skillporter policy show
```

`policy init` writes a starter `skillporter.policy.yaml` that you commit with the repository.

```yaml
block_severity: HIGH
max_risk_score: 30
require_declared_capabilities: false
require_pinned_refs: true
approved_sources:
  - Shanmukh-l33t/*
  - ./skills/*
restricted_sources: []
banned_capabilities:
  - network
allowed_harnesses:
  - claude-code
  - codex
```

The policy is evaluated before `add`, `install`, `sync` (including `sync --prefer`), `update`, `import`, profile switches and the MCP write tools. It applies in project and user scope alike, because the policy file lives in the workspace you run from. `allowed_harnesses` is also enforced by `move`, `self-skill install` and `doctor --fix`.

A malformed policy stops the command with `error:` and exit code `2`. Unknown capability names, an unknown harness, a `max_risk_score` outside 0 to 100 and an unknown `block_severity` are all rejected instead of being ignored, because a silently ignored rule is worse than a loud one.

When `approved_sources` or `restricted_sources` is set, `import` treats a package skill with no source as a violation. A package can claim any source it likes and Skillporter cannot verify that offline, so for packages the allowlist is only as trustworthy as the package. Treat an imported package the way you treat any file from an untrusted place. Local source paths are resolved before they are matched, so `approved/../elsewhere` does not match `approved/*`. `policy check` evaluates the skills already installed. A violation exits `1`.

## Reviewing an update

```bash
skillporter update --check
skillporter update pdf
```

`update --check` changes nothing. For each skill with a newer upstream version it reports the added, removed and modified files, capabilities that appeared or disappeared, the change in risk score, and any security finding that is new in this version, with the file and line. A new finding is shown even when the version number and total score are unchanged.

## Optional AI second opinion

```bash
skillporter scan ./release-notes --ai-review --ai-model provider:model --yes-send
```

The static scanner cannot recognize prompt injection written in ordinary prose. `--ai-review` asks a model you choose to read the skill. The model is given as `openai:<model>` or `anthropic:<model>`. It is off by default, needs your own API key in the environment, and sends nothing unless `--yes-send` is present. Sensitive files such as `.env*`, private keys and credential files are withheld completely and inline tokens or key blocks are redacted before transmission, and non-loopback cleartext `http://` base URLs are refused. The result is advisory. The local scan works without it, and a clean result from either scan is not proof that a skill is safe.

See [Security scanning](../security-scanning/README.md) for finding codes and [Security model](../security/README.md) for the limits of static analysis.
