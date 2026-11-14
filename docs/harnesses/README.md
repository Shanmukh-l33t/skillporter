# Harness compatibility

Skillporter ships adapters for 19 AI agent harnesses. Each adapter records the exact directories that harness reads, how it supports the Agent Skills format, and what evidence backs the claim.

Two questions are kept separate on purpose:

- **Support type** describes how the harness consumes a skill.
- **Verification tier** describes how the adapter was tested.

A harness can support skills natively and still only be fixture tested. Skillporter never marks an adapter as runtime verified because a directory was created.

## What runtime verified means here

Eight adapters are `RUNTIME_VERIFIED`: Claude Code, OpenAI Codex, GitHub Copilot, Gemini CLI, OpenCode, Cline, Continue and Hermes Agent. For all but Hermes, an installed skill was observed in the harness's own output on 2026-11-14, in both project and user scope, using the real binary:

| Harness | What was observed |
|---|---|
| Claude Code 2.1.325 | the init event lists the skill |
| OpenAI Codex 0.169.0 | the rendered model input lists the skill |
| GitHub Copilot 1.0.112 | `skill list` shows a project and a personal skill |
| Gemini CLI 0.68.0 | `skills list` shows it enabled; project scope needs a trusted folder |
| OpenCode 2.2.4 | the server's skill list API returns it |
| Cline 3.0.74 and Continue 1.5.47 | the binary's own request payload contains the skill |

No model was called, because no credentials were available. This shows that the harness discovered the skill, not that a model used it well. Captured output is in the [evidence folder](https://github.com/Shanmukh-l33t/skillporter/tree/main/docs/audits/harness-runtime-evidence-2026-11-14).

Cursor stays `FIXTURE_TESTED`: its CLI cannot list skills, so no live load was seen. Windsurf is documentation and fixture only, because the IDE was not installed. Aider is listed for AiderDesk skill folders. Core aider has no skills concept and does not load `CONVENTIONS.md` without `--read`.

## Support types

| Support type | Meaning |
|---|---|
| `NATIVE` | The harness reads the Agent Skills format (`SKILL.md`) directly. |
| `COMPATIBLE` | The harness reads `SKILL.md` through a documented compatibility path. |
| `ADAPTED` | The harness needs a controlled conversion, such as a rules or conventions file. |

The registry also defines `PARTIAL`, `UNSUPPORTED` and `UNVERIFIED` for custom adapters. No built-in adapter uses them.

## Verification tiers

| Tier | Evidence required |
|---|---|
| `RUNTIME_VERIFIED` | Installation and live discovery verified inside the running harness on a test host. |
| `INTEGRATION_TESTED` | End-to-end multi-harness workflows (`add`, `sync`, `diagnose`, `doctor --fix`, drift, duplicates, shared-path deduplication, rollback) verified in automated integration suites, plus vendor documentation. |
| `FIXTURE_TESTED` | The full adapter lifecycle verified against automated fixtures in `tests/test_adapter_conformance.py`, plus official vendor documentation. |
| `DOCUMENTATION_VERIFIED` | Discovery paths and precedence confirmed against vendor documentation, without automated fixture execution. |

Custom adapters loaded with `load_adapter_file()` default to `UNVERIFIED` until you validate them yourself.

## The 19 adapters

This table is generated from `skillporter/harnesses.py`, the same registry the CLI uses. Do not edit it by hand. Run `python3 website/scripts/generate_site_data.py` after changing the registry.

<!-- BEGIN GENERATED: harness-matrix (website/scripts/generate_site_data.py) -->

| ID | Harness | Category | Support | Verification | Project path | User path | Vendor docs |
|---|---|---|---|---|---|---|---|
| `claude-code` | Claude Code | coding | `NATIVE` | `RUNTIME_VERIFIED` | `.claude/skills` | `~/.claude/skills` | [Docs](https://code.claude.com/docs/en/skills) |
| `codex` | OpenAI Codex | coding | `NATIVE` | `RUNTIME_VERIFIED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://developers.openai.com/codex/skills) |
| `github-copilot` | GitHub Copilot | coding | `NATIVE` | `RUNTIME_VERIFIED` | `.github/skills` | `~/.copilot/skills` | [Docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) |
| `gemini-cli` | Gemini CLI | coding | `NATIVE` | `RUNTIME_VERIFIED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://geminicli.com/docs/cli/skills/) |
| `cline` | Cline | coding | `NATIVE` | `RUNTIME_VERIFIED` | `.cline/skills` | `~/.cline/skills` | [Docs](https://docs.cline.bot/customization/skills) |
| `opencode` | OpenCode | coding | `NATIVE` | `RUNTIME_VERIFIED` | `.opencode/skills` | `~/.config/opencode/skills` | [Docs](https://opencode.ai/docs/skills) |
| `hermes` | Hermes Agent | autonomous | `NATIVE` | `RUNTIME_VERIFIED` | `.hermes/skills` | `$HERMES_HOME/skills` | [Docs](https://hermes-agent.nousresearch.com/docs) |
| `continue` | Continue | coding | `COMPATIBLE` | `RUNTIME_VERIFIED` | `.continue/skills` | `~/.continue/skills` | [Docs](https://docs.continue.dev/customize/deep-dives/rules) |
| `cursor` | Cursor | coding | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://cursor.com/docs/context/skills) |
| `antigravity` | Google Antigravity | coding | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.gemini/config/skills` | [Docs](https://antigravity.google/docs/skills) |
| `windsurf` | Windsurf | coding | `NATIVE` | `FIXTURE_TESTED` | `.windsurf/skills` | `~/.codeium/windsurf/skills` | [Docs](https://docs.windsurf.com/windsurf/cascade/skills) |
| `roo-code` | Roo Code | coding | `NATIVE` | `FIXTURE_TESTED` | `.roo/skills` | `~/.roo/skills` | [Docs](https://roocodeinc.github.io/Roo-Code/features/skills/) |
| `zed` | Zed | coding | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://zed.dev/docs/ai/skills) |
| `replit` | Replit Agent | coding | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.config/agents/skills` | [Docs](https://docs.replit.com/features/agent/skills) |
| `junie` | JetBrains Junie / AI Assistant | coding | `NATIVE` | `FIXTURE_TESTED` | `.junie/skills` | `~/.junie/skills` | [Docs](https://junie.jetbrains.com/docs/agent-skills.html) |
| `openclaw` | OpenClaw | autonomous | `NATIVE` | `FIXTURE_TESTED` | `.openclaw/skills` | `~/.openclaw/skills` | [Docs](https://docs.openclaw.ai/tools/skills) |
| `openhands` | OpenHands | autonomous | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://docs.openhands.dev/overview/skills) |
| `goose` | Goose | autonomous | `NATIVE` | `FIXTURE_TESTED` | `.agents/skills` | `~/.agents/skills` | [Docs](https://block.github.io/goose/docs/guides/context-engineering/using-skills/) |
| `aider` | Aider / AiderDesk | coding | `ADAPTED` | `FIXTURE_TESTED` | `.aider-desk/skills` | `~/.aider-desk/skills` | [Docs](https://aider.chat/docs/usage/conventions.html) |

19 adapters: 8 `RUNTIME_VERIFIED`, 11 `FIXTURE_TESTED`.

<!-- END GENERATED: harness-matrix -->

Print the same matrix locally:

```bash
skillporter matrix
skillporter matrix --category autonomous
skillporter matrix --json
```

Inspect one adapter, including every compatibility path and known limitation:

```bash
skillporter info cursor
```

## The shared `.agents/skills` directory

Eight harnesses use `.agents/skills` as their primary project directory: Codex, Cursor, Gemini CLI, Antigravity, Zed, Replit Agent, OpenHands and Goose. Six more read it as a documented compatibility path: GitHub Copilot, Cline, Roo Code, OpenCode, Junie and OpenClaw.

Skillporter treats that directory as shared property.

- **One write.** `skillporter add <source> --harness all` writes `.agents/skills/<skill>` once and reports the other owners as sharing the path.
- **Safe removal.** `skillporter remove <skill> --harness cursor` removes any Cursor-only copy but keeps `.agents/skills/<skill>` while another managed harness still owns it. The shared copy is deleted only when its last owner is removed.
- **No double loading.** Installing the same skill into `.agents/skills` and `.cursor/skills` makes Cursor list it twice. `skillporter diagnose` reports that as `DUPLICATE`.

## Harness differences that matter

Harnesses do not behave identically, and Skillporter does not pretend they do. A few examples from the registry:

- Claude Code reads `.claude/skills` only. A skill that exists only in `.agents/skills` is invisible to it.
- Codex and Zed read `.agents/skills` only.
- Gemini CLI requires the project folder to be trusted before it loads workspace skills.
- Cline expects the `SKILL.md` body to stay under 5,000 tokens.
- Core Aider does not discover skill folders on its own. It needs `aider --read <skill>/SKILL.md` or an adapted `CONVENTIONS.md`.

`skillporter info <harness>` prints the notes and limitations for any adapter.

## Detecting what you have installed

```bash
skillporter detect .
skillporter detect . --all --versions
```

Detection is read-only. It looks for known binaries, user directories, project markers and environment variables.

## Adding your own harness

See [Custom adapters](../adapters/README.md) for the declarative JSON format and the Python registration API.
