# Adapter Development SDK

Skillporter provides both a Python API and a declarative JSON loader for adding custom or organization-specific agent harnesses without modifying the core installer.

## 1. Declarative JSON Adapter (Explicit Trust Boundary)

Create an adapter file (`my-harness.json`):

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

Load it in Python via `skillporter.harnesses.load_adapter_file(Path("my-harness.json"))`. Because `load_adapter_file` parses declarative JSON only, it never executes arbitrary code.

## 2. Python Adapter Registration

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
