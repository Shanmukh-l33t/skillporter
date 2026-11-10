"""Install skills into harness directories, portably.

Two strategies, both git-safe:

``copy``   — real directories. Survives Docker builds, CI, and archive/export
             (git does not follow symlinks on every host, and Docker build
             contexts notoriously drop them).
``symlink`` — a single source of truth, convenient for local work; refused on
             platforms where it cannot work.

``bridge`` installs into ``.agents/skills`` (the emerging cross-harness
location that Codex and Cursor both read) and then links the harness-specific
directories at it, which is the layout the ecosystem is converging on.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import harnesses
from .diagnose import resolve_path


class InstallError(RuntimeError):
    """Raised when an install cannot be completed safely."""


@dataclass
class InstallResult:
    skill: str
    harness: str
    dest: Path
    action: str  # "created" | "updated" | "skipped" | "unchanged"
    detail: str = ""


def _copy_skill(src: Path, dest: Path, *, force: bool) -> str:
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink():
            # Never silently delete something we cannot identify as ours.
            if not force:
                raise InstallError(
                    f"{dest} is a symlink; re-run with --force to replace it, "
                    "or use --strategy symlink to manage links explicitly"
                )
            dest.unlink()
        elif force:
            shutil.rmtree(dest)
        else:
            raise InstallError(f"{dest} already exists; re-run with --force to overwrite")
    shutil.copytree(src, dest, symlinks=False)
    return "created"


def _link_skill(src: Path, dest: Path, *, force: bool) -> str:
    if dest.is_symlink():
        current = dest.resolve()
        if current == src.resolve():
            return "unchanged"
        if not force:
            raise InstallError(f"{dest} points at {current}; re-run with --force to repoint")
        dest.unlink()
    elif dest.exists():
        if not force:
            raise InstallError(f"{dest} exists as a real directory; re-run with --force to replace it")
        shutil.rmtree(dest)
    if os.name == "nt":
        # Windows symlinks need elevation or developer mode; fail loudly instead
        # of leaving a half-installed tree.
        raise InstallError("symlink strategy is not reliable on Windows; use --strategy copy")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(src.resolve(), target_is_directory=True)
    return "created"


def install(
    root: Path,
    skill_dir: Path,
    targets: list[str],
    *,
    strategy: str = "copy",
    scope: str = "project",
    force: bool = False,
    home: Path | None = None,
) -> list[InstallResult]:
    """Install one skill into the given harnesses.

    ``skill_dir`` is the source (must contain SKILL.md).
    """
    if not (skill_dir / "SKILL.md").is_file():
        raise InstallError(f"{skill_dir} is not a skill directory (no SKILL.md)")
    if strategy not in ("copy", "symlink"):
        raise InstallError(f"unknown strategy {strategy!r}; expected 'copy' or 'symlink'")

    skill_name = skill_dir.name
    results: list[InstallResult] = []
    written: dict[Path, str] = {}  # dest -> action already taken this run

    for target in targets:
        h = harnesses.get(target)  # raises with the known list on a typo
        paths = h.project_paths if scope == "project" else h.user_paths
        if not paths:
            raise InstallError(f"harness {target!r} has no {scope}-level skill path")

        # Install into the harness's primary documented location only; writing
        # the same skill into every compatibility path creates duplicates that
        # Cursor reports twice.
        primary = paths[0]
        base = resolve_path(primary.path, scope, root, home)
        dest = base / skill_name

        # Codex and Cursor share .agents/skills. Installing one skill for both
        # must write once, not fail on the second target.
        if dest in written:
            via = primary.path if scope == "project" else base
            results.append(InstallResult(
                skill=skill_name, harness=target, dest=dest, action="unchanged",
                detail=f"shared path already installed for {written[dest]} (copy via {via})",
            ))
            continue

        try:
            if strategy == "copy":
                action = _copy_skill(skill_dir, dest, force=force)
            else:
                action = _link_skill(skill_dir, dest, force=force)
        except InstallError as exc:
            raise InstallError(f"{target}: {exc}") from exc

        written[dest] = target
        results.append(InstallResult(
            skill=skill_name, harness=target, dest=dest, action=action,
            detail=f"{strategy} via {primary.path if scope == 'project' else base}",
        ))

    return results


def uninstall(
    root: Path,
    skill_name: str,
    targets: list[str],
    *,
    scope: str = "project",
    home: Path | None = None,
) -> list[InstallResult]:
    """Remove a skill from the given harnesses (never touches the source)."""
    results: list[InstallResult] = []
    for target in targets:
        h = harnesses.get(target)
        paths = h.project_paths if scope == "project" else h.user_paths
        base = resolve_path(paths[0].path, scope, root, home)
        dest = base / skill_name
        if dest.is_symlink():
            dest.unlink()
            results.append(InstallResult(skill_name, target, dest, "removed", "symlink"))
        elif dest.is_dir():
            shutil.rmtree(dest)
            results.append(InstallResult(skill_name, target, dest, "removed", "directory"))
        else:
            results.append(InstallResult(skill_name, target, dest, "skipped", "not installed"))
    return results
