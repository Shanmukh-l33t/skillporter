---
title: "Install Skillporter"
heading: "Install Skillporter and verify the download"
description: "Install Skillporter with uv, pipx, npx or the verified release installer, check the download before it runs, then wire it into MCP and CI."
kicker: "Install"
---

## Quick install

Every channel runs the same Python core. Python 3.9 or newer is required, the package has no runtime dependencies, and nothing is uploaded.

Run it once, no install:

```bash
uvx skillporter diagnose .
```

Or with Node, a thin launcher around the same Python zipapp that needs a Python 3.9+ interpreter (`python3`, `python` or `py -3`) or `uvx` on `PATH`:

```bash
npx @shanmukhdheekonda/skillporter diagnose .
```

Install it permanently:

```bash
uv tool install skillporter
```

```bash
pipx install skillporter
```

Both install into an isolated environment, avoiding the externally managed environment error system `pip` raises on current Linux distributions. Confirm the build:

```bash
skillporter --version
```

### The standalone installer

Linux and macOS only. On Windows, use `uv`, `pipx` or `npx`. Download the installer from the immutable release tag into a file, read it, then run it:

```bash
curl -fsSL https://github.com/Shanmukh-l33t/skillporter/releases/download/v3.0.0/install.sh -o install.sh
SKILLPORTER_VERSION=v3.0.0 sh install.sh
```

The installer is deliberately not a one-line pipe into a shell: saving it to a file lets you read it first. It also stops unless it can prove where the download came from, which is the next section.

## Verify what you downloaded

A checksum fetched from the same place as the file detects corruption but does not prove who published it, so the installer refuses to continue until one independent check passes.

The installer also rejects mutable refs such as `main` or `latest`, checks the payload is a valid Python zipapp without running it, and stages it in the destination directory so one rename lands it; a failed upgrade leaves the existing binary untouched. `SKILLPORTER_INSTALL_DIR` sets the destination, `/usr/local/bin` when writable and `~/.local/bin` otherwise.

`SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM=1` accepts the same-origin checksum alone, which the project treats as trust on first use and does not recommend.

### GitHub artifact attestation

Default when the GitHub CLI is installed and signed in: the installer runs `gh attestation verify` against the release workflow.

```bash
gh auth status
SKILLPORTER_VERSION=v3.0.0 sh install.sh
```

The same check against the downloaded asset:

```bash
gh attestation verify skillporter.pyz --repo Shanmukh-l33t/skillporter
```

### A digest you pin

Best for Dockerfiles and CI, where the digest lives in your own repository.

```bash
SKILLPORTER_VERSION=v3.0.0 \
SKILLPORTER_SHA256=5468ffad0fe81af08a4499eaac1ed380d00c8d5dd4896dda46098651874a53c3 \
sh install.sh
```

That digest is `skillporter.pyz` from v3.0.0; replace it when you move to a later tag.

### A detached signature

`SKILLPORTER_PUBLIC_KEY_FILE` points at a PEM public key that verifies `SHA256SUMS.txt.sig`. This path is for mirrors and internal builds that sign their own checksum file; the official v3.0.0 release does not publish one, so use attestation or a pinned digest.

```bash
SKILLPORTER_VERSION=v3.0.0 SKILLPORTER_PUBLIC_KEY_FILE=/path/to/pub.pem sh install.sh
```

## Register it as an MCP server

`skillporter mcp` serves the workspace over stdio, so an agent can inspect skills through tool calls instead of shelling out. It is read-only unless you opt in to writes.

```bash
claude mcp add skillporter -- uvx skillporter mcp
```

```bash
codex mcp add skillporter -- uvx skillporter mcp
```

Clients without an `mcp add` command register `uvx skillporter mcp` in `mcpServers`.

Write tools stay disabled until you add `--allow-writes`. The workspace root is fixed at startup by `--root`, then `SKILLPORTER_MCP_ROOT`, then the working directory, and path arguments that leave it are rejected. [MCP integration](/docs/mcp) has the nine tools and the boundary rules.

## Upgrade and uninstall

Those words cover two things: the CLI, and the skills it manages.

Upgrade the CLI through the package manager that installed it:

```bash
uv tool upgrade skillporter
```

```bash
pipx upgrade skillporter
```

With the standalone installer, run it again with a newer tag and the same authenticity check; to remove that copy, delete the `skillporter` file from the install directory.

Move a skill to its recorded upstream version with `update`. It snapshots the current copy into `.skillporter/backups/` before replacing it, so `rollback` can undo the change.

```bash
skillporter update --dry-run
skillporter update
```

`uninstall` removes a skill from the harnesses you name. The `--harness` flag is required, and a shared `.agents/skills` copy is deleted only when its last owner goes.

```bash
skillporter uninstall pdf --harness cursor --dry-run
skillporter uninstall pdf --harness cursor
```

## Install into CI

Any pipeline can run the three checks that decide a skill change:

```bash
pipx install skillporter==3.0.0
skillporter validate .
skillporter scan . --max-risk-score 30
skillporter lock --check
```

Exit code `1` means a finding, `2` means the command could not run. The repository also ships a composite GitHub Action:

```yaml
- uses: actions/checkout@v4
- uses: Shanmukh-l33t/skillporter@v3.0.0
  with:
    command: validate
    lock-check: "true"
    max-risk-score: "30"
```

`command` accepts `validate`, `scan`, `diagnose`, `doctor`, `lock` or `audit`. Setting `upload-sarif: "true"` sends the SARIF report to code scanning and needs `security-events: write`; `pr-comment: "true"` posts the ci-report summary and needs `pull-requests: write`. [CI and GitHub Actions](/docs/ci) covers pinning both tag and digest.

## Troubleshooting a failed install

- `error: refusing to install unattested artifact`: no authenticity check was available. Sign in to `gh`, or pass `SKILLPORTER_SHA256`.
- `error: invalid SKILLPORTER_VERSION`: the value is not an immutable tag. Use something like `v3.0.0`, never `main` or `latest`.
- The npm launcher exits immediately: no Python 3.9+ interpreter and no `uvx` on `PATH`. Install Python 3.9 or newer, or use `uv`.
- `externally-managed-environment` from pip: install with `uv tool install` or `pipx install` instead of the system interpreter.

Problems after a good install are usually workspace problems. `skillporter doctor .` reports what it finds; `--json` gives the same output for a bug report. [Troubleshooting](/docs/troubleshooting) covers each message, and [Installation](/docs/installation) is the reference for every channel and variable.