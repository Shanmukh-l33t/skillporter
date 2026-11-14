# CI and GitHub Actions

Skillporter's checks return deterministic exit codes, so any CI system can run them. The repository also ships a composite GitHub Action.

## The three checks worth running

```bash
skillporter validate .
skillporter scan .
skillporter lock --check
```

| Command | Fails when |
|---|---|
| `validate` | A `SKILL.md` breaks the Agent Skills specification. |
| `scan` | The static assessment blocks a skill, or its score exceeds `--max-risk-score`. |
| `lock --check` | The lockfile is stale, or files on disk no longer match it. |

Exit code `1` means a finding. Exit code `2` means the command could not run.

## Any CI system

```yaml
steps:
  - run: pipx install skillporter
  - run: skillporter validate .
  - run: skillporter scan . --max-risk-score 30
  - run: skillporter lock --check
```

Pin the version you install so a new release cannot change your build without a commit:

```bash
pipx install skillporter==3.0.0
```

## GitHub Action

```yaml
name: skills
on: [pull_request]

permissions:
  contents: read

jobs:
  skillporter:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Shanmukh-l33t/skillporter@v3.0.1
        with:
          command: validate
          lock-check: "true"
          max-risk-score: "30"
```

The action installs Skillporter from the tagged checkout, runs the primary command, then runs the security scan and writes a SARIF file.

### Inputs

| Input | Default | Description |
|---|---|---|
| `command` | `validate` | Primary check: `validate`, `scan`, `diagnose`, `doctor`, `lock` or `audit`. |
| `path` | `.` | Repository or skill directory. |
| `harnesses` | | Harness IDs for `diagnose`. |
| `run-security-scan` | `true` | Also run `skillporter scan` and write SARIF. |
| `max-risk-score` | | Fail when a skill's risk score is above this value. |
| `sarif-file` | `skillporter.sarif` | Where to write the SARIF 2.1.0 report. |
| `upload-sarif` | `false` | Upload the SARIF file to GitHub code scanning. |
| `lock-check` | `false` | Run `skillporter lock --check`. |
| `pr-comment` | `false` | Post the `skillporter ci-report` summary on the pull request. |
| `python-version` | `3.12` | Python version to set up. |

### Code scanning

Uploading SARIF needs the `security-events: write` permission:

```yaml
permissions:
  contents: read
  security-events: write

steps:
  - uses: actions/checkout@v4
  - uses: Shanmukh-l33t/skillporter@v3.0.1
    with:
      command: scan
      upload-sarif: "true"
```

### Pull request report

`pr-comment: "true"` posts the output of `skillporter ci-report`: a reachability table, risk scores and lockfile status. The job needs `pull-requests: write`.

You can produce the same report yourself:

```bash
skillporter ci-report . --output report.md
```

## SARIF without the action

```bash
skillporter scan . --format sarif > skillporter.sarif
```

## Reproducible installs in CI

To install the standalone binary in a pipeline, pin both the tag and the digest so the build fails if the artifact ever changes:

```bash
curl -fsSL https://github.com/Shanmukh-l33t/skillporter/releases/download/v3.0.1/install.sh -o install.sh
SKILLPORTER_VERSION=v3.0.1 \
SKILLPORTER_SHA256=8bd7125b8f2a1a4f7c475406c71eaaec317bc4d7a0dd5d19e857301ef127179c \
sh install.sh
```

See [Installation](../installation/README.md) for the trust model.

## Agents in CI

If a CI job runs an agent with the MCP server attached, leave the server in its default read-only mode. See [MCP integration](../mcp/README.md).
