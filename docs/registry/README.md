# Skillporter Registry & Immutable Packaging

Skillporter includes a built-in seed catalog and supports custom local or remote JSON registries via `SKILLPORTER_REGISTRY_URL`.

## Searching & Inspecting Packages

```bash
skillporter search
skillporter search security
skillporter info anthropics/skills
skillporter inspect Shanmukh-l33t/skillporter
```

## Building Immutable Release Packages (`skillporter pack`)

To package a skill for distribution with reproducible timestamps (`mtime=0`), deterministic file ordering, and a SHA-256 provenance manifest:

```bash
skillporter pack ./skills/skillporter --out .skillporter/dist
```

This produces:
- `skillporter-2.0.0.tar.gz`
- `skillporter-2.0.0.provenance.json` (containing `archive_sha256`, `tree_hash`, per-file SHA-256 digests, and static security assessment summary)
