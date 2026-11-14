"""Deterministic Dependency & Semver Version Resolver for Agent Skills.

Supports:
  * Semver parsing and range constraints (``*``, ``1.2.3``, ``^1.2.0``,
    ``~1.2.0``, ``>=1.0.0``, ``<2.0.0``, compound space/comma ranges)
  * Direct dependencies in ``skillporter.yaml`` and transitive dependencies in
    each skill's ``SKILL.md`` frontmatter (``dependencies:``)
  * Cycle detection with clear ``a -> b -> a`` path reporting (exit code 1)
  * Version conflict detection when two skills require incompatible ranges
  * Topological installation ordering and ASCII/JSON dependency tree rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import discover, parse_skill
from .security import compute_tree_hash, scan_skill

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)(?:\.(?P<minor>0|[1-9]\d*))?(?:\.(?P<patch>0|[1-9]\d*))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)

_COMPARATOR_RE = re.compile(r"^(?P<op>\^|~|>=|<=|==|=|>|<)?\s*(?P<ver>v?\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?)$")


class DependencyError(RuntimeError):
    """Base error for skill dependency resolution failures."""


class DependencyCycleError(DependencyError):
    """Raised when a cyclic dependency is detected in the skill graph."""


class DependencyConflictError(DependencyError):
    """Raised when version constraints for a dependency cannot be satisfied."""


@dataclass(frozen=True)
class SkillDependency:
    """One skill dependency constraint."""

    name: str
    version: str = "*"
    source: str = ""
    ref: str = ""

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {"name": self.name, "version": self.version or "*"}
        if self.source:
            d["source"] = self.source
        if self.ref:
            d["ref"] = self.ref
        return d

    @classmethod
    def from_any(cls, raw: object) -> SkillDependency:
        if isinstance(raw, SkillDependency):
            return raw
        if isinstance(raw, str):
            s = raw.strip()
            if "@" in s:
                name, _, ver = s.partition("@")
                return cls(name=name.strip(), version=ver.strip() or "*")
            if ":" in s and not s.startswith(("http:", "https:", "git@", "github:", "registry:")):
                name, _, ver = s.partition(":")
                return cls(name=name.strip(), version=ver.strip() or "*")
            return cls(name=s, version="*")
        if isinstance(raw, dict):
            return cls(
                name=str(raw.get("name", "")).strip(),
                version=str(raw.get("version", "*")).strip() or "*",
                source=str(raw.get("source", "")).strip(),
                ref=str(raw.get("ref", "")).strip(),
            )
        raise ValueError(f"Unsupported dependency specification: {raw!r}")


def parse_semver(version: str) -> tuple[int, int, int, str]:
    """Parse a semantic version string into ``(major, minor, patch, prerelease)``."""
    clean = version.strip()
    if not clean or clean == "*":
        return (0, 0, 0, "")
    m = _SEMVER_RE.match(clean)
    if not m:
        raise ValueError(f"Invalid semantic version: {version!r}")
    major = int(m.group("major") or 0)
    minor = int(m.group("minor") or 0)
    patch = int(m.group("patch") or 0)
    pre = m.group("prerelease") or ""
    return (major, minor, patch, pre)


def _cmp_tuple(v: tuple[int, int, int, str]) -> tuple[int, int, int, int, str]:
    # Release (no prerelease) sorts higher than prerelease of same major.minor.patch
    return (v[0], v[1], v[2], 1 if not v[3] else 0, v[3])


def satisfies_constraint(version: str, constraint: str) -> bool:
    """Return True if *version* satisfies the semver *constraint* range."""
    c_raw = (constraint or "*").strip()
    if not c_raw or c_raw in ("*", "latest", "any"):
        return True

    try:
        v_parsed = parse_semver(version)
    except ValueError:
        return version.strip() == c_raw

    v_num = v_parsed[:3]

    # Split compound constraints on comma or whitespace between tokens
    tokens = [t.strip() for part in c_raw.split(",") for t in part.split() if t.strip()]
    for tok in tokens:
        if tok == "*":
            continue
        m = _COMPARATOR_RE.match(tok)
        if not m:
            if tok != version.strip():
                return False
            continue
        op = m.group("op") or "=="
        target_str = m.group("ver")
        t_parsed = parse_semver(target_str)
        t_num = t_parsed[:3]

        if op in ("=", "=="):
            if v_num != t_num or (t_parsed[3] and v_parsed[3] != t_parsed[3]):
                return False
        elif op == ">=":
            if _cmp_tuple(v_parsed) < _cmp_tuple(t_parsed):
                return False
        elif op == "<=":
            if _cmp_tuple(v_parsed) > _cmp_tuple(t_parsed):
                return False
        elif op == ">":
            if _cmp_tuple(v_parsed) <= _cmp_tuple(t_parsed):
                return False
        elif op == "<":
            if _cmp_tuple(v_parsed) >= _cmp_tuple(t_parsed):
                return False
        elif op == "^":
            if v_num < t_num:
                return False
            if t_num[0] > 0:
                upper = (t_num[0] + 1, 0, 0)
            elif t_num[1] > 0:
                upper = (0, t_num[1] + 1, 0)
            else:
                upper = (0, 0, t_num[2] + 1)
            if v_num >= upper:
                return False
        elif op == "~":
            if v_num < t_num:
                return False
            upper = (t_num[0], t_num[1] + 1, 0)
            if v_num >= upper:
                return False
    return True


@dataclass
class ResolvedSkillNode:
    """One resolved node in the deterministic skill dependency graph."""

    name: str
    version: str
    source: str
    ref: str = ""
    resolved_commit: str = ""
    tree_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    risk_score: int = 0
    direct: bool = True
    skill_dir: Path | None = None
    dependencies: dict[str, str] = field(default_factory=dict)  # dep_name -> constraint

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "ref": self.ref,
            "resolved_commit": self.resolved_commit,
            "tree_hash": self.tree_hash,
            "risk_score": self.risk_score,
            "direct": self.direct,
            "dependencies": dict(sorted(self.dependencies.items())),
        }


@dataclass
class DependencyGraph:
    """Resolved, cycle-free dependency graph with deterministic install order."""

    nodes: dict[str, ResolvedSkillNode] = field(default_factory=dict)
    install_order: list[str] = field(default_factory=list)  # topological leaves-first order
    root_skills: list[str] = field(default_factory=list)
    _temp_sources: list[object] = field(default_factory=list, repr=False)

    def cleanup(self) -> None:
        for res in self._temp_sources:
            cleanup_fn = getattr(res, "cleanup", None)
            if callable(cleanup_fn):
                cleanup_fn()
        self._temp_sources.clear()

    def to_dict(self) -> dict[str, object]:
        edges: list[dict[str, str]] = []
        for sname in sorted(self.nodes):
            node = self.nodes[sname]
            for dep_name, constraint in sorted(node.dependencies.items()):
                edges.append({"from": sname, "to": dep_name, "constraint": constraint})
        return {
            "root_skills": sorted(self.root_skills),
            "install_order": list(self.install_order),
            "nodes": {k: self.nodes[k].to_dict() for k in sorted(self.nodes)},
            "edges": edges,
        }

    def render_tree(self) -> str:
        """Render a deterministic human-readable dependency tree."""
        if not self.nodes:
            return "(empty dependency graph)"
        lines: list[str] = []
        roots = sorted(self.root_skills) or sorted(self.nodes)

        def _walk(name: str, prefix: str, is_last: bool, is_root: bool, visited: set[str]) -> None:
            node = self.nodes.get(name)
            ver = node.version if node else "unknown"
            thash = f" ({node.tree_hash[:8]})" if (node and node.tree_hash) else ""
            connector = "" if is_root else ("└── " if is_last else "├── ")
            lines.append(f"{prefix}{connector}{name}@{ver}{thash}")
            if not node or name in visited:
                return
            next_visited = visited | {name}
            deps = sorted(node.dependencies.items())
            for idx, (dep_name, constraint) in enumerate(deps):
                last_child = idx == len(deps) - 1
                child_prefix = prefix if is_root else (prefix + ("    " if is_last else "│   "))
                dep_node = self.nodes.get(dep_name)
                dep_ver = dep_node.version if dep_node else "unresolved"
                dep_hash = f" ({dep_node.tree_hash[:8]})" if (dep_node and dep_node.tree_hash) else ""
                c_branch = "└── " if last_child else "├── "
                lines.append(f"{child_prefix}{c_branch}{dep_name}@{dep_ver} [requires {constraint}]{dep_hash}")
                if dep_node and dep_node.dependencies and dep_name not in next_visited:
                    sub_prefix = child_prefix + ("    " if last_child else "│   ")
                    for s_idx, (s_name, _s_con) in enumerate(sorted(dep_node.dependencies.items())):
                        _walk(s_name, sub_prefix, s_idx == len(dep_node.dependencies) - 1, False, next_visited)

        for r_idx, rname in enumerate(roots):
            _walk(rname, "", r_idx == len(roots) - 1, True, set())
        return "\n".join(lines)


def _extract_skill_version_and_deps(skill_dir: Path) -> tuple[str, list[SkillDependency]]:
    """Read version and frontmatter dependencies from ``SKILL.md``."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ("1.0.0", [])
    doc = parse_skill(skill_md)
    version = str(doc.frontmatter.get("version", "")).strip()
    meta = doc.frontmatter.get("metadata")
    if not version and isinstance(meta, dict):
        version = str(meta.get("version", "")).strip()
    if not version:
        version = "1.0.0"

    deps: list[SkillDependency] = []
    raw_deps = doc.frontmatter.get("dependencies")
    if isinstance(raw_deps, list):
        for item in raw_deps:
            deps.append(SkillDependency.from_any(item))
    elif isinstance(raw_deps, dict):
        for k, v in raw_deps.items():
            if isinstance(v, dict):
                deps.append(
                    SkillDependency(
                        name=str(k),
                        version=str(v.get("version", "*")),
                        source=str(v.get("source", "")),
                        ref=str(v.get("ref", "")),
                    )
                )
            else:
                deps.append(SkillDependency(name=str(k), version=str(v)))
    elif isinstance(raw_deps, str) and raw_deps.strip():
        for tok in raw_deps.split(","):
            if tok.strip():
                deps.append(SkillDependency.from_any(tok.strip()))
    return (version, deps)


def _index_workspace_skills(root: Path) -> dict[str, Path]:
    """Map skill name -> skill directory across the workspace and nearby directories."""
    by_name: dict[str, Path] = {}
    for smd in discover(root):
        sdir = smd.parent.resolve()
        doc = parse_skill(smd)
        sname = doc.name or sdir.name
        by_name.setdefault(sname, sdir)
        by_name.setdefault(sdir.name, sdir)
    return by_name


def resolve_dependency_graph(
    root: Path,
    manifest=None,
    *,
    lockfile=None,
) -> DependencyGraph:
    """Resolve all direct and transitive skill dependencies for *root*."""
    from .manifest import load_manifest
    from .sources import SourceError, resolve_source

    root = Path(root).resolve()
    if manifest is None:
        manifest = load_manifest(root)

    locked_skills = getattr(lockfile, "skills", {}) if lockfile is not None else {}

    workspace_skills = _index_workspace_skills(root)
    graph = DependencyGraph()

    # Map skill_name -> list of (requirer, constraint)
    constraints_by_skill: dict[str, list[tuple[str, str]]] = {}
    # Map skill_name ->ManifestSkillSpec or SkillDependency hint
    spec_hints: dict[str, dict[str, object]] = {}

    if manifest and manifest.skills:
        for s in manifest.skills:
            graph.root_skills.append(s.name)
            spec_hints[s.name] = {
                "source": s.source,
                "ref": s.ref,
                "version": s.version or "*",
                "dependencies": list(getattr(s, "dependencies", [])),
                "direct": True,
            }
            if s.version:
                constraints_by_skill.setdefault(s.name, []).append(("skillporter.yaml", s.version))
    else:
        for sname in sorted(workspace_skills):
            graph.root_skills.append(sname)
            spec_hints[sname] = {
                "source": f"./{workspace_skills[sname].relative_to(root).as_posix()}"
                if workspace_skills[sname].is_relative_to(root)
                else str(workspace_skills[sname]),
                "ref": "",
                "version": "*",
                "dependencies": [],
                "direct": True,
            }

    visiting: list[str] = []
    visited: set[str] = set()

    def _resolve_node(name: str, *, default_source: str = "", default_ref: str = "", is_direct: bool = False) -> None:
        if name in visiting:
            cycle_start = visiting.index(name)
            cycle_chain = " -> ".join([*visiting[cycle_start:], name])
            raise DependencyCycleError(f"cyclic skill dependency detected: {cycle_chain}")
        if name in visited:
            if is_direct and name in graph.nodes:
                graph.nodes[name].direct = True
            return

        visiting.append(name)
        hint = spec_hints.get(name, {})
        locked_entry = locked_skills.get(name) if isinstance(locked_skills, dict) else None
        src = str(hint.get("source") or default_source or (locked_entry.source if locked_entry else "") or "").strip()
        # If lockfile pins a resolved git commit, always prefer the immutable commit over a mutable branch ref!
        pinned_commit = str(getattr(locked_entry, "resolved_commit", "") or "").strip()
        ref = pinned_commit or str(hint.get("ref") or default_ref or "").strip()
        direct_flag = bool(hint.get("direct", is_direct))

        skill_dir: Path | None = None
        resolved_commit = ""
        canonical_src = src

        if name in workspace_skills and (not src or src.startswith(".") or Path(src).exists()):
            skill_dir = workspace_skills[name]
            if not canonical_src:
                canonical_src = (
                    f"./{skill_dir.relative_to(root).as_posix()}"
                    if skill_dir.is_relative_to(root)
                    else str(skill_dir)
                )
        elif src:
            try:
                res = resolve_source(src, base_dir=root, ref_override=ref)
                graph._temp_sources.append(res)
                for d in res.skill_dirs:
                    if d.name == name:
                        skill_dir = d
                        break
                if skill_dir is None and res.skill_dirs:
                    skill_dir = res.skill_dirs[0]
                resolved_commit = res.resolved_commit
                canonical_src = res.canonical_source
                if skill_dir is not None:
                    for d in res.skill_dirs:
                        workspace_skills.setdefault(d.name, d)
            except (SourceError, KeyError) as exc:
                raise DependencyError(f"cannot resolve dependency {name!r} from {src!r}: {exc}") from exc
        elif name in workspace_skills:
            skill_dir = workspace_skills[name]
            canonical_src = (
                f"./{skill_dir.relative_to(root).as_posix()}"
                if skill_dir.is_relative_to(root)
                else str(skill_dir)
            )
        else:
            raise DependencyError(
                f"unresolved skill dependency {name!r}: not found in workspace or skillporter.yaml"
            )

        actual_version = "1.0.0"
        fm_deps: list[SkillDependency] = []
        tree_hash = ""
        file_hashes: dict[str, str] = {}
        risk_score = 0
        if skill_dir and skill_dir.exists():
            actual_version, fm_deps = _extract_skill_version_and_deps(skill_dir)
            tree_hash, file_hashes = compute_tree_hash(skill_dir)
            risk_score = scan_skill(skill_dir, offline=True).risk_score

        manifest_deps: list[SkillDependency] = list(hint.get("dependencies", []))  # type: ignore[arg-type]
        merged_deps: dict[str, SkillDependency] = {}
        for d in [*fm_deps, *manifest_deps]:
            merged_deps[d.name] = d

        for dep in merged_deps.values():
            constraints_by_skill.setdefault(dep.name, []).append((name, dep.version or "*"))
            if dep.name not in spec_hints and dep.source:
                spec_hints[dep.name] = {
                    "source": dep.source,
                    "ref": dep.ref,
                    "version": dep.version,
                    "dependencies": [],
                    "direct": False,
                }
            _resolve_node(dep.name, default_source=dep.source, default_ref=dep.ref, is_direct=False)

        # Verify all constraints placed on `name` so far
        for requirer, req_constraint in constraints_by_skill.get(name, []):
            if not satisfies_constraint(actual_version, req_constraint):
                raise DependencyConflictError(
                    f"version conflict for skill {name!r}: {requirer} requires {req_constraint!r}, "
                    f"but resolved version is {actual_version!r}"
                )

        node = ResolvedSkillNode(
            name=name,
            version=actual_version,
            source=canonical_src or f"./{name}",
            ref=ref,
            resolved_commit=resolved_commit,
            tree_hash=tree_hash,
            file_hashes=file_hashes,
            risk_score=risk_score,
            direct=direct_flag,
            skill_dir=skill_dir,
            dependencies={d.name: (d.version or "*") for d in sorted(merged_deps.values(), key=lambda x: x.name)},
        )
        graph.nodes[name] = node
        visiting.pop()
        visited.add(name)
        graph.install_order.append(name)

    for rname in graph.root_skills:
        _resolve_node(rname, is_direct=True)

    # Final global constraint check across all nodes
    for sname, node in sorted(graph.nodes.items()):
        for requirer, req_constraint in constraints_by_skill.get(sname, []):
            if not satisfies_constraint(node.version, req_constraint):
                raise DependencyConflictError(
                    f"version conflict for skill {sname!r}: {requirer} requires {req_constraint!r}, "
                    f"but resolved version is {node.version!r}"
                )

    return graph
