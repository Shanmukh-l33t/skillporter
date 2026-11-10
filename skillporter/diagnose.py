"""Diagnose why a skill does or does not load in a given harness.

This is the part competing sync tools skip: they copy files and report success,
leaving the author to discover by hand that (say) Codex never reads
``.claude/skills``. skillporter resolves every harness path, checks whether the
skill is reachable, and names the exact reason it is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .frontmatter import Issue, parse_skill, validate

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

    def loads(self, skill: str) -> bool:
        return skill in self.reachable_skills


@dataclass
class Diagnosis:
    """Full result of a diagnose run."""

    root: Path
    skills: list[Path] = field(default_factory=list)
    reports: dict[str, HarnessReport] = field(default_factory=dict)
    issues: dict[str, list[Issue]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)

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
            continue
        # A bridge directory (e.g. .agents/skills/* -> real skill dirs).
        if entry.is_dir() and recursive:
            for nested in sorted(entry.rglob(_SKILL_FILE)):
                loc.skill_dirs.append(nested.parent.name)
                break
    return loc


def diagnose(root: Path, *, only: list[str] | None = None, home: Path | None = None,
             scope: str = "project") -> Diagnosis:
    """Diagnose skill reachability for every (or selected) harness.

    ``scope="project"`` (the default) inspects only project-relative paths, so
    diagnosing a repository reflects that repository — not whatever the
    operator happens to have installed in their own home directory.
    ``scope="user"`` inspects the user-level locations instead.
    """
    root = root.resolve()
    diag = Diagnosis(root=root)

    from .frontmatter import discover

    # Deduplicate: after an install the same skill can exist in several harness
    # roots. The report is per *skill name*, not per file on disk.
    seen: set[str] = set()
    for skill_md in discover(root):
        name = skill_md.parent.name
        if name in seen:
            continue
        seen.add(name)
        diag.skills.append(skill_md)
        diag.issues[str(skill_md.parent)] = validate(parse_skill(skill_md))

    selected = only or list(harnesses.HARNESSES)
    for name in selected:
        h = harnesses.get(name)
        report = HarnessReport(harness=h.name, verified=h.verified, notes=list(h.notes))
        wanted = h.project_paths if scope == "project" else h.user_paths
        for p in wanted:
            loc = scan_location(
                h.name, p.path, p.scope, root,
                recursive=h.recursive, home=home,
            )
            report.locations.append(loc)
            report.reachable_skills.update(loc.skill_dirs)
        diag.reports[h.name] = report

    # Actionable findings, ordered by how often they actually bite.
    for name, report in diag.reports.items():
        for loc in report.locations:
            if loc.status == "broken":
                diag.findings.append(
                    f"{name}: broken symlink(s) under {loc.resolved} — the target no longer exists "
                    f"({', '.join(Path(b).name for b in loc.broken_links)})"
                )

    for skill_md in diag.skills:
        skill = skill_md.parent.name
        missing = diag.missing_in(skill)
        if not missing:
            continue
        loaded = [h for h, r in diag.reports.items() if r.loads(skill)]
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
