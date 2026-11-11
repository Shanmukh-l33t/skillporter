# Troubleshooting

## A skill shows `MISSING` for a harness
Run `skillporter matrix` or `skillporter info <harness>` to inspect the exact project and user paths that harness scans. Run `skillporter sync` or `skillporter doctor --fix` to mirror the skill across active harnesses.

## A skill shows `DRIFT` in `skillporter diagnose`
You modified one copy of the skill (for example in `.claude/skills/<name>`) without updating another copy (`.agents/skills/<name>`). Run `skillporter sync` to reconcile all copies to match, then verify with `skillporter diagnose .`.

## A skill shows `DUPLICATE` in Cursor
The skill exists in two directories that Cursor scans simultaneously (such as `.agents/skills/<name>` and `.cursor/skills/<name>`). Remove the redundant `.cursor/skills/<name>` copy (`rm -rf .cursor/skills/<name>`) and keep `.agents/skills/<name>`, which satisfies both Codex and Cursor with a single folder.

## Installation blocked by static security policy
`skillporter add` runs `skillporter scan` before writing files. If `HIGH` or `CRITICAL` issues are found, run `skillporter scan <path>` to inspect the exact file and line number. Only pass `--allow-risky` if you have manually verified the finding is benign.
