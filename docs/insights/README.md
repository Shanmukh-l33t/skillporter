# Suggestions and insights

Two read-only commands help you decide which skills a project needs, and what your skills and instruction files cost in context.

## Suggest skills for a project

```bash
skillporter suggest
```

`suggest` reads files in the workspace such as `package.json`, `pyproject.toml`, `requirements.txt`, `Dockerfile` and framework or test configuration, and detects the stack. It then matches the stack against a short hand-curated list of upstream skill repositories and explains each match: which detected technology it relates to, what the upstream repository contains, and the command to inspect or install it.

The list is small on purpose. Every entry points at an upstream repository whose public skill listing was checked, and an entry exists only where a matching skill exists. A suggestion carries no version, no risk score and no scan result, because Skillporter has not scanned it. It is reported as `not scanned`. The scan happens when you run `skillporter add`.

It works from local files only and does not upload your project. It does not recommend every keyword match. A generic dependency such as `lodash` does not trigger a skill, a Python project is not offered JVM skills, and an empty repository produces no suggestions. If nothing relevant is found, it says so.

Treat a suggestion as a starting point. Review a skill with `skillporter inspect` and `skillporter scan` before installing it. A suggestion does not mean the skill has been reviewed.

## Context and usage insights

```bash
skillporter insights
```

`insights` lists installed skills and instruction files with an estimated token size, which harnesses use them, and where the largest costs are. It also points at duplicated instructions and large files.

Token sizes are estimates from a four-characters-per-token rule. They are not tokenizer counts and differ by model.

Usage data is different. Skillporter cannot see inside an agent, so it does not invent usage figures. By default, `insights` shows size only. Usage appears only if you record it yourself:

```bash
skillporter insights --record-usage pdf --harness-used claude-code
```

Events are stored locally in `.skillporter/usage.jsonl`. Nothing is sent anywhere, and nothing is recorded unless you run that command or wire it into your own hook.

For the exact instructions one harness loads, use `skillporter context --harness <id>`, described in [Instruction files and context](../instructions/README.md).
