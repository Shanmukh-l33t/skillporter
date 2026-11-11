"""Diagnose why a skill does or does not load in a given harness, including
content-drift and duplicate-loading detection.

This is the part competing sync tools skip: they copy files and report success,
leaving the author to discover by hand that (say) Codex never reads
``.claude/skills``, or that two copied directories have silently drifted out of
sync. skillporter resolves every harness path, checks reachability, verifies
SHA-256 content hashes across copies, detects duplicate loading within the same
harness, and names the exact reason.
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
        """Return 'drifted', 'duplicate', 'yes', or 'MISSING'."""
        if skill not in self.reachable_skills:
            return "MISSING"
        if skill in self.drifted_skills:
            return "DRIFT"
        if skill in self.duplicate_skills:
            return "DUPLICATE"
        return "yes"


@dataclass
class Diagnosis:
    """Full result of a diagnose run."""

    root: Path
    skills: list[Path] = field(default_factory=list)
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

    for entry in entries:
        if entry.is_symlink() and not entry.exists():
            loc.broken_links.append(str(entry))
            continue
        if (entry / _SKILL_FILE).is_file():
            loc.skill_dirs.append(entry.name)
            thash, _ = compute_tree_hash(entry)
            if thash:
                loc.skill_hashes[entry.name] = thash
            continue
        # Nested category directories (e.g. Hermes $HERMES_HOME/skills/<category>/<name>/SKILL.md)
        if entry.is_dir() and recursive:
            for nested in sorted(entry.rglob(_SKILL_FILE)):
                sname = nested.parent.name
                if sname not in loc.skill_dirs:
                    loc.skill_dirs.append(sname)
                thash, _ = compute_tree_hash(nested.parent)
                if thash:
                    loc.skill_hashes[sname] = thash
    return loc


def diagnose(
    root: Path,
    *,
    only: list[str] | None = None,
    home: Path | None = None,
    scope: str = "project",
    check_drift: bool = True,
) -> Diagnosis:
    """Diagnose skill reachability, broken links, content drift, and duplicates.

    ``scope="project"`` (the default) inspects only project-relative paths, so
    diagnosing a repository reflects that repository — not whatever the
    operator happens to have installed in their own home directory.
    ``scope="user"`` inspects the user-level locations instead.
    """
    root = root.resolve()
    diag = Diagnosis(root=root)

    # Track every copy of every skill under root so we can detect content drift
    # across copies even while deduplicating the skill list by name.
    all_copies: dict[str, dict[str, str]] = {}  # skill_name -> {rel_dir: tree_hash}
    seen: set[str] = set()
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

        if name in seen:
            continue
        seen.add(name)
        diag.skills.append(skill_md)
        diag.issues[str(skill_dir)] = validate(parse_skill(skill_md))

    selected = only or list(harnesses.HARNESSES)
    for name in selected:
        h = harnesses.get(name)
        report = HarnessReport(
            harness=h.name,
            verified=h.verified,
            notes=list(h.notes),
            support_status=h.support_status,
            verification_level=h.verification_level,
        )
        wanted = h.project_paths if scope == "project" else h.user_paths
        seen_in_harness: dict[str, list[str]] = {}
        for p in wanted:
            loc = scan_location(
                h.name,
                p.path,
                p.scope,
                root,
                recursive=h.recursive,
                home=home,
            )
            report.locations.append(loc)
            report.reachable_skills.update(loc.skill_dirs)
            for sname in loc.skill_dirs:
                seen_in_harness.setdefault(sname, []).append(loc.raw_path)

        # Duplicate check: only flag if a skill exists in >=2 *non-compatibility*
        # or distinct physical paths read by the same harness (e.g. .agents/skills and .cursor/skills)
        for sname, raw_paths in seen_in_harness.items():
            if len(raw_paths) > 1:
                report.duplicate_skills[sname] = raw_paths
                diag.duplicates.setdefault(h.name, {})[sname] = raw_paths

        diag.reports[h.name] = report

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

    if only is not None:
        required_set = {harnesses.get(h).name for h in only}
    elif scope == "user":
        required_set = set(harnesses.CORE_HARNESS_NAMES)
    else:
        required_set = {"claude-code", "codex", "cursor"}
        for hname, rep in diag.reports.items():
            if any(loc.exists for loc in rep.locations):
                required_set.add(hname)
        from .manifest import load_manifest

        manifest = load_manifest(root)
        if manifest and manifest.harnesses:
            for mh in manifest.harnesses:
                with contextlib.suppress(KeyError):
                    required_set.add(harnesses.get(mh).name)

    for skill_md in diag.skills:
        skill = skill_md.parent.name
        missing = sorted(h for h in required_set if h in diag.reports and not diag.reports[h].loads(skill))
        if not missing:
            continue
        loaded = sorted(h for h in required_set if h in diag.reports and diag.reports[h].loads(skill))
        diag.findings.append(
            f"skill {skill!r} is not visible to: {', '.join(missing)}"
            + (f" (visible to: {', '.join(loaded)})" if loaded else " (visible to no harness)")
        )

    errors = {
        path: [i for i in issues if i.level == "error"]
        for path, issues in diag.issues.items()
    }
    for path, errs in errors.items():
        for issue in errs:
            diag.findings.append(f"{Path(path).name}: {issue}")

    return diag
