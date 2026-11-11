"""Agent Skills frontmatter parsing, validation, and boundary-safe discovery.

Implements the checks from https://agentskills.io/specification and categorizes
findings into three explicit tiers:
  * ``spec``                  — Official Agent Skills specification violations.
  * ``recommendation``        — Progressive-disclosure and trigger-phrasing guidance.
  * ``harness-compatibility`` — Features or limits that behave differently across harnesses.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_BODY_TOKENS_WARN = 5000
MAX_BODY_LINES_WARN = 500

_DEEP_REF_RE = re.compile(r"\]\((?:references|assets|scripts)/[^)\s/]+/[^)\s/]+/[^)\s]+\)")


@dataclass
class Issue:
    """A single validation finding."""

    level: str  # "error" | "warning"
    code: str
    message: str
    category: str = "spec"  # "spec" | "recommendation" | "harness-compatibility"

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "code": self.code,
            "category": self.category,
            "message": self.message,
        }


@dataclass
class SkillDoc:
    """Parsed SKILL.md."""

    path: Path
    frontmatter: dict[str, object] = field(default_factory=dict)
    body: str = ""
    has_tab_indent: bool = False

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


def _parse_scalar_or_nested(lines: list[str]) -> tuple[dict[str, object], bool]:
    """Parse the block-style subset of YAML used by SKILL.md frontmatter.

    Returns ``(parsed_dict, has_tab_indentation)``.
    """
    data: dict[str, object] = {}
    has_tabs = any(line.startswith("\t") or line.startswith(" \t") for line in lines)
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw.startswith((" ", "\t")):
            i += 1
            continue
        if ":" not in raw:
            i += 1
            continue
        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = rest.strip()

        if rest in (">", "|", ">-", "|-"):
            block: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                if lines[i].startswith("\t"):
                    has_tabs = True
                block.append(lines[i].strip())
                i += 1
            joiner = "\n" if rest.startswith("|") else " "
            text = joiner.join(block).strip()
            if rest.endswith("-"):
                text = text.rstrip("\n")
            data[key] = text
            continue

        if rest == "":
            nested_map: dict[str, str] = {}
            nested_list: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                if lines[i].startswith("\t"):
                    has_tabs = True
                child = lines[i].strip()
                if not child or child.startswith("#"):
                    i += 1
                    continue
                if child.startswith("- "):
                    nested_list.append(_unquote(child[2:]))
                elif ":" in child:
                    ck, _, cv = child.partition(":")
                    nested_map[ck.strip()] = _unquote(cv)
                i += 1
            if nested_list and not nested_map:
                data[key] = nested_list
            else:
                data[key] = nested_map if nested_map else ""
            continue

        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            data[key] = [_unquote(x) for x in inner.split(",") if x.strip()] if inner else []
            i += 1
            continue

        data[key] = _unquote(rest)
        i += 1
    return data, has_tabs


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split line-anchored ``---`` YAML frontmatter from the Markdown body."""
    fm, body, _ = _split_frontmatter_detailed(text)
    return fm, body


def _split_frontmatter_detailed(text: str) -> tuple[dict[str, object], str, bool]:
    clean = text[1:] if text.startswith("\ufeff") else text
    lines = clean.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, clean, False

    closing_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() in ("---", "..."):
            closing_idx = idx
            break

    if closing_idx is None:
        return {}, clean, False

    fm_lines = lines[1:closing_idx]
    body_lines = lines[closing_idx + 1 :]
    body = "\n".join(body_lines).lstrip("\n")
    if clean.endswith("\n") and body:
        body += "\n"
    parsed, has_tabs = _parse_scalar_or_nested(fm_lines)
    return parsed, body, has_tabs


def parse_skill(path: Path) -> SkillDoc:
    """Parse a SKILL.md file into a :class:`SkillDoc`."""
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body, has_tabs = _split_frontmatter_detailed(text)
    return SkillDoc(path=path, frontmatter=frontmatter, body=body, has_tab_indent=has_tabs)


def validate(doc: SkillDoc) -> list[Issue]:
    """Validate a parsed skill against the Agent Skills specification."""
    issues: list[Issue] = []
    fm = doc.frontmatter

    if doc.has_tab_indent:
        issues.append(
            Issue(
                "error",
                "frontmatter-tab-indentation",
                "YAML frontmatter contains tab indentation; use spaces only",
                category="spec",
            )
        )

    if not fm:
        issues.append(
            Issue(
                "error",
                "no-frontmatter",
                "SKILL.md must start with YAML frontmatter delimited by '---'",
                category="spec",
            )
        )
        return issues

    name = doc.name
    if not name:
        issues.append(Issue("error", "missing-name", "'name' is required", category="spec"))
    else:
        if len(name) > MAX_NAME:
            issues.append(
                Issue("error", "name-too-long", f"'name' is {len(name)} chars (max {MAX_NAME})", category="spec")
            )
        if not NAME_RE.match(name):
            issues.append(
                Issue(
                    "error",
                    "name-invalid-chars",
                    f"'name' {name!r} must be lowercase alphanumeric with single hyphens "
                    "(no leading/trailing hyphen, no consecutive hyphens)",
                    category="spec",
                )
            )
        if name != doc.directory_name:
            issues.append(
                Issue(
                    "error",
                    "name-directory-mismatch",
                    f"'name' {name!r} must match its directory name {doc.directory_name!r}",
                    category="spec",
                )
            )

    desc = doc.description
    if not desc:
        issues.append(Issue("error", "missing-description", "'description' is required", category="spec"))
    else:
        if len(desc) > MAX_DESCRIPTION:
            issues.append(
                Issue(
                    "error",
                    "description-too-long",
                    f"'description' is {len(desc)} chars (max {MAX_DESCRIPTION})",
                    category="spec",
                )
            )
        if len(desc) < 20:
            issues.append(
                Issue(
                    "warning",
                    "description-vague",
                    "'description' is very short; state what the skill does AND when to use it",
                    category="recommendation",
                )
            )
        lowered = desc.lower()
        if not any(k in lowered for k in ("use when", "use this", "when the user", "when you", "trigger")):
            issues.append(
                Issue(
                    "warning",
                    "description-no-trigger",
                    "'description' does not say when to activate; add a 'Use when ...' clause",
                    category="recommendation",
                )
            )

    compat = fm.get("compatibility")
    if isinstance(compat, str) and len(compat) > MAX_COMPATIBILITY:
        issues.append(
            Issue(
                "error",
                "compatibility-too-long",
                f"'compatibility' is {len(compat)} chars (max {MAX_COMPATIBILITY})",
                category="spec",
            )
        )

    meta = fm.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        issues.append(
            Issue(
                "error",
                "metadata-not-map",
                "'metadata' must be a map of string keys to string values",
                category="spec",
            )
        )
    elif isinstance(meta, dict):
        for k, v in meta.items():
            if not isinstance(v, str):
                issues.append(
                    Issue(
                        "warning",
                        "metadata-non-string",
                        f"metadata.{k} is not a string; clients may reject it",
                        category="spec",
                    )
                )

    tools = fm.get("allowed-tools")
    if tools is not None and not isinstance(tools, str):
        issues.append(
            Issue(
                "error",
                "allowed-tools-not-string",
                "'allowed-tools' must be a space-separated string",
                category="spec",
            )
        )

    if fm.get("context") == "fork":
        issues.append(
            Issue(
                "warning",
                "harness-specific-context-fork",
                "'context: fork' is only supported by Claude Code and Hermes Agent; other harnesses ignore it",
                category="harness-compatibility",
            )
        )

    body = doc.body.strip()
    if not body:
        issues.append(
            Issue(
                "warning",
                "empty-body",
                "SKILL.md body is empty; the agent loads nothing on activation",
                category="recommendation",
            )
        )
    else:
        approx_tokens = len(body) // 4
        if approx_tokens > MAX_BODY_TOKENS_WARN:
            issues.append(
                Issue(
                    "warning",
                    "body-too-large",
                    f"body is ~{approx_tokens} tokens (recommended < {MAX_BODY_TOKENS_WARN}; Cline enforces <5k); "
                    "move detail into references/",
                    category="harness-compatibility",
                )
            )
        if _DEEP_REF_RE.search(body):
            issues.append(
                Issue(
                    "warning",
                    "deep-reference-path",
                    "file references should stay one level deep (e.g. references/FILE.md)",
                    category="recommendation",
                )
            )

    return issues


def discover(root: Path) -> list[Path]:
    """Find every skill root's SKILL.md under *root*, stopping at skill boundaries.

    Once a directory contains ``SKILL.md``, it is a single skill package; we do
    not recurse inside its ``references/``, ``scripts/``, or ``assets/``
    subdirectories looking for nested skills. Symlink cycles are avoided by
    tracking visited directory ``(st_dev, st_ino)`` pairs.
    """
    skip = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".skillporter",
        "build",
        "dist",
    }
    found: list[Path] = []
    visited_inodes: set[tuple[int, int]] = set()
    root = Path(root)
    if not root.exists():
        return found

    if root.is_file() and root.name == "SKILL.md":
        return [root]

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=True):
        cpath = Path(dirpath)
        try:
            st = cpath.stat()
            inode_key = (st.st_dev, st.st_ino)
            if inode_key in visited_inodes and inode_key != (0, 0):
                dirnames[:] = []
                continue
            visited_inodes.add(inode_key)
        except OSError:
            dirnames[:] = []
            continue

        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in skip
            and not d.endswith(".egg-info")
            and not d.startswith(".skillporter-")
        )

        if "SKILL.md" in filenames:
            found.append(cpath / "SKILL.md")
            # A directory containing SKILL.md is one skill; do not search inside it for more skills
            dirnames[:] = []

    return sorted(found)
