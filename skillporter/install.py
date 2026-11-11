"""Transactional Skill Installation, Planning, Ownership, and Rollback Engine.

Supports two primary strategies:
  * ``copy``    — Real directories. Survives Docker builds, CI, and git archives.
  * ``symlink`` — Portable relative symlinks for single-source-of-truth local dev.

Key guarantees:
  1. Shared destinations (such as ``.agents/skills`` shared by Codex, Cursor,
     Gemini CLI, Zed, Antigravity, OpenHands, and Goose) are written ONCE per run.
  2. Existing unmanaged files are never silently overwritten without ``--force``.
  3. Existing managed installations are snapshotted to ``.skillporter/backups/``
     before update/overwrite so partial failures automatically roll back and
     users can run ``skillporter rollback <skill>``.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .diagnose import resolve_path
from .formats import render_adapted_skill
from .frontmatter import parse_skill
from .state import (
    is_managed_destination,
    load_state,
    record_installation,
    save_state,
    snapshot_skill_for_rollback,
)


class InstallError(RuntimeError):
    """Raised when an install cannot be completed safely."""


@dataclass
class InstallResult:
    skill: str
    harness: str
    dest: Path
    action: str  # "created" | "updated" | "skipped" | "unchanged" | "removed" | "rolled-back"
    detail: str = ""


@dataclass
class PlannedDestination:
    """One destination in an installation plan."""

    harness: str
    primary_path: str
    resolved_dest: Path
    shared_with: list[str] = field(default_factory=list)
    exists: bool = False
    managed: bool = False
    conflict: bool = False


@dataclass
class InstallPlan:
    """Previewable installation plan across skills and harnesses."""

    root: Path
    scope: str
    strategy: str
    skills: list[str]
    harnesses: list[str]
    destinations: list[PlannedDestination] = field(default_factory=list)
    shared_count: int = 0
    conflicts: list[str] = field(default_factory=list)


def plan_install(
    root: Path,
    skill_dirs: list[Path],
    targets: list[str],
    *,
    strategy: str = "copy",
    scope: str = "project",
    force: bool = False,
    allow_managed_update: bool = False,
    home: Path | None = None,
) -> InstallPlan:
    """Compute an installation plan without modifying the filesystem."""
    root = root.resolve()
    skill_names = [d.name for d in skill_dirs]
    plan = InstallPlan(
        root=root,
        scope=scope,
        strategy=strategy,
        skills=skill_names,
        harnesses=list(targets),
    )

    for skill_dir in skill_dirs:
        sname = skill_dir.name
        seen_dests: dict[Path, PlannedDestination] = {}
        for target in targets:
            h = harnesses.get(target)
            paths = h.project_paths if scope == "project" else h.user_paths
            if not paths:
                continue
            primary = paths[0]
            base = resolve_path(primary.path, scope, root, home)
            dest = (base / sname).resolve() if not (base / sname).is_symlink() else (base / sname)

            if dest in seen_dests:
                seen_dests[dest].shared_with.append(h.name)
                plan.shared_count += 1
                continue

            exists = dest.exists() or dest.is_symlink()
            managed = is_managed_destination(root, sname, dest, scope=scope, home=home) if exists else False
            conflict = False
            if exists and not force and not (allow_managed_update and managed):
                conflict = True
                plan.conflicts.append(f"{h.name}: {dest} already exists")

            pdest = PlannedDestination(
                harness=h.name,
                primary_path=primary.path,
                resolved_dest=dest,
                exists=exists,
                managed=managed,
                conflict=conflict,
            )
            seen_dests[dest] = pdest
            plan.destinations.append(pdest)

    return plan


def _copy_skill(src: Path, dest: Path, *, force: bool) -> str:
    existed = dest.exists() or dest.is_symlink()
    if existed:
        if dest.is_symlink():
            if not force:
                raise InstallError(
                    f"{dest} is a symlink; re-run with --force to replace it, "
                    "or use --strategy symlink to manage links explicitly"
                )
            dest.unlink()
        elif force:
            if src.resolve() == dest.resolve():
                return "unchanged"
            shutil.rmtree(dest)
        else:
            raise InstallError(f"{dest} already exists; re-run with --force to overwrite")
    shutil.copytree(src, dest, symlinks=False)
    return "created"


def _link_skill(src: Path, dest: Path, *, force: bool) -> str:
    if dest.is_symlink():
        try:
            current = dest.resolve()
        except OSError:
            current = None
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
        raise InstallError("symlink strategy is not reliable on Windows; use --strategy copy")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        rel_target = os.path.relpath(src.resolve(), dest.parent.resolve())
        dest.symlink_to(Path(rel_target), target_is_directory=True)
    except ValueError:
        # Different drive on POSIX/Windows fallback
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
    source: str = "",
    resolved_commit: str = "",
    version: str = "",
    record_state: bool = False,
    adapt: bool = False,
    skill_name_override: str = "",
) -> list[InstallResult]:
    """Install one skill into the given harnesses.

    ``skill_dir`` is the source (must contain SKILL.md).
    """
    root = root.resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise InstallError(f"{skill_dir} is not a skill directory (no SKILL.md)")
    if strategy not in ("copy", "symlink"):
        raise InstallError(f"unknown strategy {strategy!r}; expected 'copy' or 'symlink'")

    doc = parse_skill(skill_dir / "SKILL.md")
    skill_name = skill_name_override or skill_dir.name
    meta = doc.frontmatter.get("metadata")
    inferred_version = version or (
        str(meta.get("version", "1.0.0")) if isinstance(meta, dict) else "1.0.0"
    )

    results: list[InstallResult] = []
    written: dict[Path, str] = {}  # dest -> first harness that wrote it
    created_in_txn: list[Path] = []
    backup_entry = None
    existing_records = load_state(root, scope=scope, home=home) if record_state else {}
    existing_record = existing_records.get(skill_name)

    try:
        for target in targets:
            h = harnesses.get(target)
            paths = h.project_paths if scope == "project" else h.user_paths
            if not paths:
                raise InstallError(f"harness {target!r} has no {scope}-level skill path")

            primary = paths[0]
            base = resolve_path(primary.path, scope, root, home)
            dest = base / skill_name

            if dest in written:
                via = primary.path if scope == "project" else base
                results.append(
                    InstallResult(
                        skill=skill_name,
                        harness=h.name,
                        dest=dest,
                        action="unchanged",
                        detail=f"shared path already installed for {written[dest]} ({strategy} via {via})",
                    )
                )
                continue

            if record_state and dest.exists() and not dest.is_symlink() and backup_entry is None:
                backup_entry = snapshot_skill_for_rollback(
                    root, skill_name, dest, existing_record, scope=scope, home=home
                )

            existed_before = dest.exists() or dest.is_symlink()
            try:
                if strategy == "copy":
                    action = _copy_skill(skill_dir, dest, force=force)
                else:
                    action = _link_skill(skill_dir, dest, force=force)
            except InstallError as exc:
                raise InstallError(f"{h.name}: {exc}") from exc

            if not existed_before:
                created_in_txn.append(dest)

            detail_suffix = f"{strategy} via {primary.path if scope == 'project' else base}"
            if adapt and h.capabilities.adapted_format and scope == "project":
                rel_adapt, adapt_content = render_adapted_skill(doc, h.capabilities.adapted_format)
                adapt_path = root / rel_adapt
                adapt_path.parent.mkdir(parents=True, exist_ok=True)
                adapt_path.write_text(adapt_content, encoding="utf-8")
                detail_suffix += f" + adapted {rel_adapt}"

            written[dest] = h.name
            results.append(
                InstallResult(
                    skill=skill_name,
                    harness=h.name,
                    dest=dest,
                    action=action,
                    detail=detail_suffix,
                )
            )
    except Exception:
        # Transactional rollback of newly created destinations on mid-install failure
        for created_dest in created_in_txn:
            if created_dest.is_symlink():
                created_dest.unlink(missing_ok=True)
            elif created_dest.is_dir():
                shutil.rmtree(created_dest, ignore_errors=True)
        raise

    if record_state and written:
        record_installation(
            root,
            skill_name=skill_name,
            source=source or str(skill_dir),
            skill_dir=skill_dir,
            harnesses=[h_obj.harness for h_obj in results],
            destinations=list(written.keys()),
            strategy=strategy,
            scope=scope,
            resolved_commit=resolved_commit,
            version=inferred_version,
            backup_entry=backup_entry,
            home=home,
        )

    return results


def uninstall(
    root: Path,
    skill_name: str,
    targets: list[str],
    *,
    scope: str = "project",
    home: Path | None = None,
    record_state: bool = False,
) -> list[InstallResult]:
    """Remove a skill from the given harnesses (never touches the source)."""
    root = root.resolve()
    results: list[InstallResult] = []
    removed_dests: set[str] = set()

    for target in targets:
        h = harnesses.get(target)
        paths = h.project_paths if scope == "project" else h.user_paths
        if not paths:
            results.append(InstallResult(skill_name, h.name, root, "skipped", f"no {scope} path"))
            continue
        base = resolve_path(paths[0].path, scope, root, home)
        dest = base / skill_name
        if dest.is_symlink():
            dest.unlink()
            removed_dests.add(str(dest.resolve()))
            results.append(InstallResult(skill_name, h.name, dest, "removed", "symlink"))
        elif dest.is_dir():
            removed_dests.add(str(dest.resolve()))
            shutil.rmtree(dest)
            results.append(InstallResult(skill_name, h.name, dest, "removed", "directory"))
        else:
            results.append(InstallResult(skill_name, h.name, dest, "skipped", "not installed"))

    if record_state and removed_dests:
        records = load_state(root, scope=scope, home=home)
        rec = records.get(skill_name)
        if rec:
            rec.destinations = [d for d in rec.destinations if d not in removed_dests]
            removed_harnesses = {r.harness for r in results if r.action == "removed"}
            rec.harnesses = [hn for hn in rec.harnesses if hn not in removed_harnesses]
            if not rec.destinations:
                records.pop(skill_name, None)
            save_state(root, records, scope=scope, home=home)

    return results


def rollback_skill(
    root: Path,
    skill_name: str,
    *,
    backup_id: str = "",
    scope: str = "project",
    home: Path | None = None,
) -> list[InstallResult]:
    """Restore a skill to its previous backup snapshot across all tracked destinations."""
    root = root.resolve()
    records = load_state(root, scope=scope, home=home)
    rec = records.get(skill_name)
    if not rec or not rec.history:
        raise InstallError(f"no backup history available to roll back skill {skill_name!r}")

    chosen = None
    if backup_id:
        for entry in reversed(rec.history):
            if entry.backup_id == backup_id or entry.backup_id.startswith(backup_id):
                chosen = entry
                break
        if not chosen:
            raise InstallError(f"backup {backup_id!r} not found for skill {skill_name!r}")
    else:
        chosen = rec.history[-1]

    bdir = Path(chosen.backup_dir)
    if not bdir.is_dir():
        raise InstallError(f"backup directory {bdir} is missing on disk")

    targets = rec.harnesses or ["claude-code", "codex", "cursor"]
    results = install(
        root,
        bdir,
        targets,
        strategy="copy",
        scope=scope,
        force=True,
        home=home,
        source=chosen.source,
        resolved_commit=chosen.resolved_commit,
        version=chosen.version,
        record_state=False,
        skill_name_override=skill_name,
    )
    for r in results:
        if r.action == "created":
            r.action = "rolled-back"
        r.detail = f"restored backup {chosen.backup_id}"

    rec.tree_hash = chosen.tree_hash
    rec.version = chosen.version
    rec.resolved_commit = chosen.resolved_commit
    if chosen == rec.history[-1]:
        rec.history.pop()
    save_state(root, records, scope=scope, home=home)
    return results
