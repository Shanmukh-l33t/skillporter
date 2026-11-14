# Configuration Overview

See [docs/configuration/README.md](configuration/README.md) for the complete reference on `skillporter.yaml` (project manifest), `skillporter.lock` (deterministic lockfile), and environment variables.

## Summary

- **Zero-config operation**: Commands such as `skillporter diagnose .`, `skillporter scan .`, and `skillporter add <source>` work without a manifest file.
- **Declarative team manifest (`skillporter.yaml`)**: Created via `skillporter init` to declare target harnesses, security risk gates (`security.max_risk_score`), and skill dependencies.
- **Reproducible lockfile (`skillporter.lock`)**: Created via `skillporter lock` or `skillporter sync` and verified in CI via `skillporter lock --check`.
