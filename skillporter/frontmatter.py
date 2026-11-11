"""Agent Skills frontmatter parsing and validation.

Implements the checks from https://agentskills.io/specification:

* ``name``      — required, 1-64 chars, ``[a-z0-9-]`` only, no leading/trailing
                  hyphen, no consecutive hyphens, must match the directory name.
* ``description`` — required, 1-1024 chars, should say what *and* when.
* ``license``    — optional
* ``compatibility`` — optional, 1-500 chars
* ``metadata``   — optional map of string -> string
* ``allowed-tools`` — optional space-separated string (experimental)

The parser is deliberately dependency-free: a YAML library is optional, and a
small frontmatter-subset parser is used as fallback so the tool runs anywhere
Python does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
# Recommended budget for the body an agent loads on activation.
MAX_BODY_TOKENS_WARN = 5000


@dataclass
class Issue:
    """A single validation finding."""

    level: str  # "error" | "warning"
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"


@dataclass
class SkillDoc:
    """Parsed SKILL.md."""

    path: Path
    frontmatter: dict[str, object] = field(default_factory=dict)
    body: str = ""

    @property
    def name(self) -> str:
        value = self.frontmatter.get("name")
        return value if isinstance(value, str) else ""

    @property
    def description(self) -> str:
        value = self.frontmatter.get("description")
        return value if isinstance(value, str) else ""

    @property
    def directory_name(self) -> str:
        return self.path.parent.name


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_scalar_or_nested(lines: list[str]) -> dict[str, object]:
    """Parse the block-style subset of YAML used by SKILL.md frontmatter.

    Handles ``key: value``, nested one-level maps, and ``>``/``|`` block
    scalars — the shapes the specification and real skills actually use.
    """
    data: dict[str, object] = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw.startswith((" ", "\t")):
            # Continuation without a parent key — malformed, skip.
            i += 1
            continue
        if ":" not in raw:
            i += 1
            continue
        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = rest.strip()

        if rest in (">", "|", ">-", "|-"):
            # Block scalar: consume following indented lines.
            block: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            joiner = "\n" if rest.startswith("|") else " "
            text = joiner.join(block).strip()
            if rest.endswith("-"):
                text = text.rstrip("\n")
            data[key] = text
            continue

        if rest == "":
            # Possibly a nested map.
            nested: dict[str, str] = {}
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                child = lines[i].strip()
                if child and ":" in child:
                    ck, _, cv = child.partition(":")
                    nested[ck.strip()] = _unquote(cv)
                i += 1
            data[key] = nested if nested else ""
            continue

        data[key] = _unquote(rest)
        i += 1
    return data


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split ``---`` frontmatter from the Markdown body."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw_fm, body = parts[1], parts[2]
    return _parse_scalar_or_nested(raw_fm.strip("\n").splitlines()), body.lstrip("\n")


def parse_skill(path: Path) -> SkillDoc:
    """Parse a SKILL.md file into a :class:`SkillDoc`."""
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = split_frontmatter(text)
    return SkillDoc(path=path, frontmatter=frontmatter, body=body)


def validate(doc: SkillDoc) -> list[Issue]:
    """Validate a parsed skill against the Agent Skills specification."""
    issues: list[Issue] = []
    fm = doc.frontmatter

    if not fm:
        issues.append(Issue("error", "no-frontmatter", "SKILL.md must start with YAML frontmatter delimited by '---'"))
        return issues

    name = doc.name
    if not name:
        issues.append(Issue("error", "missing-name", "'name' is required"))
    else:
        if len(name) > MAX_NAME:
            issues.append(Issue("error", "name-too-long", f"'name' is {len(name)} chars (max {MAX_NAME})"))
        if not NAME_RE.match(name):
            issues.append(Issue(
                "error", "name-invalid-chars",
                f"'name' {name!r} must be lowercase alphanumeric with single hyphens "
                "(no leading/trailing hyphen, no consecutive hyphens)",
            ))
        if name != doc.directory_name:
            issues.append(Issue(
                "error", "name-directory-mismatch",
                f"'name' {name!r} must match its directory name {doc.directory_name!r}",
            ))

    desc = doc.description
    if not desc:
        issues.append(Issue("error", "missing-description", "'description' is required"))
    else:
        if len(desc) > MAX_DESCRIPTION:
            issues.append(Issue(
                "error", "description-too-long",
                f"'description' is {len(desc)} chars (max {MAX_DESCRIPTION})",
            ))
        if len(desc) < 20:
            issues.append(Issue(
                "warning", "description-vague",
                "'description' is very short; state what the skill does AND when to use it",
            ))
        lowered = desc.lower()
        if not any(k in lowered for k in ("use when", "use this", "when the user", "when you", "trigger")):
            issues.append(Issue(
                "warning", "description-no-trigger",
                "'description' does not say when to activate; add a 'Use when ...' clause",
            ))

    compat = fm.get("compatibility")
    if isinstance(compat, str) and len(compat) > MAX_COMPATIBILITY:
        issues.append(Issue(
            "error", "compatibility-too-long",
            f"'compatibility' is {len(compat)} chars (max {MAX_COMPATIBILITY})",
        ))

    meta = fm.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        issues.append(Issue("error", "metadata-not-map", "'metadata' must be a map of string keys to string values"))
    elif isinstance(meta, dict):
        for k, v in meta.items():
            if not isinstance(v, str):
                issues.append(Issue(
                    "warning", "metadata-non-string",
                    f"metadata.{k} is not a string; clients may reject it",
                ))

    tools = fm.get("allowed-tools")
    if tools is not None and not isinstance(tools, str):
        issues.append(Issue("error", "allowed-tools-not-string", "'allowed-tools' must be a space-separated string"))

    body = doc.body.strip()
    if not body:
        issues.append(Issue("warning", "empty-body", "SKILL.md body is empty; the agent loads nothing on activation"))
    else:
        # Rough token estimate: ~4 chars/token for English prose.
        approx_tokens = len(body) // 4
        if approx_tokens > MAX_BODY_TOKENS_WARN:
            issues.append(Issue(
                "warning", "body-too-large",
                f"body is ~{approx_tokens} tokens (recommended < {MAX_BODY_TOKENS_WARN}); "
                "move detail into references/",
            ))

    return issues


def discover(root: Path) -> list[Path]:
    """Find every SKILL.md under *root*, skipping VCS, virtualenv, and backup trees."""
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".skillporter"}
    found: list[Path] = []
    for path in sorted(root.rglob("SKILL.md")):
        if any(part in skip for part in path.parts):
            continue
        found.append(path)
    return found
