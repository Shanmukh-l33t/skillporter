# Harness Compatibility & Verification Audit (Skillporter 3.0)

_Last verified: 2026-11-14_

Skillporter enforces an evidence-backed verification model across all 19 supported AI coding and autonomous agent harnesses. Directory creation is never conflated with live runtime verification.

## 1. Four-Tier Verification Model

| Verification Level | Definition & Required Evidence |
|---|---|
| `RUNTIME_VERIFIED` | Skill installation and live discovery verified inside the actual running agent harness on the test host (`VERIFIED` in `doctor`). |
| `INTEGRATION_TESTED` | End-to-end multi-harness workflows (`add`, `sync`, `diagnose`, `doctor --fix`, drift, duplicate detection, shared-path deduplication, rollback) verified in automated integration suites plus vendor documentation. |
| `FIXTURE_TESTED` | Full adapter lifecycle (project & user path resolution, `SKILL.md` + `scripts/` + `references/` preservation, frontmatter/adapted format compatibility, conflict refusal, shared `.agents/skills/` safe removal) verified against automated fixtures in `tests/test_adapter_conformance.py` plus official vendor documentation. |
| `DOCUMENTATION_VERIFIED` | Discovery paths and precedence verified against official upstream vendor documentation without automated fixture execution. |

*(Declarative custom adapters loaded via `load_adapter_file()` default to `UNVERIFIED` / `UNIT_TESTED` unless independently validated.)*

## 2. Shared `.agents/skills/` Ownership Guarantee

Eight harnesses (`codex`, `cursor`, `gemini-cli`, `antigravity`, `zed`, `replit`, `openhands`, `goose`) use `.agents/skills` as their primary project directory, and six more (`github-copilot`, `cline`, `roo-code`, `opencode`, `junie`, `openclaw`) read `.agents/skills` as a documented compatibility path.

1. **Deduplicated Install**: `skillporter add <source> --harness all` writes `.agents/skills/<skill>` once and marks remaining shared targets `unchanged (shared path)`.
2. **Reference-Safe Removal**: `skillporter remove <skill> --harness cursor` removes any redundant `.cursor/skills/<skill>` copy while **preserving** `.agents/skills/<skill>` (`preserved-shared`) as long as any other managed harness (`codex`, `zed`, etc.) still owns it. `.agents/skills/<skill>` is deleted only when the last owning harness is removed.

## 3. Verified 19-Harness Compatibility Ledger

| Harness ID | Display Name | Support | Verification Level | Project Primary | User Primary | Shared `.agents/skills` |
|---|---|---|---|---|---|---|
| `hermes` | Hermes Agent | `NATIVE` | `RUNTIME_VERIFIED` | `.hermes/skills` | `$HERMES_HOME/skills` | No |
| `claude-code` | Claude Code | `NATIVE` | `INTEGRATION_TESTED` | `.claude/skills` | `~/.claude/skills` | No |
| `codex` | OpenAI Codex | `NATIVE` | `INTEGRATION_TESTED` | `.agents/skills` | `~/.agents/skills` | Yes (Primary) |
| `cursor` | Cursor | `NATIVE` | `INTEGRATION_TESTED` | `.agents/skills` | `~/.agents/skills` | Yes (Primary) |
| `github-copilot` | GitHub Copilot | `NATIVE` | `FIXTURE_TESTED` | `.github/skills` | `~/.copilot/skills` | Yes (Compat) |
| `gemini-cli` | Gemini CLI | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | Yes (Primary) |
| `antigravity` | Google Antigravity | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.gemini/config/skills` | Yes (Primary) |
| `windsurf` | Windsurf | `NATIVE` | `FIXTURE_TESTED` | `.windsurf/skills` | `~/.codeium/windsurf/skills` | No |
| `cline` | Cline | `NATIVE` | `FIXTURE_TESTED` | `.cline/skills` | `~/.cline/skills` | Yes (Compat) |
| `roo-code` | Roo Code | `NATIVE` | `FIXTURE_TESTED` | `.roo/skills` | `~/.roo/skills` | Yes (Compat) |
| `opencode` | OpenCode | `NATIVE` | `FIXTURE_TESTED` | `.opencode/skills` | `~/.config/opencode/skills` | Yes (Compat) |
| `zed` | Zed | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | Yes (Primary) |
| `replit` | Replit Agent | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.config/agents/skills` | Yes (Primary) |
| `junie` | JetBrains Junie | `NATIVE` | `FIXTURE_TESTED` | `.junie/skills` | `~/.junie/skills` | Yes (Compat) |
| `openclaw` | OpenClaw | `NATIVE` | `FIXTURE_TESTED` | `.openclaw/skills` | `~/.openclaw/skills` | Yes (Compat) |
| `openhands` | OpenHands | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | Yes (Primary) |
| `goose` | Goose | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | Yes (Primary) |
| `continue` | Continue | `COMPATIBLE` | `FIXTURE_TESTED` | `.continue/skills` | `~/.continue/skills` | No |
| `aider` | Aider / AiderDesk | `ADAPTED` | `FIXTURE_TESTED` | `.aider-desk/skills` | `~/.aider-desk/skills` | No |
