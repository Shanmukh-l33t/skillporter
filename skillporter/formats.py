"""Universal Skill Format Detection and Controlled Adaptation Engine.

Primary portable format: Agent Skills specification (SKILL.md).
Also inspects and provides explicit, previewable adaptations for:
  * Cursor rules (.cursor/rules/<name>.mdc)
  * GitHub Copilot instructions (.github/instructions/<name>.instructions.md)
  * Windsurf rules (.windsurf/rules/<name>.md)
  * Continue rules (.continue/rules/<name>.md)
  * Aider conventions (CONVENTIONS.md section)
  * AGENTS.md index blocks

Principle: Never silently convert a skill in a way that changes its behavior
or silently drops bundled capabilities. Conversions validate target filenames,
escape frontmatter scalars, and report explicit adaptation limitations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import NAME_RE, SkillDoc, parse_skill

ADAPTED_FORMATS = (
    "cursor-mdc",
    "copilot-instructions",
    "windsurf-rules",
    "continue-rules",
    "aider-conventions",
    "agents-md",
)


@dataclass
class PackageInspection:
    """Detailed structural inspection of a skill directory or repository."""

    root: Path
    skill_doc: SkillDoc | None = None
    detected_formats: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    other_files: list[str] = field(default_factory=list)
    dependencies_mentioned: list[str] = field(default_factory=list)
    harness_configs: list[str] = field(default_factory=list)
    incompatible_files: list[str] = field(default_factory=list)
    adaptation_limitations: dict[str, list[str]] = field(default_factory=dict)


def _safe_adapted_name(doc: SkillDoc) -> str:
    """Return a validated single-segment skill name for adapted output paths.

    Prevents a malicious ``name: ../../evil`` in SKILL.md frontmatter from
    traversing outside ``.cursor/rules/`` or ``.github/instructions/``.
    """
    for candidate in (doc.name.strip(), doc.directory_name.strip()):
        if (
            candidate
            and candidate not in (".", "..")
            and "/" not in candidate
            and "\\" not in candidate
            and "\x00" not in candidate
            and (NAME_RE.match(candidate) or candidate.replace("_", "-").isalnum())
        ):
            return candidate
    raise ValueError(
        f"cannot derive safe adapted filename from skill name {doc.name!r} or directory {doc.directory_name!r}"
    )


def _sanitize_single_line(text: str) -> str:
    """Collapse newlines and control characters so scalars cannot inject YAML keys."""
    clean = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return clean.replace("\x00", "")


def assess_adaptation_limitations(
    doc: SkillDoc,
    skill_dir: Path | None = None,
    target_format: str = "cursor-mdc",
) -> list[str]:
    """Identify any skill features or assets that do not translate 1:1 to *target_format*."""
    notes: list[str] = []
    fm = doc.frontmatter
    if fm.get("allowed-tools"):
        notes.append(
            f"{target_format}: 'allowed-tools' pre-approval metadata is not enforced by flat rule files"
        )
    if fm.get("context") == "fork":
        notes.append(
            f"{target_format}: 'context: fork' subagent isolation is not supported in flat rule files"
        )
    if skill_dir is not None and skill_dir.is_dir():
        if (skill_dir / "scripts").is_dir() and any((skill_dir / "scripts").iterdir()):
            notes.append(
                f"{target_format}: bundled scripts/ remain in {skill_dir.name}/scripts/ "
                "and are not embedded in the rule file"
            )
        if (skill_dir / "references").is_dir() and any((skill_dir / "references").iterdir()):
            notes.append(
                f"{target_format}: progressive-disclosure references/ remain in {skill_dir.name}/references/"
            )
    return notes


def inspect_skill_dir(skill_dir: Path) -> PackageInspection:
    """Inspect a skill directory's structure, assets, scripts, and formats."""
    skill_dir = skill_dir.resolve()
    info = PackageInspection(root=skill_dir)

    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        info.detected_formats.append("agent-skills-v1 (SKILL.md)")
        doc = parse_skill(skill_md)
        info.skill_doc = doc
        compat = str(doc.frontmatter.get("compatibility", "")).strip()
        if compat:
            info.dependencies_mentioned.append(compat)
        for fmt in ADAPTED_FORMATS:
            lims = assess_adaptation_limitations(doc, skill_dir, fmt)
            if lims:
                info.adaptation_limitations[fmt] = lims

    if (skill_dir / "AGENTS.md").is_file():
        info.detected_formats.append("agents-md (AGENTS.md)")
    if (skill_dir / "CLAUDE.md").is_file():
        info.detected_formats.append("claude-md (CLAUDE.md)")
    if (skill_dir / "CONVENTIONS.md").is_file():
        info.detected_formats.append("aider-conventions (CONVENTIONS.md)")

    for item in sorted(skill_dir.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(skill_dir).as_posix()
        if rel == "SKILL.md":
            continue
        if rel.startswith("scripts/"):
            info.scripts.append(rel)
        elif rel.startswith("references/"):
            info.references.append(rel)
        elif rel.startswith(("assets/", "templates/")):
            info.assets.append(rel)
        elif rel.endswith((".mdc", ".instructions.md", ".clinerules", ".cursorrules")):
            info.harness_configs.append(rel)
        else:
            info.other_files.append(rel)

        if item.suffix.lower() in (".exe", ".dll", ".so", ".dylib", ".bin"):
            info.incompatible_files.append(rel)

    return info


def render_adapted_skill(doc: SkillDoc, target_format: str) -> tuple[str, str]:
    """Render a SKILL.md document into a controlled target harness format.

    Returns ``(relative_output_path, rendered_content)``.
    """
    name = _safe_adapted_name(doc)
    raw_desc = doc.description or f"Skill {name}"
    desc = _sanitize_single_line(raw_desc)
    body = doc.body.strip()
    lims = assess_adaptation_limitations(doc, doc.path.parent if doc.path else None, target_format)
    lim_comment = ""
    if lims:
        lim_lines = "\n".join(f"  - {item}" for item in lims)
        lim_comment = f"<!-- Adaptation notes:\n{lim_lines}\n-->\n\n"

    if target_format == "cursor-mdc":
        rel_path = f".cursor/rules/{name}.mdc"
        safe_desc = desc.replace('"', "'")
        content = (
            "---\n"
            f'description: "{safe_desc}"\n'
            "globs:\n"
            "alwaysApply: false\n"
            "---\n\n"
            f"<!-- Generated by skillporter from {name}/SKILL.md -->\n"
            f"{lim_comment}"
            f"{body}\n"
        )
        return rel_path, content

    if target_format == "copilot-instructions":
        rel_path = f".github/instructions/{name}.instructions.md"
        safe_desc = desc.replace('"', "'")
        content = (
            "---\n"
            f'description: "{safe_desc}"\n'
            'applyTo: "**"\n'
            "---\n\n"
            f"<!-- Generated by skillporter from {name}/SKILL.md -->\n"
            f"{lim_comment}"
            f"{body}\n"
        )
        return rel_path, content

    if target_format == "windsurf-rules":
        rel_path = f".windsurf/rules/{name}.md"
        content = (
            f"# {name}\n\n"
            f"> {desc}\n\n"
            f"<!-- Generated by skillporter from {name}/SKILL.md -->\n"
            f"{lim_comment}"
            f"{body}\n"
        )
        return rel_path, content

    if target_format == "continue-rules":
        rel_path = f".continue/rules/{name}.md"
        safe_desc = desc.replace('"', "'")
        content = (
            "---\n"
            f"name: {name}\n"
            f'description: "{safe_desc}"\n'
            "---\n\n"
            f"<!-- Generated by skillporter from {name}/SKILL.md -->\n"
            f"{lim_comment}"
            f"{body}\n"
        )
        return rel_path, content

    if target_format == "aider-conventions":
        rel_path = f".aider-desk/conventions/{name}.md"
        content = (
            f"# Skill: {name}\n\n"
            f"Trigger / Scope: {desc}\n\n"
            f"{lim_comment}"
            f"{body}\n"
        )
        return rel_path, content

    if target_format == "agents-md":
        rel_path = "AGENTS.md"
        content = (
            f"## Skill: {name}\n\n"
            f"- **Description**: {desc}\n"
            f"- **Source**: `{name}/SKILL.md`\n\n"
            f"{body}\n"
        )
        return rel_path, content

    raise ValueError(f"unsupported adapted format {target_format!r}; expected one of {ADAPTED_FORMATS}")
