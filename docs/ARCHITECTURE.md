# Architecture

Three small layers, no dependencies.

```
cli.py        argument parsing, output formatting, exit codes
   |
   +-- diagnose.py   resolve harness paths -> scan -> reachability + findings
   +-- install.py    copy or symlink a skill into a harness directory
   +-- frontmatter.py  parse + validate SKILL.md against the spec
   |
   +-- harnesses.py  the path registry (single source of truth)
```

## Why the registry is data, not code

`harnesses.py` holds every path as a `SkillPath(path, scope)`. Nothing else in
the codebase knows where Claude Code or Codex look. Adding a harness is one
entry plus one assertion in `test_matrix_paths_match_published_docs` — which is
what keeps the matrix from silently drifting away from vendor docs.

## Diagnosis model

For a given root and harness:

1. Ask the registry which paths that harness reads at the requested scope.
2. Resolve each to an absolute path (`$HERMES_HOME` is profile-scoped and must
   never be hardcoded).
3. List skill directories there, recording broken symlinks separately.
4. Union the results into `reachable_skills`.

Findings are then derived by diffing discovered skills against reachable sets.
`scope="project"` deliberately ignores user-level paths so diagnosing a repo
describes the repo, not the operator's machine.

## Install model

Installs write to the harness's **primary** documented path only. Writing to
every compatibility path would duplicate skills in Cursor (which reads four
roots). Because Codex and Cursor share `.agents/skills`, a single run tracks
destinations already written and reports `unchanged` instead of failing.

`copy` is the default because symlinks do not survive Docker build contexts,
`git archive`, or cross-platform checkouts — the exact failures reported in the
upstream issues this tool was built from.

## Non-goals

- Editing skill content.
- Managing MCP servers or plugins.
- Replacing a package manager.
