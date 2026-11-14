# Custom adapters

The 19 built-in adapters cover public harnesses. If your organization runs an internal agent, or a harness Skillporter does not know yet, you can describe it without changing the core.

## Declarative JSON adapter

Create an adapter file, for example `acme-agent.json`:

```json
{
  "name": "acme-agent",
  "display_name": "Acme Internal Agent",
  "category": "coding",
  "support_status": "COMPATIBLE",
  "verification_level": "UNIT_TESTED",
  "docs": "https://internal.acme.example/agent/skills",
  "aliases": ["acme"],
  "paths": [
    {"path": ".acme/skills", "scope": "project"},
    {"path": ".acme/skills", "scope": "user"}
  ]
}
```

Load it from Python:

```python
from pathlib import Path
from skillporter.harnesses import load_adapter_file

load_adapter_file(Path("acme-agent.json"))
```

The loader parses JSON data only. It never executes code from an adapter file. Project and user paths must be relative and must not contain `..`, so an adapter cannot point outside its scope.

Adapters loaded this way default to `UNVERIFIED` for both support and verification unless the file says otherwise.

## Python registration

```python
from skillporter.harnesses import Harness, SkillPath, register_adapter

register_adapter(
    Harness(
        name="acme-agent",
        display_name="Acme Internal Agent",
        support_status="NATIVE",
        verification_level="INTEGRATION_TESTED",
        paths=(
            SkillPath(".acme/skills", "project"),
            SkillPath(".acme/skills", "user"),
        ),
        docs="https://internal.acme.example/docs",
    )
)
```

`register_adapter` rejects unknown support types and verification tiers.

## Fields

| Field | Description |
|---|---|
| `name` | Canonical ID used with `--harness`. |
| `display_name` | Human-readable name. |
| `category` | `coding` or `autonomous`. |
| `support_status` | `NATIVE`, `COMPATIBLE`, `ADAPTED`, `PARTIAL`, `UNSUPPORTED` or `UNVERIFIED`. |
| `verification_level` | The evidence tier. Be honest about it. |
| `paths` | Each has a `path`, a `scope` (`project`, `user` or `admin`), an optional `note` and `is_compatibility`. List the primary path first. |
| `docs` | Link to the documentation that proves the paths. |
| `aliases` | Alternative names accepted on the command line. |
| `notes`, `limitations` | Shown by `skillporter info`. |

## Contributing an adapter upstream

A built-in adapter needs vendor documentation for its paths and an entry in the conformance suite. See [Contributing](../contributing/README.md) and [Harness compatibility](../harnesses/README.md).
