# Supported Harnesses & Evidence Directory

_Verified: 2026-11-11_

Skillporter classifies every harness with an explicit **Support Status** (`NATIVE`, `COMPATIBLE`, `ADAPTED`, `PARTIAL`, `UNSUPPORTED`, `UNVERIFIED`) and **Verification Level** (`RUNTIME_VERIFIED`, `INTEGRATION_TESTED`, `DOCUMENTATION_VERIFIED`, `UNIT_TESTED`, `UNVERIFIED`).

## Full 19-Harness Matrix

| ID | Display Name | Category | Support | Verification | Primary Project Path | Primary User Path | Official Docs |
|---|---|---|---|---|---|---|---|
| `claude-code` | Claude Code | coding | `NATIVE` | `INTEGRATION_TESTED` | `.claude/skills` | `~/.claude/skills` | [Docs](https://code.claude.com/docs/en/skills) |
| `codex` | OpenAI Codex | coding | `NATIVE` | `INTEGRATION_TESTED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://developers.openai.com/codex/skills) |
| `cursor` | Cursor | coding | `NATIVE` | `INTEGRATION_TESTED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://cursor.com/docs/context/skills) |
| `github-copilot` | GitHub Copilot | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.github/skills` | `~/.copilot/skills` | [Docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) |
| `gemini-cli` | Gemini CLI | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://geminicli.com/docs/cli/skills/) |
| `antigravity` | Google Antigravity | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.agents/skills` | `~/.gemini/config/skills` | [Docs](https://antigravity.google/docs/skills) |
| `windsurf` | Windsurf | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.windsurf/skills` | `~/.codeium/windsurf/skills` | [Docs](https://docs.windsurf.com/windsurf/cascade/skills) |
| `cline` | Cline | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.cline/skills` | `~/.cline/skills` | [Docs](https://docs.cline.bot/customization/skills) |
| `roo-code` | Roo Code | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.roo/skills` | `~/.roo/skills` | [Docs](https://roocodeinc.github.io/Roo-Code/features/skills/) |
| `opencode` | OpenCode | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.opencode/skills` | `~/.config/opencode/skills` | [Docs](https://opencode.ai/docs/skills) |
| `zed` | Zed | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://zed.dev/docs/ai/skills) |
| `replit` | Replit Agent | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.agents/skills` | `~/.config/agents/skills` | [Docs](https://docs.replit.com/features/agent/skills) |
| `junie` | JetBrains Junie | coding | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.junie/skills` | `~/.junie/skills` | [Docs](https://junie.jetbrains.com/docs/agent-skills.html) |
| `hermes` | Hermes Agent | autonomous | `NATIVE` | `RUNTIME_VERIFIED` | `.hermes/skills` | `$HERMES_HOME/skills` | [Docs](https://hermes-agent.nousresearch.com/docs) |
| `openclaw` | OpenClaw | autonomous | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.openclaw/skills` | `~/.openclaw/skills` | [Docs](https://docs.openclaw.ai/tools/skills) |
| `openhands` | OpenHands | autonomous | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://docs.openhands.dev/overview/skills) |
| `goose` | Goose | autonomous | `NATIVE` | `DOCUMENTATION_VERIFIED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://block.github.io/goose/docs/guides/context-engineering/using-skills/) |
| `continue` | Continue | coding | `COMPATIBLE` | `DOCUMENTATION_VERIFIED` | `.continue/skills` | `~/.continue/skills` | [Docs](https://docs.continue.dev/customize/deep-dives/rules) |
| `aider` | Aider / AiderDesk | coding | `ADAPTED` | `DOCUMENTATION_VERIFIED` | `.aider-desk/skills` | `~/.aider-desk/skills` | [Docs](https://aider.chat/docs/usage/conventions.html) |

## Shared `.agents/skills` Deduplication

Notice that **Codex, Cursor, Gemini CLI, Antigravity, Zed, Replit, OpenHands, and Goose** all use `.agents/skills` as their primary project path (and **GitHub Copilot, Cline, Roo Code, OpenCode, Junie, and OpenClaw** read `.agents/skills` as a documented compatibility path).

When you run `skillporter add <source> --harness all`, Skillporter writes `.agents/skills/<name>` **once** and marks the remaining shared targets as `unchanged (shared path)`, preventing duplicate writes and duplicate skill loading.
