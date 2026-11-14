# Installation

Every distribution channel runs the same Python core. Pick the one that fits how you already manage tools.

| Channel | Command | Needs |
|---|---|---|
| Run once | `uvx skillporter diagnose .` | `uv` |
| Run once | `npx @shanmukhdheekonda/skillporter diagnose .` | Node 16+, Python 3.9+ |
| Install | `uv tool install skillporter` | `uv` |
| Install | `pipx install skillporter` | `pipx` |
| Install | Standalone release installer | `sh`, `python3`, `curl` or `wget` |

Python 3.9 or newer is required in every case. The package has no runtime dependencies.

Every install channel, including the checks that verify the standalone download, is on the [install page](https://www.skillporter.dev/install).

## Run without installing

```bash
uvx skillporter diagnose .
```

```bash
npx @shanmukhdheekonda/skillporter diagnose .
```

The npm package is a thin launcher around the same Python zipapp. It still needs `python3` on `PATH`.

## Install from PyPI

```bash
uv tool install skillporter
```

```bash
pipx install skillporter
```

Both install into an isolated environment, which keeps you clear of the externally managed environment errors that system `pip` raises on current Linux distributions.

Confirm the version:

```bash
skillporter --version
```

## Standalone release installer

The installer is for Linux and macOS. On Windows, use `uv`, `pipx` or `npx`.

Download the installer from the immutable release tag, then run it:

```bash
curl -fsSL https://github.com/Shanmukh-l33t/skillporter/releases/download/v3.1.0/install.sh -o install.sh
SKILLPORTER_VERSION=v3.1.0 sh install.sh
```

The installer is deliberately not a `curl | sh` one-liner. Downloading it to a file lets you read it before it runs.

### What the installer verifies

1. **Immutable tag.** `SKILLPORTER_VERSION` must look like `v3.1.0`. Branch names such as `main` and aliases such as `latest` are rejected.
2. **Checksum.** The downloaded `skillporter.pyz` must match `SHA256SUMS.txt` from the same release.
3. **Authenticity.** A checksum fetched from the same place as the file only detects corruption. It does not prove who published it. The installer therefore refuses to continue until one independent check passes.
4. **Archive structure.** The download must be a valid Python zipapp. The payload is not executed during this check.
5. **Atomic placement.** The file is staged inside the destination directory and moved into place with one rename, so a failed upgrade leaves the existing binary untouched.

### Authenticity options

Choose one. Without any of them the installer exits with an error and writes nothing.

**GitHub artifact attestation (default).** If the GitHub CLI is installed and authenticated, the installer runs `gh attestation verify` against the release workflow.

```bash
gh auth status
SKILLPORTER_VERSION=v3.1.0 sh install.sh
```

Prerequisite: `gh` on `PATH` and signed in.

**Pinned SHA-256.** Supply the expected digest yourself. This is the right choice for Dockerfiles and CI, where the digest lives in your own repository.

```bash
SKILLPORTER_VERSION=v3.1.0 \
SKILLPORTER_SHA256=8bd7125b8f2a1a4f7c475406c71eaaec317bc4d7a0dd5d19e857301ef127179c \
sh install.sh
```

The digest above is `skillporter.pyz` from the v3.1.0 release. You can confirm it independently:

```bash
gh attestation verify skillporter.pyz --repo Shanmukh-l33t/skillporter
```

**Detached signature.** The installer can verify `SHA256SUMS.txt.sig` with an OpenSSL public key:

```bash
SKILLPORTER_VERSION=v3.1.0 SKILLPORTER_PUBLIC_KEY_FILE=/path/to/pub.pem sh install.sh
```

This path is for mirrors and internal builds that sign their own checksum file with `scripts/build_standalone.py --sign-key`. The official v3.1.0 GitHub release does not publish a signature file, so use attestation or a pinned digest for it.

### Installer environment variables

| Variable | Purpose |
|---|---|
| `SKILLPORTER_VERSION` | Release tag to install. Must be an immutable tag. |
| `SKILLPORTER_INSTALL_DIR` | Destination directory. Defaults to `/usr/local/bin` when writable, otherwise `~/.local/bin`. |
| `SKILLPORTER_SHA256` | Expected SHA-256 of `skillporter.pyz`. |
| `SKILLPORTER_PUBLIC_KEY_FILE` | PEM public key used to verify `SHA256SUMS.txt.sig`. |
| `SKILLPORTER_RELEASE_BASE_URL` | Alternative release host, for mirrors. |
| `SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM` | Set to `1` to accept the same-origin checksum alone. This trusts the download host on first use and is not recommended. |

## Run the zipapp directly

Each release also ships `skillporter.pyz`, a single-file Python zipapp:

```bash
python3 skillporter.pyz --version
```

## Build from source

```bash
git clone https://github.com/Shanmukh-l33t/skillporter
cd skillporter
python3 scripts/build_standalone.py
./dist/skillporter.pyz --version
```

## Upgrade and remove

```bash
uv tool upgrade skillporter
pipx upgrade skillporter
```

```bash
uv tool uninstall skillporter
pipx uninstall skillporter
```

For the standalone installer, run it again with a newer `SKILLPORTER_VERSION` to upgrade, or delete the `skillporter` file from the install directory to remove it.

## Next

[Getting started](../getting-started/README.md) walks through the first commands. [MCP integration](../mcp/README.md) covers running Skillporter as a tool server inside a harness. Questions about channels, platforms and upgrades are answered in the [FAQ](https://www.skillporter.dev/faq).
