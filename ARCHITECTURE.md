# Skillporter Architecture (v3.0)

Skillporter is a local-first, zero-runtime-dependency Python 3.9+ package manager, dependency resolver, and supply-chain security layer for AI agent skills, wrapped by thin CLI, `uvx`, `npx`, standalone `.pyz`, GitHub Action, and stdio MCP interfaces.

```
+-----------------------------------------------------------------------------------+
|                           USER & AGENT INTERFACES                                 |
|  CLI (`skillporter`)  |  NPX (`npx @shanmukhdheekonda/skillporter`)               |
|  GitHub Action        |  MCP (`skillporter mcp` - read-only default)              |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                  CLI DISPATCH (`cli.py` -> `skillporter/commands/`)               |
|   add.py | remove.py | sync.py | scan.py | audit.py | registry.py | doctor.py     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        SKILLPORTER CORE ENGINE (`skillporter/`)                   |
|                                                                                   |
|  +----------------------+  +----------------------+  +-------------------------+  |
|  | security.py +        |  | sources.py           |  | install.py + atomic.py  |  |
|  | scanner_analyzers.py |  | Git (--ref/SHA),     |  | Staged txn journal,     |  |
|  | Python AST, JS/TS,   |  | Zip/Tar (NFC, O_EXCL,|  | flock/msvcrt lock,      |  |
|  | Markdown, encoded,   |  | reserved names, bomb |  | shared .agents/skills   |  |
|  | cross-file & SARIF   |  | caps), local, reg    |  | ownership & rollback    |  |
|  +----------------------+  +----------------------+  +-------------------------+  |
|                                                                                   |
|  +----------------------+  +----------------------+  +-------------------------+  |
|  | manifest.py +        |  | state.py + audit.py  |  | diagnose.py +           |  |
|  | resolver.py          |  | .skillporter/state,  |  | harnesses.py +          |  |
|  | skillporter.yaml,    |  | SHA-256 backups,     |  | formats.py              |  |
|  | skillporter.lock v2, |  | secret-scrubbed      |  | 19 adapters, drift,     |  |
|  | semver & commit pins |  | audit.jsonl          |  | duplicates, adaptation  |  |
|  +----------------------+  +----------------------+  +-------------------------+  |
+-----------------------------------------------------------------------------------+
```

## 1. Core Architectural Invariants

1. **Single Zero-Dependency Core**: All business logic uses the Python 3.9+ standard library (`ast`, `argparse`, `base64`, `dataclasses`, `hashlib`, `json`, `pathlib`, `shutil`, `subprocess`, `tarfile`, `unicodedata`, `urllib`, `zipfile`).
2. **Command Dispatch Separated from Domain Logic**: `skillporter/cli.py` defines `argparse` schemas and dispatches into focused command handlers under `skillporter/commands/`, which call domain modules (`install.py`, `security.py`, `manifest.py`, `resolver.py`, `diagnose.py`).
3. **Crash-Safe Filesystem Transactions**:
   - State, manifest, lockfile, and journal writes use `atomic_write_text()` (`tempfile.mkstemp` in same directory + `fsync` + `os.replace`).
   - Workspace mutations serialize under re-entrant cross-process `workspace_lock()` (`fcntl.flock` on POSIX, byte-0 `msvcrt.locking` on Windows).
   - Multi-harness installs record pending `created` and `replaced` paths in `.skillporter/tmp/txn-<id>/journal.json` before moving directories; `recover_interrupted_transactions()` rolls back any uncommitted partial target after a `SIGKILL` crash.
4. **Defense-in-Depth Security Boundaries**:
   - Archive extraction validates normalized member paths, rejects special/reserved/colliding entries, and creates files with `O_CREAT | O_EXCL | O_NOFOLLOW`.
   - Conflict overrides (`--force`) never bypass security gates (`--allow-risky` / `accept_risk`), and structural escapes (`sec-symlink-escape`, `sec-path-traversal`) are never overridable.
   - `skillporter mcp` enforces workspace containment and denies write tools unless explicitly enabled.

## 2. Module Map

- `skillporter/cli.py` & `skillporter/commands/{common,add,remove,sync,scan,audit,registry,doctor}.py`: CLI UX, `--dry-run`, `--json` / `--format sarif`, exit codes, and `audit` reporting.
- `skillporter/security.py` & `skillporter/scanner_analyzers.py`: Deterministic 0–100 risk scoring, completeness tracking, Python AST / JS / Markdown / encoded-payload / cross-file static analyzers, SkillSpector integration, and SARIF 2.1.0 export.
- `skillporter/mcp_server.py`: Hardened JSON-RPC 2.0 stdio MCP server with read/write permission separation and strict runtime type validation.
- `skillporter/audit.py`: Secret-scrubbed `.skillporter/audit.jsonl` structured event recorder and reader.
- `skillporter/sources.py`: Hardened Git, GitHub shorthand/tree URL, ZIP/TAR archive, local, and registry source resolver.
- `skillporter/install.py`, `skillporter/state.py`, `skillporter/atomic.py`: Transactional planner/installer, shared-directory reference-aware `uninstall()`, backup snapshotting, crash recovery, and graph rollback.
- `skillporter/manifest.py` & `skillporter/resolver.py`: `skillporter.yaml` parser, `skillporter.lock` v2 validator (`LockfileError`), commit/hash reproducibility checks, and topological semver dependency resolver.
- `skillporter/harnesses.py`, `skillporter/diagnose.py`, `skillporter/formats.py`, `skillporter/frontmatter.py`: 19-harness adapter catalog, independent harness detection, declarative JSON adapter SDK, Agent Skills spec validator, drift/duplicate detector, and rule file exporter.
- `skillporter/instructions.py`, `skillporter/suggest.py`, `skillporter/insights.py`: Multi-agent instruction file discovery, overlap/conflict/outdated analysis, safe canonical consolidation with bidirectional manual-edit reconciliation, active harness context inspection, local-first stack skill recommendations, and context token cost insights.
- `skillporter/capabilities.py`, `skillporter/policy.py`, `skillporter/update_review.py`, `skillporter/authoring.py`, `skillporter/ai_review.py`: Declared vs. inferred capability model, `skillporter.policy.yaml` enforcement engine, human-readable `update --check` diffing, skill scaffolding/linting/preview/`skill.test.yaml` activation testing, and opt-in advisory LLM security review.
