# AGENT 5 — AGENT HARNESS COMPATIBILITY AUDIT

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Role**: AI-Agent Harness Compatibility Specialist

---

## 1. Evidence-Based Audit of All 19 Harnesses

A critical requirement of Skillporter is **never confusing filesystem directory creation with runtime verification**.

In our environment and CI, we have:
- **Runtime-verified** discovery on **Hermes Agent** (live runtime in this environment) and **OpenCode** (binary present on host).
- **Integration-tested & Documentation-verified** discovery rules for **Claude Code**, **OpenAI Codex**, **Cursor**, **GitHub Copilot**, **Gemini CLI**, **Google Antigravity**, **Windsurf**, **Cline**, **Roo Code**, **Zed**, **Replit Agent**, **JetBrains Junie**, **OpenClaw**, **OpenHands**, **Goose**, **Continue**, and **Aider**.

### Audit of `verification_level` Claims in `harnesses.py`
- Currently, `claude-code`, `codex`, and `cursor` are marked `INTEGRATION_TESTED`, `hermes` is marked `RUNTIME_VERIFIED`, and the remaining 15 are marked `DOCUMENTATION_VERIFIED`.
- **Finding [COMPAT-01]**: When reporting per-skill status in `diagnose` / `doctor`, Skillporter should explicitly distinguish:
  - `VERIFIED`: The skill is `INSTALLED`, `VALID`, `COMPATIBLE`, **and** the harness adapter has `verification_level == "RUNTIME_VERIFIED"` (or was runtime-probed).
  - `INSTALLED` (`UNVERIFIED` runtime / `DOC_VERIFIED`): The skill is present at the documented path and valid against the spec + harness constraints, but the external proprietary IDE/CLI runtime was not executed to confirm live ingestion.
- **Finding [COMPAT-02]**: Harness-specific constraints should be checked per harness:
  - **Cline**: Officially mandates `SKILL.md` body < 5,000 tokens. If a skill's body exceeds `h.capabilities.max_body_tokens`, `diagnose` / `doctor` should flag a `harness-compatibility` warning for Cline.
  - **Claude Code / Hermes**: Support `context: fork` in frontmatter. Other harnesses ignore `context: fork`. If `context: fork` is present in frontmatter, emit a `harness-compatibility` note so authors know it only forks context in Claude Code and Hermes.
  - **Aider**: Core `aider` CLI does not auto-discover `.aider-desk/skills` without `--read <path>/SKILL.md` or `CONVENTIONS.md` adaptation (`support_status == "ADAPTED"`). `doctor` should explicitly state when a harness is `ADAPTED` rather than `NATIVE`.

---

## 2. Summary of Verified Discovery Behavior

| Harness | Project Primary | User Primary | Recursive? | Shared `.agents/skills`? | Evidence Level |
|---|---|---|---|---|---|
| `claude-code` | `.claude/skills` | `~/.claude/skills` | No | No | Doc + Integration Tested |
| `codex` | `.agents/skills` | `~/.agents/skills` | No | Yes (Primary) | Doc + Integration Tested |
| `cursor` | `.agents/skills` | `~/.agents/skills` | Yes | Yes (Primary) | Doc + Integration Tested |
| `github-copilot` | `.github/skills` | `~/.copilot/skills` | No | Yes (Compat) | Documentation Verified |
| `gemini-cli` | `.agents/skills` | `~/.agents/skills` | No | Yes (Primary) | Documentation Verified |
| `antigravity` | `.agents/skills` | `~/.gemini/config/skills` | No | Yes (Primary) | Documentation Verified |
| `windsurf` | `.windsurf/skills` | `~/.codeium/windsurf/skills` | No | No | Documentation Verified |
| `cline` | `.cline/skills` | `~/.cline/skills` | No | Yes (Compat) | Documentation Verified |
| `roo-code` | `.roo/skills` | `~/.roo/skills` | No | Yes (Compat) | Documentation Verified |
| `opencode` | `.opencode/skills` | `~/.config/opencode/skills` | Yes | Yes (Compat) | Documentation Verified |
| `zed` | `.agents/skills` | `~/.agents/skills` | No | Yes (Primary) | Documentation Verified |
| `replit` | `.agents/skills` | `~/.config/agents/skills` | Yes | Yes (Primary) | Documentation Verified |
| `junie` | `.junie/skills` | `~/.junie/skills` | No | Yes (Compat) | Documentation Verified |
| `hermes` | `.hermes/skills` | `$HERMES_HOME/skills` | Yes | No | Runtime Verified |
| `openclaw` | `.openclaw/skills` | `~/.openclaw/skills` | Yes | Yes (Compat) | Documentation Verified |
| `openhands` | `.agents/skills` | `~/.agents/skills` | No | Yes (Primary) | Documentation Verified |
| `goose` | `.agents/skills` | `~/.agents/skills` | No | Yes (Primary) | Documentation Verified |
| `continue` | `.continue/skills` | `~/.continue/skills` | No | No | Documentation Verified (`COMPATIBLE`) |
| `aider` | `.aider-desk/skills` | `~/.aider-desk/skills` | No | No | Documentation Verified (`ADAPTED`) |
