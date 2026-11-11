# Community Skill Registry Specification (Phase 1 — Client Contract v1.0.0)

**Status:** Stable Client Contract (`v1.0.0`, shipped in `skillporter v2.4.0`)
**Module:** `skillporter/registry.py`

## 1. Overview & Design Principles

Phase 1 defines the versioned client contract, package provenance schema, security gate, and CLI lifecycle (`search`, `info`, `pack`, `publish`, `add registry:<slug>`) before deploying a centralized multi-tenant backend.

1. **Zero-Trust Package Verification**: Every published package consists of a deterministic, reproducible `.tar.gz` archive (normalizing UID/GID/mtime to `0`) paired with a `provenance.json` manifest pinning the archive SHA-256, content tree SHA-256, per-file SHA-256 digests, and security scan assessment.
2. **Fail-Closed Security Gate**: `skillporter publish` refuses to package or publish any skill that has specification errors, fails the static/SkillSpector security scan, or has a `risk_score > 30`.
3. **Offline & Custom Registry Support**: The client merges the built-in curated `SEED_CATALOG` with any local JSON file or HTTPS index pointed to by `SKILLPORTER_REGISTRY_URL` or `--registry` (capped at 1 MiB response size to prevent memory exhaustion).

## 2. Package Metadata Schema (`RegistryPackage`)

```json
{
  "contract_version": "1.0.0",
  "packages": [
    {
      "slug": "publisher/skill-name",
      "name": "skill-name",
      "publisher": "publisher",
      "description": "What the skill does and when an agent should trigger it.",
      "source": "https://github.com/publisher/repo/tree/main/skills/skill-name",
      "version": "1.2.0",
      "category": "developer-tools",
      "tags": ["skills", "ci", "security"],
      "verified_harnesses": ["claude-code", "codex", "cursor", "github-copilot"],
      "license": "MIT",
      "homepage": "https://github.com/publisher/repo",
      "rating": 4.9,
      "downloads": 1250,
      "risk_score": 0,
      "dependencies": ["publisher/helper-skill@^1.0.0"]
    }
  ]
}
```

## 3. Provenance Manifest Schema (`<name>-<version>.provenance.json`)

```json
{
  "schema_version": 2,
  "registry_contract_version": "1.0.0",
  "name": "my-skill",
  "version": "1.2.0",
  "description": "...",
  "license": "MIT",
  "generated_at": "2026-11-11T12:00:00Z",
  "archive": "my-skill-1.2.0.tar.gz",
  "archive_sha256": "<64-hex-sha256>",
  "tree_hash": "<64-hex-sha256>",
  "file_hashes": {
    "SKILL.md": "<64-hex-sha256>"
  },
  "security_assessment": {
    "type": "STATIC_SECURITY_ASSESSMENT",
    "engine": "skillspector",
    "engine_version": "2.4.0",
    "risk_score": 0,
    "recommendation": "APPROVE",
    "passed": true,
    "critical": 0,
    "high": 0,
    "medium": 0
  }
}
```

## 4. CLI Client Operations

- **Search**: `skillporter search <query> [--category <cat>] [--json]`
- **Inspect Metadata**: `skillporter info <publisher/name> [--json]`
- **Install by Name/Slug**: `skillporter add registry:<publisher/name>[@version] --harness all`
- **Build Release Bundle**: `skillporter pack <path> [--out .skillporter/dist] [--json]`
- **Publish (Client Contract)**: `skillporter publish <path> [--dry-run] [--registry <index.json|url>] [--format json]`
