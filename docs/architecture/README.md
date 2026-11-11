# Architecture Overview

See the root [ARCHITECTURE.md](../../ARCHITECTURE.md) for the complete system diagram and module breakdown.

## Core Invariants

1. **Single Authoritative Core**: `skillporter/` in Python 3.9+ standard library is the sole source of business logic. `npx`, `uvx`, MCP, and GitHub Actions all invoke this core.
2. **Data-Driven Adapter Registry**: `skillporter/harnesses.py` defines all 19 adapters declaratively.
3. **Transactional State & Backups**: `.skillporter/state.json` and `.skillporter/backups/` guarantee that failed multi-harness operations roll back cleanly and previous versions can be restored via `skillporter rollback`.
