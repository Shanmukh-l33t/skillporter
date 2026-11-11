"""Project Manifest (skillporter.yaml) and Deterministic Lockfile (skillporter.lock).

Provides dependency-free parsing and serialization of ``skillporter.yaml`` and
``skillporter.lock`` so teams can version-control their desired agent skill set
and reproduce identical installations across machines and CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import atomic_write_text

MANIFEST_FILENAME = "skillporter.yaml"
LOCKFILE_FILENAME = "skillporter.lock"
MANIFEST_SCHEMA_VERSION = 1


@dataclass
class ManifestSkillSpec:
    """One skill entry declared in skillporter.yaml."""

    name: str
    source: str
    ref: str = ""
    version: str = ""
    strategy: str = ""
    harnesses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"name": self.name, "source": self.source}
        if self.ref:
            d["ref"] = self.ref
        if self.version:
            d["version"] = self.version
        if self.strategy:
            d["strategy"] = self.strategy
        if self.harnesses:
            d["harnesses"] = list(self.harnesses)
        return d


@dataclass
class ProjectManifest:
    """Parsed skillporter.yaml configuration."""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    project: str = "my-project"
    scope: str = "project"
    strategy: str = "copy"
    harnesses: list[str] = field(default_factory=lambda: ["claude-code", "codex", "cursor"])
    security_policy: str = "HIGH"  # block installs on findings >= this severity
    skills: list[ManifestSkillSpec] = field(default_factory=list)

    def to_yaml(self) -> str:
        lines = [
            f"schema_version: {self.schema_version}",
            f"project: {self.project}",
            f"scope: {self.scope}",
            f"strategy: {self.strategy}",
            f"security_policy: {self.security_policy}",
            "harnesses:",
        ]
        for h in self.harnesses:
            lines.append(f"  - {h}")
        if not self.skills:
            lines.append("skills: []")
        else:
            lines.append("skills:")
            for s in self.skills:
                lines.append(f"  - name: {s.name}")
                lines.append(f"    source: {s.source}")
                if s.ref:
                    lines.append(f"    ref: {s.ref}")
                if s.version:
                    lines.append(f"    version: {s.version}")
                if s.strategy:
                    lines.append(f"    strategy: {s.strategy}")
                if s.harnesses:
                    lines.append(f"    harnesses: [{', '.join(s.harnesses)}]")
        return "\n".join(lines) + "\n"


@dataclass
class LockedSkill:
    """One deterministic entry in skillporter.lock."""

    name: str
    source: str
    resolved_commit: str
    version: str
    tree_hash: str
    strategy: str
    installed_targets: list[str] = field(default_factory=list)
    locked_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source": self.source,
            "resolved_commit": self.resolved_commit,
            "version": self.version,
            "tree_hash": self.tree_hash,
            "strategy": self.strategy,
            "installed_targets": sorted(set(self.installed_targets)),
            "locked_at": self.locked_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LockedSkill:
        targets = data.get("installed_targets", [])
        return cls(
            name=str(data.get("name", "")),
            source=str(data.get("source", "")),
            resolved_commit=str(data.get("resolved_commit", "")),
            version=str(data.get("version", "1.0.0")),
            tree_hash=str(data.get("tree_hash", "")),
            strategy=str(data.get("strategy", "copy")),
            installed_targets=[str(t) for t in targets] if isinstance(targets, list) else [],
            locked_at=str(data.get("locked_at", "")),
        )


@dataclass
class Lockfile:
    """Deterministic skillporter.lock representation."""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    generated_at: str = ""
    skills: dict[str, LockedSkill] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "skills": {k: v.to_dict() for k, v in sorted(self.skills.items())},
        }


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1]
    return val


def _parse_inline_list(val: str) -> list[str]:
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(x) for x in inner.split(",") if x.strip()]
    return []


def parse_manifest(text: str) -> ProjectManifest:
    """Parse skillporter.yaml (supports YAML subset and JSON)."""
    stripped = text.strip()
    if stripped.startswith("{"):
        raw = json.loads(stripped)
        skills = [
            ManifestSkillSpec(
                name=str(s["name"]),
                source=str(s["source"]),
                ref=str(s.get("ref", "")),
                version=str(s.get("version", "")),
                strategy=str(s.get("strategy", "")),
                harnesses=[str(h) for h in s.get("harnesses", [])],
            )
            for s in raw.get("skills", [])
            if isinstance(s, dict) and "name" in s and "source" in s
        ]
        return ProjectManifest(
            schema_version=int(raw.get("schema_version", 1)),
            project=str(raw.get("project", "my-project")),
            scope=str(raw.get("scope", "project")),
            strategy=str(raw.get("strategy", "copy")),
            harnesses=[str(h) for h in raw.get("harnesses", ["claude-code", "codex", "cursor"])],
            security_policy=str(raw.get("security_policy", "HIGH")),
            skills=skills,
        )

    manifest = ProjectManifest(harnesses=[], skills=[])
    section: str | None = None
    current_skill: dict[str, object] | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        sline = line.strip()

        if indent == 0 and ":" in sline:
            if current_skill and "name" in current_skill and "source" in current_skill:
                manifest.skills.append(
                    ManifestSkillSpec(
                        name=str(current_skill["name"]),
                        source=str(current_skill["source"]),
                        ref=str(current_skill.get("ref", "")),
                        version=str(current_skill.get("version", "")),
                        strategy=str(current_skill.get("strategy", "")),
                        harnesses=list(current_skill.get("harnesses", [])),  # type: ignore[arg-type]
                    )
                )
                current_skill = None

            k, _, v = sline.partition(":")
            k = k.strip()
            v = v.strip()
            if k == "schema_version" and v.isdigit():
                manifest.schema_version = int(v)
                section = None
            elif k == "project":
                manifest.project = _strip_quotes(v)
                section = None
            elif k == "scope":
                manifest.scope = _strip_quotes(v)
                section = None
            elif k == "strategy":
                manifest.strategy = _strip_quotes(v)
                section = None
            elif k == "security_policy":
                manifest.security_policy = _strip_quotes(v)
                section = None
            elif k == "harnesses":
                if v.startswith("["):
                    manifest.harnesses = _parse_inline_list(v)
                    section = None
                else:
                    section = "harnesses"
            elif k == "skills":
                section = None if v == "[]" else "skills"
            continue

        if section == "harnesses" and sline.startswith("- "):
            manifest.harnesses.append(_strip_quotes(sline[2:]))
            continue

        if section == "skills":
            if sline.startswith("- "):
                if current_skill and "name" in current_skill and "source" in current_skill:
                    manifest.skills.append(
                        ManifestSkillSpec(
                            name=str(current_skill["name"]),
                            source=str(current_skill["source"]),
                            ref=str(current_skill.get("ref", "")),
                            version=str(current_skill.get("version", "")),
                            strategy=str(current_skill.get("strategy", "")),
                            harnesses=list(current_skill.get("harnesses", [])),  # type: ignore[arg-type]
                        )
                    )
                current_skill = {}
                rem = sline[2:].strip()
                if ":" in rem:
                    ck, _, cv = rem.partition(":")
                    current_skill[ck.strip()] = _strip_quotes(cv)
            elif current_skill is not None and ":" in sline:
                ck, _, cv = sline.partition(":")
                ck = ck.strip()
                cv = cv.strip()
                if ck == "harnesses":
                    current_skill["harnesses"] = _parse_inline_list(cv)
                else:
                    current_skill[ck] = _strip_quotes(cv)

    if current_skill and "name" in current_skill and "source" in current_skill:
        manifest.skills.append(
            ManifestSkillSpec(
                name=str(current_skill["name"]),
                source=str(current_skill["source"]),
                ref=str(current_skill.get("ref", "")),
                version=str(current_skill.get("version", "")),
                strategy=str(current_skill.get("strategy", "")),
                harnesses=list(current_skill.get("harnesses", [])),  # type: ignore[arg-type]
            )
        )

    if not manifest.harnesses:
        manifest.harnesses = ["claude-code", "codex", "cursor"]
    return manifest


def load_manifest(root: Path) -> ProjectManifest | None:
    p = root / MANIFEST_FILENAME
    if not p.is_file():
        return None
    return parse_manifest(p.read_text(encoding="utf-8"))


def save_manifest(root: Path, manifest: ProjectManifest) -> Path:
    p = root / MANIFEST_FILENAME
    atomic_write_text(p, manifest.to_yaml())
    return p


def load_lockfile(root: Path) -> Lockfile:
    p = root / LOCKFILE_FILENAME
    if not p.is_file():
        return Lockfile()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Lockfile()
    skills_raw = raw.get("skills", {}) if isinstance(raw, dict) else {}
    skills: dict[str, LockedSkill] = {}
    if isinstance(skills_raw, dict):
        for k, v in skills_raw.items():
            if isinstance(v, dict):
                skills[k] = LockedSkill.from_dict(v)
    return Lockfile(
        schema_version=int(raw.get("schema_version", 1)) if isinstance(raw, dict) else 1,
        generated_at=str(raw.get("generated_at", "")) if isinstance(raw, dict) else "",
        skills=skills,
    )


def save_lockfile(root: Path, lockfile: Lockfile) -> Path:
    p = root / LOCKFILE_FILENAME
    atomic_write_text(p, json.dumps(lockfile.to_dict(), indent=2) + "\n")
    return p
