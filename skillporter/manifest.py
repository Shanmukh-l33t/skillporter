"""Project Manifest (skillporter.yaml) and Deterministic Lockfile (skillporter.lock).

Provides dependency-free parsing and serialization of ``skillporter.yaml`` and
``skillporter.lock`` (schema v2 with automatic backward-compatible v1 migration),
supporting configurable security risk thresholds (``security.max_risk_score``),
opt-in telemetry settings, and transitive skill dependency graphs.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .atomic import atomic_write_text
from .resolver import SkillDependency

MANIFEST_FILENAME = "skillporter.yaml"
LOCKFILE_FILENAME = "skillporter.lock"
MANIFEST_SCHEMA_VERSION = 2


class LockfileError(ValueError):
    """Raised when skillporter.lock is corrupted or uses an unsupported schema version."""

_WARNED_V1_LOCKFILES: set[str] = set()


@dataclass
class SecurityConfig:
    """Security policy and risk-score gate declared in skillporter.yaml."""

    policy: str = "HIGH"
    max_risk_score: int | None = None
    engine: str = "auto"
    sandbox: bool = False

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"policy": self.policy, "engine": self.engine, "sandbox": self.sandbox}
        if self.max_risk_score is not None:
            d["max_risk_score"] = self.max_risk_score
        return d


@dataclass
class TelemetryConfig:
    """Opt-in privacy-preserving telemetry settings in skillporter.yaml."""

    enabled: bool = False


@dataclass
class ManifestSkillSpec:
    """One skill entry declared in skillporter.yaml."""

    name: str
    source: str
    ref: str = ""
    version: str = ""
    strategy: str = ""
    harnesses: list[str] = field(default_factory=list)
    dependencies: list[SkillDependency] = field(default_factory=list)

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
        if self.dependencies:
            d["dependencies"] = [dep.to_dict() for dep in self.dependencies]
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
    max_risk_score: int | None = None
    security: SecurityConfig = field(default_factory=SecurityConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    harness_paths: dict[str, str] = field(default_factory=dict)
    profile: str = ""
    skills: list[ManifestSkillSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_risk_score is not None and self.security.max_risk_score is None:
            self.security.max_risk_score = self.max_risk_score
        elif self.security.max_risk_score is not None and self.max_risk_score is None:
            self.max_risk_score = self.security.max_risk_score
        if self.security_policy != "HIGH" and self.security.policy == "HIGH":
            self.security.policy = self.security_policy
        elif self.security.policy != "HIGH" and self.security_policy == "HIGH":
            self.security_policy = self.security.policy

    def to_yaml(self) -> str:
        lines = [
            f"schema_version: {self.schema_version}",
            f"project: {self.project}",
            f"scope: {self.scope}",
            f"strategy: {self.strategy}",
            f"security_policy: {self.security_policy}",
        ]
        if self.max_risk_score is not None or self.security.max_risk_score is not None:
            eff_score = self.max_risk_score if self.max_risk_score is not None else self.security.max_risk_score
            lines.extend(
                [
                    "security:",
                    f"  policy: {self.security.policy}",
                    f"  max_risk_score: {eff_score}",
                ]
            )
        if self.profile:
            lines.append(f"profile: {self.profile}")
        if self.telemetry.enabled:
            lines.extend(["telemetry:", "  enabled: true"])
        if self.harness_paths:
            lines.append("harness_paths:")
            for hk, hp in sorted(self.harness_paths.items()):
                lines.append(f"  {hk}: {hp}")
        lines.append("harnesses:")
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
                if s.dependencies:
                    dep_tokens = [
                        f"{d.name}@{d.version}" if d.version and d.version != "*" else d.name
                        for d in s.dependencies
                    ]
                    lines.append(f"    dependencies: [{', '.join(dep_tokens)}]")
        return "\n".join(lines) + "\n"


@dataclass
class LockedSkill:
    """One deterministic node in skillporter.lock (schema v2)."""

    name: str
    source: str
    resolved_commit: str
    version: str
    tree_hash: str
    strategy: str
    installed_targets: list[str] = field(default_factory=list)
    locked_at: str = ""
    dependencies: dict[str, str] = field(default_factory=dict)
    risk_score: int = 0
    direct: bool = True
    file_hashes: dict[str, str] = field(default_factory=dict)
    adapter_version: str = ""
    scope: str = "project"
    adapt: bool = False
    manifest_schema_version: int = MANIFEST_SCHEMA_VERSION

    @property
    def pin_state(self) -> str:
        """Classify whether this lockfile entry is immutable or references a mutable source."""
        if not self.tree_hash:
            return "UNPINNED_MUTABLE"
        if self.resolved_commit and len(self.resolved_commit) >= 7:
            return "PINNED_COMMIT"
        is_remote = self.source.startswith(("https://", "http://", "git@", "github:", "registry:"))
        if is_remote and not self.resolved_commit:
            return "UNPINNED_MUTABLE"
        return "PINNED_CONTENT"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source": self.source,
            "resolved_commit": self.resolved_commit,
            "version": self.version,
            "tree_hash": self.tree_hash,
            "file_hashes": {k: self.file_hashes[k] for k in sorted(self.file_hashes)},
            "pin_state": self.pin_state,
            "strategy": self.strategy,
            "scope": self.scope,
            "adapt": bool(self.adapt),
            "adapter_version": self.adapter_version or __version__,
            "manifest_schema_version": int(self.manifest_schema_version),
            "installed_targets": sorted(set(self.installed_targets)),
            "locked_at": self.locked_at,
            "dependencies": {k: self.dependencies[k] for k in sorted(self.dependencies)},
            "risk_score": int(self.risk_score),
            "direct": bool(self.direct),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LockedSkill:
        targets = data.get("installed_targets", [])
        raw_deps = data.get("dependencies", {})
        deps: dict[str, str] = {}
        if isinstance(raw_deps, dict):
            deps = {str(k): str(v) for k, v in sorted(raw_deps.items())}
        elif isinstance(raw_deps, list):
            for item in raw_deps:
                sd = SkillDependency.from_any(item)
                deps[sd.name] = sd.version
        raw_fhashes = data.get("file_hashes", {})
        fhashes = {str(k): str(v) for k, v in sorted(raw_fhashes.items())} if isinstance(raw_fhashes, dict) else {}
        raw_risk = data.get("risk_score", 0)
        raw_mver = data.get("manifest_schema_version", MANIFEST_SCHEMA_VERSION)
        return cls(
            name=str(data.get("name", "")),
            source=str(data.get("source", "")),
            resolved_commit=str(data.get("resolved_commit", "")),
            version=str(data.get("version", "1.0.0")),
            tree_hash=str(data.get("tree_hash", "")),
            strategy=str(data.get("strategy", "copy")),
            installed_targets=[str(t) for t in targets] if isinstance(targets, list) else [],
            locked_at=str(data.get("locked_at", "")),
            dependencies=deps,
            risk_score=int(raw_risk) if isinstance(raw_risk, (int, float)) else 0,
            direct=bool(data.get("direct", True)),
            file_hashes=fhashes,
            adapter_version=str(data.get("adapter_version", "")),
            scope=str(data.get("scope", "project")),
            adapt=bool(data.get("adapt", False)),
            manifest_schema_version=int(raw_mver) if isinstance(raw_mver, int) else MANIFEST_SCHEMA_VERSION,
        )


@dataclass
class Lockfile:
    """Deterministic skillporter.lock representation (schema v2)."""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    generated_at: str = ""
    skills: dict[str, LockedSkill] = field(default_factory=dict)
    migrated_from_v1: bool = False
    manifest_schema_version: int = MANIFEST_SCHEMA_VERSION

    @property
    def reproducible(self) -> bool:
        """Return True only when every locked skill is content-hashed and free of unpinned mutable refs."""
        return all(bool(s.tree_hash) and s.pin_state != "UNPINNED_MUTABLE" for s in self.skills.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_schema_version": self.manifest_schema_version,
            "reproducible": self.reproducible,
            "generated_at": self.generated_at or "1970-01-01T00:00:00Z",
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


def _build_skill_spec(current_skill: dict[str, object]) -> ManifestSkillSpec:
    raw_deps = current_skill.get("dependencies", [])
    deps: list[SkillDependency] = []
    if isinstance(raw_deps, list):
        for item in raw_deps:
            deps.append(SkillDependency.from_any(item))
    elif isinstance(raw_deps, dict):
        for k, v in raw_deps.items():
            deps.append(SkillDependency(name=str(k), version=str(v)))
    return ManifestSkillSpec(
        name=str(current_skill["name"]),
        source=str(current_skill["source"]),
        ref=str(current_skill.get("ref", "")),
        version=str(current_skill.get("version", "")),
        strategy=str(current_skill.get("strategy", "")),
        harnesses=list(current_skill.get("harnesses", [])),  # type: ignore[arg-type]
        dependencies=deps,
    )


def parse_manifest(text: str) -> ProjectManifest:
    """Parse skillporter.yaml (supports YAML subset and JSON)."""
    stripped = text.strip()
    if stripped.startswith("{"):
        raw = json.loads(stripped)
        sec_raw = raw.get("security", {}) if isinstance(raw.get("security"), dict) else {}
        tel_raw = raw.get("telemetry", {}) if isinstance(raw.get("telemetry"), dict) else {}
        max_risk_val = sec_raw.get("max_risk_score", raw.get("max_risk_score"))
        max_risk = int(max_risk_val) if isinstance(max_risk_val, (int, float)) else None
        sec_policy = str(sec_raw.get("policy", raw.get("security_policy", "HIGH")))
        skills = [
            _build_skill_spec(s)
            for s in raw.get("skills", [])
            if isinstance(s, dict) and "name" in s and "source" in s
        ]
        raw_hpaths = raw.get("harness_paths", {}) if isinstance(raw.get("harness_paths"), dict) else {}
        return ProjectManifest(
            schema_version=int(raw.get("schema_version", MANIFEST_SCHEMA_VERSION)),
            project=str(raw.get("project", "my-project")),
            scope=str(raw.get("scope", "project")),
            strategy=str(raw.get("strategy", "copy")),
            harnesses=[str(h) for h in raw.get("harnesses", ["claude-code", "codex", "cursor"])],
            security_policy=sec_policy,
            max_risk_score=max_risk,
            security=SecurityConfig(
                policy=sec_policy,
                max_risk_score=max_risk,
                engine=str(sec_raw.get("engine", "auto")),
                sandbox=bool(sec_raw.get("sandbox", False)),
            ),
            telemetry=TelemetryConfig(enabled=bool(tel_raw.get("enabled", False))),
            harness_paths={str(k): str(v) for k, v in raw_hpaths.items()},
            profile=str(raw.get("profile", "")),
            skills=skills,
        )

    manifest = ProjectManifest(harnesses=[], skills=[])
    section: str | None = None
    current_skill: dict[str, object] | None = None
    current_dep: dict[str, str] | None = None
    in_skill_deps = False

    def _flush_dep() -> None:
        nonlocal current_dep
        if current_dep and "name" in current_dep and current_skill is not None:
            deps_list = current_skill.setdefault("dependencies", [])
            if isinstance(deps_list, list):
                deps_list.append(SkillDependency.from_any(current_dep))
        current_dep = None

    def _flush_skill() -> None:
        nonlocal current_skill, in_skill_deps
        _flush_dep()
        if current_skill and "name" in current_skill and "source" in current_skill:
            manifest.skills.append(_build_skill_spec(current_skill))
        current_skill = None
        in_skill_deps = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        sline = line.strip()

        if indent == 0 and ":" in sline:
            _flush_skill()
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
            elif k == "profile":
                manifest.profile = _strip_quotes(v)
                section = None
            elif k == "security_policy":
                manifest.security_policy = _strip_quotes(v)
                manifest.security.policy = manifest.security_policy
                section = None
            elif k == "max_risk_score" and v.isdigit():
                manifest.max_risk_score = int(v)
                manifest.security.max_risk_score = int(v)
                section = None
            elif k == "security":
                section = "security"
            elif k == "telemetry":
                section = "telemetry"
            elif k == "harness_paths":
                section = "harness_paths"
            elif k == "harnesses":
                if v.startswith("["):
                    manifest.harnesses = _parse_inline_list(v)
                    section = None
                else:
                    section = "harnesses"
            elif k == "skills":
                section = None if v == "[]" else "skills"
            continue

        if section == "security" and ":" in sline:
            sk, _, sv = sline.partition(":")
            sk = sk.strip()
            sv = _strip_quotes(sv.strip())
            if sk == "max_risk_score" and sv.isdigit():
                manifest.max_risk_score = int(sv)
                manifest.security.max_risk_score = int(sv)
            elif sk in ("policy", "security_policy"):
                manifest.security_policy = sv
                manifest.security.policy = sv
            elif sk == "engine":
                manifest.security.engine = sv
            elif sk == "sandbox":
                manifest.security.sandbox = sv.lower() in ("true", "1", "yes")
            continue

        if section == "telemetry" and ":" in sline:
            tk, _, tv = sline.partition(":")
            if tk.strip() == "enabled":
                manifest.telemetry.enabled = _strip_quotes(tv.strip()).lower() in ("true", "1", "yes")
            continue

        if section == "harness_paths" and ":" in sline:
            hk, _, hv = sline.partition(":")
            hkey = _strip_quotes(hk.strip()).lower()
            hval = _strip_quotes(hv.strip())
            if hkey and hval:
                manifest.harness_paths[hkey] = hval
            continue

        if section == "harnesses" and sline.startswith("- "):
            manifest.harnesses.append(_strip_quotes(sline[2:]))
            continue

        if section == "skills":
            if indent <= 2 and sline.startswith("- "):
                _flush_skill()
                current_skill = {}
                rem = sline[2:].strip()
                if ":" in rem:
                    ck, _, cv = rem.partition(":")
                    current_skill[ck.strip()] = _strip_quotes(cv)
                continue

            if current_skill is not None:
                if in_skill_deps and indent >= 6:
                    if sline.startswith("- "):
                        _flush_dep()
                        rem_d = sline[2:].strip()
                        if ":" in rem_d:
                            dk, _, dv = rem_d.partition(":")
                            current_dep = {dk.strip(): _strip_quotes(dv)}
                        else:
                            deps_list = current_skill.setdefault("dependencies", [])
                            if isinstance(deps_list, list):
                                deps_list.append(SkillDependency.from_any(_strip_quotes(rem_d)))
                    elif current_dep is not None and ":" in sline:
                        dk, _, dv = sline.partition(":")
                        current_dep[dk.strip()] = _strip_quotes(dv)
                    continue

                if ":" in sline:
                    _flush_dep()
                    in_skill_deps = False
                    ck, _, cv = sline.partition(":")
                    ck = ck.strip()
                    cv = cv.strip()
                    if ck == "harnesses":
                        current_skill["harnesses"] = _parse_inline_list(cv)
                    elif ck == "dependencies":
                        if cv.startswith("["):
                            current_skill["dependencies"] = [
                                SkillDependency.from_any(x) for x in _parse_inline_list(cv)
                            ]
                        elif not cv:
                            current_skill["dependencies"] = []
                            in_skill_deps = True
                        else:
                            current_skill["dependencies"] = [SkillDependency.from_any(_strip_quotes(cv))]
                    else:
                        current_skill[ck] = _strip_quotes(cv)

    _flush_skill()

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


def load_lockfile(root: Path, *, warn_migration: bool = True) -> Lockfile:
    p = (root / LOCKFILE_FILENAME).resolve()
    if not p.is_file():
        return Lockfile()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockfileError(f"corrupted {LOCKFILE_FILENAME} at {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LockfileError(f"corrupted {LOCKFILE_FILENAME} at {p}: root JSON value must be an object")

    raw_ver_obj = raw.get("schema_version", 1)
    if isinstance(raw_ver_obj, bool) or not isinstance(raw_ver_obj, int):
        raise LockfileError(f"invalid schema_version {raw_ver_obj!r} in {LOCKFILE_FILENAME}")
    raw_ver = raw_ver_obj
    if raw_ver < 1 or raw_ver > MANIFEST_SCHEMA_VERSION:
        raise LockfileError(
            f"unsupported {LOCKFILE_FILENAME} schema_version {raw_ver} "
            f"(supported versions: 1..{MANIFEST_SCHEMA_VERSION})"
        )

    migrated = False
    if raw_ver < MANIFEST_SCHEMA_VERSION:
        migrated = True
        if warn_migration and str(p) not in _WARNED_V1_LOCKFILES:
            _WARNED_V1_LOCKFILES.add(str(p))
            print(
                f"warning: auto-migrating {LOCKFILE_FILENAME} from schema_version "
                f"{raw_ver} to {MANIFEST_SCHEMA_VERSION}",
                file=sys.stderr,
            )

    skills_raw = raw.get("skills", {})
    if not isinstance(skills_raw, dict):
        raise LockfileError(f"corrupted {LOCKFILE_FILENAME} at {p}: 'skills' must be an object")
    skills: dict[str, LockedSkill] = {}
    for k, v in sorted(skills_raw.items()):
        if not isinstance(v, dict):
            raise LockfileError(f"corrupted {LOCKFILE_FILENAME} entry for {k!r}: expected object")
        skills[k] = LockedSkill.from_dict(v)
    raw_mver = raw.get("manifest_schema_version", MANIFEST_SCHEMA_VERSION)
    return Lockfile(
        schema_version=MANIFEST_SCHEMA_VERSION,
        generated_at=str(raw.get("generated_at", "")),
        skills=skills,
        migrated_from_v1=migrated,
        manifest_schema_version=int(raw_mver) if isinstance(raw_mver, int) else MANIFEST_SCHEMA_VERSION,
    )


def save_lockfile(root: Path, lockfile: Lockfile) -> Path:
    """Write `skillporter.lock` with byte-stable deterministic formatting across machines."""
    p = root / LOCKFILE_FILENAME
    if p.is_file() and not lockfile.generated_at:
        try:
            existing_raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(existing_raw, dict):
                existing_skills = existing_raw.get("skills")
                new_skills = {k: v.to_dict() for k, v in sorted(lockfile.skills.items())}
                if existing_skills == new_skills and existing_raw.get("generated_at"):
                    lockfile.generated_at = str(existing_raw["generated_at"])
        except (OSError, json.JSONDecodeError):
            pass

    if not lockfile.generated_at:
        lockfile.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    atomic_write_text(p, json.dumps(lockfile.to_dict(), indent=2, sort_keys=True) + "\n")
    return p
