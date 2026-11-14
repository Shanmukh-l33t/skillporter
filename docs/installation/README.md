# Installation & Distribution Channels

Skillporter executes a single zero-runtime-dependency Python 3.9+ core across every distribution channel.

## 1. Zero-Install Runners (`uvx` and `npx`)

```bash
# Run directly from PyPI via uvx
uvx skillporter diagnose .

# Run via npx from npm
npx @shanmukhdheekonda/skillporter diagnose .
```

## 2. Global CLI Installation (PEP 668 Safe)

```bash
# Recommended: uv tool or pipx from PyPI
uv tool install skillporter
pipx install skillporter
```

## 3. Hardened Standalone Installer (`install.sh`, Linux & macOS)

`install.sh` downloads immutable release tags (`skillporter.pyz` + `SHA256SUMS.txt`), never falls back to mutable `main`, and fails closed unless authenticity/provenance is verified:

```bash
# Download the release installer for a specific immutable tag
curl -fsSL https://github.com/Shanmukh-l33t/skillporter/releases/download/v3.0.0/install.sh -o install.sh

# Option A (Preferred): Verify Sigstore OIDC provenance via GitHub CLI (`gh attestation verify`)
SKILLPORTER_VERSION=v3.0.0 sh install.sh

# Option B: Pin expected SHA-256 digest out-of-band (CI / Dockerfiles)
SKILLPORTER_VERSION=v3.0.0 SKILLPORTER_SHA256=<64-hex-sha256> sh install.sh

# Option C: Verify detached OpenSSL signature against a release public key
SKILLPORTER_VERSION=v3.0.0 SKILLPORTER_PUBLIC_KEY_FILE=/path/to/pub.pem sh install.sh
```

> **Trust Model Limitation**: Downloading `SHA256SUMS.txt` from the same HTTPS endpoint as `skillporter.pyz` detects accidental corruption, not a compromised release bucket. `install.sh` therefore refuses unattested installs unless one of Options A/B/C succeeds (or the operator explicitly sets `SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM=1`).

## 4. Building Standalone Executables Locally

```bash
python3 scripts/build_standalone.py
./dist/skillporter.pyz --version
```

Artifacts produced in `dist/`:
- `skillporter.pyz` (universal Python 3.9+ zipapp)
- `skillporter-linux-x64`, `skillporter-linux-arm64`
- `skillporter-macos-arm64`, `skillporter-macos-x64`
- `skillporter-windows-x64.cmd`
- `SHA256SUMS.txt` (and `SHA256SUMS.txt.sig` when `--sign-key <pem>` is passed)

## 5. Native AI Harness Integration (MCP Server)

`skillporter mcp` runs in **read-only mode by default** (exposing `detect`, `diagnose`, `scan`, `inspect`, `matrix` within the workspace root):

```bash
# Read-only MCP server (default, recommended)
claude mcp add skillporter -- uvx skillporter mcp
codex mcp add skillporter -- uvx skillporter mcp

# Explicitly opt in to workspace write tools (add, install, sync, remove)
claude mcp add skillporter -- uvx skillporter mcp --allow-writes
```
