# Installation & Distribution Channels

Skillporter is designed so you never need to manually manage virtualenvs just to install or audit agent skills. All distribution channels execute the single authoritative Python core.

## 1. Zero-Install Runners (`uvx` and `npx`)

```bash
uvx skillporter diagnose .
npx skillporter diagnose .
```

## 2. Global CLI Installation

```bash
# via uv
uv tool install skillporter

# via pipx
pipx install skillporter

# via pip
pip install skillporter
```

## 3. Standalone Single-File Zipapp & Executables

Build or download the zero-dependency standalone executable (`skillporter.pyz`):

```bash
python3 scripts/build_standalone.py
./dist/skillporter.pyz --version
```

Artifacts produced in `dist/`:
- `skillporter.pyz` (universal Python 3.9+ zipapp)
- `skillporter-linux-x64`, `skillporter-linux-arm64`
- `skillporter-macos-arm64`, `skillporter-macos-x64`
- `skillporter-windows-x64.cmd`
- `SHA256SUMS.txt`

## 4. Native AI Harness Integration (MCP Server)

Skillporter includes a built-in, zero-dependency stdio JSON-RPC 2.0 Model Context Protocol (MCP) server (`skillporter mcp`):

```bash
# Claude Code
claude mcp add skillporter -- uvx skillporter mcp

# OpenAI Codex
codex mcp add skillporter -- uvx skillporter mcp
```

For Cursor, Windsurf, Cline, or Hermes, merge [`integrations/mcp/mcp.json`](../../integrations/mcp/mcp.json) into your MCP settings.

## 5. Claude Code Plugin & Slash Command

This repository ships `.claude-plugin/plugin.json` and `.claude/commands/skillporter.md`, enabling `/skillporter` inside Claude Code workspaces.
