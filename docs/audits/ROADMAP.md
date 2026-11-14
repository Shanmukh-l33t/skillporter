# Skillporter Product Roadmap

**ONE SKILL. EVERY AGENT.**

Skillporter is evolving across three generations while keeping the local CLI fast, zero-dependency, and open-source.

---

## Generation 1: Skillporter Manager (v1.x – v2.0, Current)

Focus: Local-first universal CLI, deterministic project configuration, supply-chain security scanning, and native agent integrations.

- [x] **v1.0**: Core `SKILL.md` frontmatter validator, 5-harness path registry, copy/symlink installer, and reachability matrix.
- [x] **v2.0 (Current Release)**:
  - **19-Harness Universal Adapter Architecture**: Evidence-backed adapters for Claude Code, OpenAI Codex, Cursor, GitHub Copilot, Gemini CLI, Google Antigravity, Windsurf, Cline, Roo Code, OpenCode, Zed, Replit Agent, JetBrains Junie, Hermes Agent, OpenClaw, OpenHands, Goose, Continue, and Aider.
  - **One-Command Remote & Local Installer (`skillporter add`)**: Install from `owner/repo`, GitHub subdirectories, branches/tags/commits, Git URLs, ZIP/tar archives, and local paths.
  - **Content-Drift & Duplicate Detection**: SHA-256 tree hashing across harness directories so copy-mode installs never silently diverge.
  - **Manifest (`skillporter.yaml`) & Deterministic Lockfile (`skillporter.lock`)**: Reproducible team environments via `skillporter init`, `skillporter lock`, and `skillporter sync`.
  - **Transactional Lifecycle & Rollback**: Ownership tracking (`.skillporter/state.json`), automatic backups before updates, `skillporter update`, and `skillporter rollback`.
  - **Static Security & Supply-Chain Scanner (`skillporter scan`)**: Inspects skills for hardcoded secrets, prompt injection, hidden Unicode, dangerous shell patterns, symlink escapes, and archive traversal before installation.
  - **Zero-Friction Distribution**: PyPI / `uvx skillporter`, `npx skillporter` wrapper, standalone single-file `.pyz` executable bundle, composite GitHub Action (`action.yml`), and native `skillporter mcp` server.

---

## Generation 2: Skillporter Ecosystem (v2.1 – v2.5, Planned)

Focus: Public skill discovery, immutable package publishing, and automated compatibility/security scorecards.

- [ ] **Public Registry API (FastAPI + PostgreSQL + S3/R2)**:
  - Hosted index backing `skillporter search`, `skillporter info`, and `skillporter add registry:publisher/skill@version`.
  - Immutable content-addressed release tarballs verified against `provenance.json` SHA-256 digests and GitHub OIDC attestations.
- [ ] **Automated Harness Verification Matrix**:
  - Scheduled CI runners executing headless discovery smoke tests against new releases of Claude Code, Codex, Gemini CLI, OpenCode, and Hermes.
- [ ] **Public Compatibility & Security Badges**:
  - Hosted SVG badge endpoints reflecting live CI validation and static scan verdicts.

---

## Generation 3: Skillporter Platform (v3.0+, Future)

Focus: Team synchronization, organization governance, and private registries.

- [ ] **Private & Self-Hosted Registries**: Internal skill catalogs for engineering organizations with custom `SKILLPORTER_REGISTRY_URL` authentication.
- [ ] **Organization Policy Engine**: Centralized allowlists, required security scan thresholds, and commit-pinning policies enforced in CI and developer workstations.
- [ ] **Cross-Repo Fleet Sync**: Automated pull requests when upstream organization skills release security or workflow updates.
