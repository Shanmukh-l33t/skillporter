"""Diagnose why a skill does or does not load in a given harness, including
content-drift, duplicate-loading, multi-copy validation, and explicit
verification states.

Explicit compatibility & verification states exposed:
  * ``FOUND``       — Skill directory with SKILL.md discovered in workspace.
  * ``VALID``       — Passes all Agent Skills specification checks (0 errors).
  * ``INVALID``     — Contains one or more specification errors.
  * ``COMPATIBLE``  — Compatible with target harness (or ``ADAPTED`` when conversion required).
  * ``INSTALLED``   — Present at a path scanned by the harness.
  * ``VERIFIED``    — Installed AND adapter has independent runtime verification evidence.
  * ``UNVERIFIED``  — Installed at documented path, not runtime-probed in live agent process.
  * ``MISSING``     — Not present in any path scanned by the harness.
  * ``DRIFT``       — Copies across directories have diverging SHA-256 content hashes.
  * ``DUPLICATE``   — Present in >=2 distinct directories scanned by the same harness.
  * ``BROKEN``      — Dangling symlink in harness skill directory.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .frontmatter import Issue, discover, parse_skill, validate
from .security import compute_tree_hash

#: Files that make a directory a plausible skill root.
_SKILL_FILE = "SKILL.md"


@dataclass
class Location:
    """A concrete skill directory as found on disk for one harness path."""

    harness: str
    raw_path: str
    resolved: Path
    exists: bool
    skill_dirs: list[str] = field(default_factory=list)
    broken_links: list[str] = field(default_factory=list)
    is_bridge: bool = False
    skill_hashes: dict[str, str] = field(default_factory=dict)
    duplicate_paths: dict[str, list[str]] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.exists:
            return "missing"
        if self.broken_links:
            return "broken"
        return "ok" if self.skill_dirs else "empty"


@dataclass
class HarnessReport:
    """Per-harness diagnosis."""

    harness: str
    verified: bool
    locations: list[Location] = field(default_factory=list)
    reachable_skills: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    duplicate_skills: dict[str, list[str]] = field(default_factory=dict)
    drifted_skills: set[str] = field(default_factory=set)
    support_status: str = "NATIVE"
    verification_level: str = "DOCUMENTATION_VERIFIED"

    def loads(self, skill: str) -> bool:
        return skill in self.reachable_skills

    def cell_state(self, skill: str) -> str:
        """Return 'DRIFT', 'DUPLICATE', 'yes', or 'MISSING' (backward-compatible table cell)."""
        if skill not in self.reachable_skills:
            return "MISSING"
        if skill in self.drifted_skills:
            return "DRIFT"
        if skill in self.duplicate_skills:
            return "DUPLICATE"
        return "yes"

    def explicit_states(self, skill: str, *, is_valid: bool = True) -> list[str]:
        """Return explicit states: FOUND, VALID/INVALID, COMPATIBLE, INSTALLED/MISSING, VERIFIED/UNVERIFIED."""
        states = ["FOUND", "VALID" if is_valid else "INVALID"]
        if self.support_status in ("NATIVE", "COMPATIBLE"):
            states.append("COMPATIBLE")
        elif self.support_status == "ADAPTED":
            states.append("ADAPTED")
        else:
            states.append(self.support_status)

        if skill not in self.reachable_skills:
            states.append("MISSING")
            return states

        states.append("INSTALLED")
        if skill in self.drifted_skills:
            states.append("DRIFT")
        if skill in self.duplicate_skills:
            states.append("DUPLICATE")

        if self.verification_level == "RUNTIME_VERIFIED":
            states.append("VERIFIED")
        else:
            states.append("UNVERIFIED")
        return states


@dataclass
class Diagnosis:
    """Full result of a diagnose run."""

    root: Path
    skills: list[Path] = field(default_factory=list)
    skill_copies: dict[str, list[Path]] = field(default_factory=dict)
    reports: dict[str, HarnessReport] = field(default_factory=dict)
    issues: dict[str, list[Issue]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    drifted: dict[str, dict[str, str]] = field(default_factory=dict)
    duplicates: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    @property
    def skill_names(self) -> list[str]:
        return [p.parent.name for p in self.skills]

    def missing_in(self, skill: str) -> list[str]:
        return [h for h, r in self.reports.items() if not r.loads(skill)]

    def is_skill_valid(self, skill: str) -> bool:
        for copy_path in self.skill_copies.get(skill, []):
            errs = [i for i in self.issues.get(str(copy_path), []) if i.level == "error"]
            if errs:
                return False
        for path_str, iss_list in self.issues.items():
            if Path(path_str).name == skill and any(i.level == "error" for i in iss_list):
                return False
        return True


def load_custom_harness_paths(
    root: Path,
    *,
    scope: str = "project",
    explicit: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve safe custom harness directory overrides from manifest, env, and CLI."""
    merged: dict[str, str] = {}
    if scope == "project":
        from .manifest import load_manifest

        manifest = load_manifest(root)
        if manifest and manifest.harness_paths:
            for hk, hp in manifest.harness_paths.items():
                with contextlib.suppress(KeyError):
                    merged[harnesses.get(hk).name] = hp

    env_raw = os.environ.get("SKILLPORTER_HARNESS_PATHS", "").strip()
    if env_raw:
        for pair in env_raw.split(","):
            if "=" not in pair:
                continue
            hk, _, hp = pair.partition("=")
            hk_s, hp_s = hk.strip(), hp.strip()
            if hk_s and hp_s:
                with contextlib.suppress(KeyError):
                    merged[harnesses.get(hk_s).name] = hp_s

    if explicit:
        for hk, hp in explicit.items():
            if hk and hp:
                with contextlib.suppress(KeyError):
                    merged[harnesses.get(hk).name] = hp

    validated: dict[str, str] = {}
    for hname, raw_p in merged.items():
        norm = raw_p.strip().replace("\\", "/")
        parts = [seg for seg in norm.split("/") if seg]
        if not norm or ".." in parts or norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
            raise ValueError(
                f"unsafe custom harness path {raw_p!r} for {hname!r}: relative path without '..' required"
            )
        validated[hname] = raw_p.strip()
    return validated


def select_harness_install_raw_path(
    h: harnesses.Harness,
    scope: str,
    *,
    custom_paths: dict[str, str] | None = None,
    isolated: bool = False,
) -> str | None:
    """Choose the target raw directory path for *h* in *scope*.

    Honors ``custom_paths`` first. When ``isolated=True`` and *h* offers a
    dedicated non-shared native directory (such as ``.cursor/skills`` or
    ``.gemini/skills`` alongside shared ``.agents/skills``), prefers the
    harness-specific directory so installations do not leak into other
    ``.agents/skills`` harnesses.
    """
    if custom_paths and h.name in custom_paths:
        return custom_paths[h.name]
    paths = h.project_paths if scope == "project" else h.user_paths
    if not paths:
        return None
    if isolated:
        for sp in paths:
            if not sp.is_compatibility and sp.path != ".agents/skills":
                return sp.path
    return paths[0].path


def resolve_path(raw: str, scope: str, root: Path, home: Path | None = None) -> Path:
    """Resolve a harness path to an absolute location.

    ``user`` scope resolves against ``$HOME`` (or ``$HERMES_HOME`` for Hermes,
    which is profile-scoped and must never be hardcoded).
    """
    home = home or Path(os.path.expanduser("~"))
    if raw.startswith("$HERMES_HOME"):
        base = Path(os.environ.get("HERMES_HOME") or home / ".hermes")
        return base / raw.split("$HERMES_HOME", 1)[1].lstrip("/")
    if scope == "admin":
        return Path(raw)
    if scope == "user":
        return home / raw
    return root / raw


def scan_location(
    harness: str,
    raw_path: str,
    scope: str,
    root: Path,
    *,
    recursive: bool,
    home: Path | None = None,
) -> Location:
    """Inspect one harness path and list the skills inside it."""
    resolved = resolve_path(raw_path, scope, root, home)
    label = raw_path if scope == "project" else str(resolved)
    loc = Location(
        harness=harness,
        raw_path=label,
        resolved=resolved,
        exists=resolved.exists(),
    )

    if not loc.exists:
        return loc

    # A path that is itself a symlink we cannot follow is a broken link.
    if resolved.is_symlink() and not resolved.exists():
        loc.broken_links.append(str(resolved))
        return loc

    try:
        entries = sorted(resolved.iterdir())
    except (PermissionError, OSError):
        return loc

    seen_in_loc: dict[str, list[str]] = {}
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_symlink() and not entry.exists():
            loc.broken_links.append(str(entry))
            continue
        if (entry / _SKILL_FILE).is_file():
            loc.skill_dirs.append(entry.name)
            seen_in_loc.setdefault(entry.name, []).append(entry.name)
            thash, _ = compute_tree_hash(entry)
            if thash:
                loc.skill_hashes[entry.name] = thash
            continue
        # Nested category directories (e.g. Hermes $HERMES_HOME/skills/<category>/<name>/SKILL.md)
        if entry.is_dir() and recursive:
            for nested in discover(entry):
                sname = nested.parent.name
                rel_sub = nested.parent.relative_to(resolved).as_posix()
                seen_in_loc.setdefault(sname, []).append(rel_sub)
                if sname not in loc.skill_dirs:
                    loc.skill_dirs.append(sname)
                thash, _ = compute_tree_hash(nested.parent)
                if thash:
                    loc.skill_hashes[sname] = thash

    for sname, rel_list in seen_in_loc.items():
        if len(rel_list) > 1:
            loc.duplicate_paths[sname] = rel_list
    return loc


def diagnose(
    root: Path,
    *,
    only: list[str] | None = None,
    home: Path | None = None,
    scope: str = "project",
    check_drift: bool = True,
    custom_paths: dict[str, str] | None = None,
) -> Diagnosis:
    """Diagnose skill reachability, broken links, content drift, and duplicates.

    ``scope="project"`` (the default) inspects only project-relative paths, so
    diagnosing a repository reflects that repository — not whatever the
    operator happens to have installed in their own home directory.
    ``scope="user"`` inspects the user-level locations instead.
    """
    root = root.resolve()
    from .install import recover_interrupted_transactions
    from .state import state_dir

    if (state_dir(root, scope=scope, home=home) / "tmp").is_dir():
        recover_interrupted_transactions(root, scope=scope, home=home)

    diag = Diagnosis(root=root)
    eff_custom = load_custom_harness_paths(root, scope=scope, explicit=custom_paths)

    all_copies: dict[str, dict[str, str]] = {}  # skill_name -> {rel_dir: tree_hash}
    seen: set[str] = set()
    if scope == "project":
        for skill_md in discover(root):
            skill_dir = skill_md.parent
            name = skill_dir.name
            try:
                rel_dir = skill_dir.resolve().relative_to(root).as_posix()
            except ValueError:
                rel_dir = str(skill_dir)
            thash, _ = compute_tree_hash(skill_dir)
            if thash:
                all_copies.setdefault(name, {})[rel_dir] = thash

            # Always validate every discovered copy so a corrupted secondary copy is never missed
            copy_issues = validate(parse_skill(skill_md))
            diag.issues[str(skill_dir)] = copy_issues
            diag.skill_copies.setdefault(name, []).append(skill_dir)

            if name in seen:
                continue
            seen.add(name)
            diag.skills.append(skill_md)

    selected = only or list(harnesses.HARNESSES)
    loc_cache: dict[tuple[Path, bool], Location] = {}
    scanned_user_roots: set[Path] = set()

    for name in selected:
        h = harnesses.get(name)
        report = HarnessReport(
            harness=h.name,
            verified=h.verified,
            notes=list(h.notes),
            support_status=h.support_status,
            verification_level=h.verification_level,
        )
        wanted = list(h.project_paths if scope == "project" else h.user_paths)
        if h.name in eff_custom:
            custom_raw = eff_custom[h.name]
            if all(p.path != custom_raw for p in wanted):
                wanted.insert(0, harnesses.SkillPath(custom_raw, scope, "custom override"))
        seen_in_harness: dict[str, list[str]] = {}
        for p in wanted:
            resolved_p = resolve_path(p.path, p.scope, root, home)
            cache_key = (resolved_p, h.recursive)
            cached = loc_cache.get(cache_key)
            if cached is None:
                cached = scan_location(
                    h.name,
                    p.path,
                    p.scope,
                    root,
                    recursive=h.recursive,
                    home=home,
                )
                loc_cache[cache_key] = cached
            loc = Location(
                harness=h.name,
                raw_path=p.path if p.scope == "project" else str(resolved_p),
                resolved=cached.resolved,
                exists=cached.exists,
                skill_dirs=list(cached.skill_dirs),
                broken_links=list(cached.broken_links),
                is_bridge=cached.is_bridge,
                skill_hashes=dict(cached.skill_hashes),
                duplicate_paths=dict(cached.duplicate_paths),
            )
            if scope == "user" and loc.exists:
                scanned_user_roots.add(loc.resolved)
            report.locations.append(loc)
            report.reachable_skills.update(loc.skill_dirs)
            for sname in loc.skill_dirs:
                if sname in loc.duplicate_paths:
                    for sub_rel in loc.duplicate_paths[sname]:
                        seen_in_harness.setdefault(sname, []).append(f"{loc.raw_path}/{sub_rel}")
                elif not p.is_compatibility:
                    seen_in_harness.setdefault(sname, []).append(loc.raw_path)

        for sname, raw_paths in seen_in_harness.items():
            if len(raw_paths) > 1:
                report.duplicate_skills[sname] = raw_paths
                diag.duplicates.setdefault(h.name, {})[sname] = raw_paths

        diag.reports[h.name] = report

    if scope == "user":
        effective_home = (home or Path(os.path.expanduser("~"))).resolve()
        for uroot in sorted(scanned_user_roots):
            for skill_md in discover(uroot):
                skill_dir = skill_md.parent
                sname = skill_dir.name
                try:
                    rel_dir = "~/" + skill_dir.resolve().relative_to(effective_home).as_posix()
                except ValueError:
                    rel_dir = str(skill_dir)
                thash, _ = compute_tree_hash(skill_dir)
                if thash:
                    all_copies.setdefault(sname, {})[rel_dir] = thash
                copy_issues = validate(parse_skill(skill_md))
                diag.issues[str(skill_dir)] = copy_issues
                if skill_dir not in diag.skill_copies.setdefault(sname, []):
                    diag.skill_copies[sname].append(skill_dir)
                if sname not in seen:
                    seen.add(sname)
                    diag.skills.append(skill_md)

    # Content-drift check across copies of the same skill
    if check_drift:
        for sname, path_hashes in all_copies.items():
            unique_hashes = set(path_hashes.values())
            if len(unique_hashes) > 1:
                diag.drifted[sname] = path_hashes
                for rep in diag.reports.values():
                    if sname in rep.reachable_skills:
                        rep.drifted_skills.add(sname)

    # Actionable findings, ordered by how often they actually bite.
    for name, report in diag.reports.items():
        for loc in report.locations:
            if loc.status == "broken":
                diag.findings.append(
                    f"{name}: broken symlink(s) under {loc.resolved} — the target no longer exists "
                    f"({', '.join(Path(b).name for b in loc.broken_links)})"
                )

    for sname, path_hashes in sorted(diag.drifted.items()):
        locs_summary = ", ".join(f"{p} ({h[:8]})" for p, h in sorted(path_hashes.items()))
        diag.findings.append(
            f"skill {sname!r} has content drift across copies: {locs_summary}"
        )

    from .manifest import load_manifest
    from .state import load_state

    manifest = load_manifest(root) if scope == "project" else None
    manifest_skill_map = {s.name: s for s in manifest.skills} if (manifest and manifest.skills) else {}
    state_records = load_state(root, scope=scope, home=home)

    explicit_only_set = {harnesses.get(h).name for h in only} if only is not None else None
    default_project_set = {"claude-code", "codex", "cursor"}
    if scope == "project":
        for hname, rep in diag.reports.items():
            if any(loc.exists for loc in rep.locations):
                default_project_set.add(hname)
        if manifest and manifest.harnesses:
            for mh in manifest.harnesses:
                with contextlib.suppress(KeyError):
                    default_project_set.add(harnesses.get(mh).name)

    for skill_md in diag.skills:
        skill = skill_md.parent.name
        if explicit_only_set is not None:
            skill_required = explicit_only_set
        elif skill in manifest_skill_map and manifest_skill_map[skill].harnesses:
            skill_required = set()
            for mh in manifest_skill_map[skill].harnesses:
                with contextlib.suppress(KeyError):
                    skill_required.add(harnesses.get(mh).name)
        elif skill in state_records and state_records[skill].harnesses:
            skill_required = set()
            for sh in state_records[skill].harnesses:
                with contextlib.suppress(KeyError):
                    skill_required.add(harnesses.get(sh).name)
        elif scope == "user":
            skill_required = set()
        else:
            skill_required = default_project_set

        if not skill_required:
            continue
        missing = sorted(h for h in skill_required if h in diag.reports and not diag.reports[h].loads(skill))
        if not missing:
            continue
        loaded = sorted(h for h in skill_required if h in diag.reports and diag.reports[h].loads(skill))
        diag.findings.append(
            f"skill {skill!r} is not visible to: {', '.join(missing)}"
            + (f" (visible to: {', '.join(loaded)})" if loaded else " (visible to no harness)")
        )

    errors = {
        path: [i for i in issues if i.level == "error"]
        for path, issues in diag.issues.items()
    }
    seen_err_msgs: set[str] = set()
    for path, errs in errors.items():
        for issue in errs:
            msg = f"{Path(path).name}: {issue}"
            if msg not in seen_err_msgs:
                seen_err_msgs.add(msg)
                diag.findings.append(msg)

    return diag
