# Harness runtime evidence, 2026-11-14

Captured by an independent audit pass against real agent binaries installed into a scratch prefix, with a temporary HOME
and a probe skill named `audit-probe-skill` installed by `skillporter add` in project and user scope. No model was
invoked (no API credentials), so this shows that each harness discovered or received the skill, not that a model used it.

| Harness | Binary and version | How discovery was observed |
|---|---|---|
| claude-code | claude 2.1.325 | `stream-json` init event lists the skill |
| codex | codex-cli 0.169.0 | `debug prompt-input` model-visible input lists the skill |
| github-copilot | copilot 1.0.112 | `copilot skill list` shows project and personal skill |
| gemini-cli | gemini 0.68.0 | `gemini skills list` shows it enabled; project scope needs a trusted folder |
| opencode | opencode 2.2.4 | server `skill.list` API returns the skill |
| cline | cline 3.0.74 | the binary's own request payload contains the skill |
| continue | cn 1.5.47 | the binary's request payload lists the skill in `read_skill` |

Not runtime verified: cursor (`cursor-agent` has no skill listing; fixture level only), windsurf (IDE not installed),
aider (core aider has no skills; `CONVENTIONS.md` is only loaded with `--read`), and the 9 other adapters.
Files here are excerpts; large payloads were trimmed to the lines around the match.
