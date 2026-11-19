# What should the first five minutes tell me?

Start with the developer who already has skills, not the developer shopping for another installer. The first useful question is: **what do I have here, and which copy needs my attention?** The second is: **what exactly will change if I fix it?**

## Observations from the original CLI

On Windows 11, from a clean editable installation at `bdfb9e6` (3.2.0), a temporary project contained only `.claude/skills/hello/SKILL.md` with a name, description, and no version. No manifest requested any other target. These are excerpts of actual CLI output:

```
$ skillporter status
Skills summary:     1 total (0 synced, 1 unmanaged, 0 needing attention)
...
hello  1.0.0    UNMANAGED  no       claude-code, cline, cursor, github-copilot (+2)
...
! skill 'hello' is not visible to: codex (visible to: claude-code, cline, cursor, github-copilot, opencode, replit)

$ skillporter list
hello  untracked  no       e2771b9e656d  claude-code, cline, cursor, github-copilot (+2)
```

The status header was `NEEDS ATTENTION`. No agent had been asked whether it loaded `hello`. There was no evidence for version `1.0.0` or for needing to install in Codex. `diagnose .` printed a wide harness matrix, and starting with no arguments printed the command catalog twice in different groupings. This is not a problem a new color scheme would solve.

## Independent signals (not interviews or adoption metrics)

- [Codex issue 52266](https://github.com/openai/codex/issues/52266): the reporter could read 15 repository skills from disk, but the managed cloud catalog returned no skills. Finding a file must not be presented as witnessing activation.
- [Skills CLI issue 691](https://github.com/vercel-labs/skills/issues/691): the reporter describes installed symlinks that the OpenClaw loader rejects. This is a reason to verify the receiving harness, not proof that Skillporter has the same bug.
- [Skills CLI issue 165](https://github.com/vercel-labs/skills/issues/165): a request for a project manifest, stable agent selection, and repeatable installs. The useful comparison is whether a second project reproduces the first, not which tool advertises more targets.

## Decisions and acceptance checks

| Decision | How to challenge it |
|---|---|
| Show actionable status first; keep full rows and automation available. Use the existing CLI, not a TUI. | Run against a small project and a mixed collection of thousands. Measure output volume **and** time to look up a particular skill. A short output that takes minutes to appear still fails. |
| Separate ownership, filesystem visibility, declared intent, and observed runtime loading. | Install an unversioned Claude-only skill. An unrequested missing Codex copy is not damage; an explicitly required missing one is. Load the skill from a real harness before claiming runtime integration. |
| Preview physical changes rather than just announcing a dry run. | On a disposable installation, compare preview paths with actual changes. Verify an unrelated file, shared owner and source survive, then rerun. |
| Use scan-local reuse, not a persistent cache of hashes. | Change an installed file without changing its name, start a new process, and confirm the next scan reports the edit. |
| Keep a headless path. | Exercise JSON output, exit codes and stdio MCP independently from human output. Do not hide real problems to make a demo return success. |

No product-market-fit claim follows from these observations. User retention, actual skill usage, and recommendation intent require separate evidence.
