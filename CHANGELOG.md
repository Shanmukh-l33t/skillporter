# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-10

### Added
- `diagnose` — skill × harness reachability matrix with actionable findings
  (missing install, broken symlink, spec violations). Exits 1 on findings.
- `install` — copy (Docker/CI-safe) and symlink strategies, project and user
  scope, `--force` with safety refusals.
- `uninstall` — removes installs without touching the source skill.
- `validate` — full Agent Skills specification checks (name charset, length,
  directory match, description budget and trigger wording, metadata typing,
  body size).
- `matrix` — harness path registry with `verified` vs `expected` status.
- Harness registry for Claude Code, OpenAI Codex, Cursor, Hermes Agent and
  OpenClaw, sourced from each project's published documentation.
- Shared-path handling: installing for Codex and Cursor writes to
  `.agents/skills` once instead of duplicating.
- 36 tests covering parsing, validation, diagnosis, install/uninstall, CLI
  exit codes, and the real-world failure modes (broken symlinks, worktree
  layouts, user/project scope isolation).
- GitHub Actions CI: tests on 3.9–3.13, ruff, gitleaks, skill validation.
