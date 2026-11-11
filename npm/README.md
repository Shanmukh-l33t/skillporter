# skillporter (NPX Wrapper)

**ONE SKILL. EVERY AGENT.**

This npm package provides the zero-install `npx skillporter` CLI launcher for the [Skillporter](https://github.com/Shanmukh-l33t/skillporter) universal Agent Skill package manager.

## Usage

```bash
# Diagnose skill reachability and SHA-256 drift across harnesses
npx skillporter diagnose .

# Install a skill from GitHub across all detected harnesses
npx skillporter add owner/repository --harness all

# Static security & supply-chain scan
npx skillporter scan .

# Synchronize skills from skillporter.yaml
npx skillporter sync
```

## Architecture

`npx skillporter` is a thin Node.js launcher that invokes the bundled, zero-dependency `skillporter.pyz` Python core (or delegates to `uvx skillporter`), ensuring 100% identical behavior across `npx`, `uvx`, `pipx`, and standalone binaries.
