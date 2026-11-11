"""Transactional Skill Installation, Planning, Crash Recovery, Ownership & Rollback.

Supports two primary strategies:
  * ``copy``    — Real directories. Survives Docker builds, CI, and git archives.
  * ``symlink`` — Portable relative symlinks for single-source-of-truth local dev.

Key guarantees:
  1. Shared destinations (such as ``.agents/skills`` shared by Codex, Cursor,
     Gemini CLI, Zed, Antigravity, OpenHands, and Goose) are written ONCE per run.
  2. Existing unmanaged files are never silently overwritten without ``--force``.
  3. Directory replacements are staged via ``.skillporter/tmp/`` with an atomic
     ``journal.json`` write-ahead log so interrupted writes or ``SIGKILL`` crashes
     can be automatically recovered via ``recover_interrupted_transactions()``.
  4. All skill names are validated as single safe path segments so ``install``,
     ``uninstall``, and ``rollback`` can never escape harness skill roots.
  5. Rollback verifies the backup's SHA-256 content tree hash before restoring
     so a corrupted backup directory can never overwrite a working installation.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .atomic import atomic_write_text, workspace_lock
from .diagnose import resolve_path
from .formats import render_adapted_skill
from .frontmatter import parse_skill
from .security import compute_tree_hash
from .state import (
    BackupEntry,
    is_managed_destination,
    load_state,
    record_installation,
    save_state,
    snapshot_skill_for_rollback,
    state_dir,
)


class InstallError(RuntimeError):
    """Raised when an install or uninstall cannot be completed safely."""


def validate_skill_name_segment(skill_name: str, base: Path | None = None) -> str:
    """Validate that *skill_name* is a single safe directory name segment.

    Prevents path traversal (e.g. ``../../victim``) in ``install``,
    ``uninstall``, and ``rollback_skill``.
    """
    clean = skill_name.strip()
    if (
        not clean
        or clean in (".", "..")
        or "/" in clean
        or "\\" in clean
        or "\x00" in clean
        or (len(clean) > 1 and clean[1] == ":")
    ):
        raise InstallError(
            f"invalid skill name {skill_name!r}: must be a single directory name without path separators or '..'"
        )
    if base is not None:
        resolved_base = base.resolve()
        raw_cand = resolved_base / clean
        candidate = raw_cand.resolve() if not raw_cand.is_symlink() else raw_cand
        if candidate.parent.resolve() != resolved_base:
            raise InstallError(f"skill destination {candidate} escapes harness directory {resolved_base}")
    return clean


def recover_interrupted_transactions(
    root: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
) -> list[str]:
    """Recover any orphaned transaction directories left behind by a prior hard crash (SIGKILL).

    Must be called while holding ``workspace_lock(root)`` or acquires it.
    Returns a list of human-readable recovery actions performed.
    """
    root = Path(root).resolve()
    sdir_root = state_dir(root, scope=scope, home=home)
    tmp_parent = sdir_root / "tmp"
    if not tmp_parent.is_dir():
        return []

    recovered: list[str] = []
    with workspace_lock(root):
        for txn_dir in sorted(tmp_parent.iterdir()):
            if not txn_dir.is_dir() or not txn_dir.name.startswith("txn-"):
                continue
            journal_file = txn_dir / "journal.json"
            if journal_file.is_file():
                try:
                    jdata = json.loads(journal_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    jdata = {}
                replaced = jdata.get("replaced", []) if isinstance(jdata, dict) else []
                for item in reversed(replaced):
                    if not isinstance(item, dict):
                        continue
                    dest_p = Path(str(item.get("dest", "")))
                    prev_p = Path(str(item.get("prev", "")))
                    if (prev_p.exists() or prev_p.is_symlink()) and not (dest_p.exists() or dest_p.is_symlink()):
                        dest_p.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(prev_p), str(dest_p))
                        recovered.append(f"restored interrupted destination {dest_p} from {prev_p.name}")
            shutil.rmtree(txn_dir, ignore_errors=True)
        with contextlib.suppress(OSError):
            if not any(tmp_parent.iterdir()):
                tmp_parent.rmdir()
    return recovered


def _write_txn_journal(
    txn_tmp_root: Path,
    created_in_txn: list[Path],
    replaced_in_txn: list[tuple[Path, Path]],
    pending_pair: tuple[Path, Path] | None = None,
) -> None:
    all_replaced = list(replaced_in_txn)
    if pending_pair is not None:
        all_replaced.append(pending_pair)
    payload = {
        "pid": os.getpid(),
        "created": [str(p) for p in created_in_txn],
        "replaced": [{"dest": str(d), "prev": str(prv)} for d, prv in all_replaced],
    }
    atomic_write_text(txn_tmp_root / "journal.json", json.dumps(payload, indent=2) + "\n")


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
    skill_names = [validate_skill_name_segment(d.name) for d in skill_dirs]
    plan = InstallPlan(
        root=root,
        scope=scope,
        strategy=strategy,
        skills=skill_names,
        harnesses=list(targets),
    )

    for skill_dir in skill_dirs:
        sname = validate_skill_name_segment(skill_dir.name)
        seen_dests: dict[Path, PlannedDestination] = {}
        for target in targets:
            h = harnesses.get(target)
            paths = h.project_paths if scope == "project" else h.user_paths
            if not paths:
                continue
            primary = paths[0]
            base = resolve_path(primary.path, scope, root, home)
            validate_skill_name_segment(sname, base)
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


def _verify_no_escaping_symlinks(src: Path) -> None:
    """Reject any skill tree containing a symlink that resolves outside *src* (or is broken).

    Structural filesystem escapes must NEVER be copied onto disk, even when
    ``--allow-risky`` or ``--force`` is passed.
    """
    resolved_src = src.resolve()
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        cdir = Path(dirpath)
        for name in [*dirnames, *filenames]:
            entry = cdir / name
            if entry.is_symlink():
                raw_link = os.readlink(entry)
                try:
                    target = entry.resolve()
                    target.relative_to(resolved_src)
                except (ValueError, OSError) as exc:
                    raise InstallError(
                        f"refusing to install {src.name!r}: symlink {entry.relative_to(src)} -> {raw_link!r} "
                        "escapes skill root"
                    ) from exc


def _stage_and_copy_skill(
    src: Path,
    dest: Path,
    *,
    force: bool,
    txn_tmp_root: Path,
    created_in_txn: list[Path],
    replaced_in_txn: list[tuple[Path, Path]],
) -> str:
    """Copy *src* to *dest* via a staging directory, preserving prior *dest* for rollback."""
    _verify_no_escaping_symlinks(src)
    existed = dest.exists() or dest.is_symlink()
    if existed:
        if dest.is_symlink():
            if not force:
                raise InstallError(
                    f"{dest} is a symlink; re-run with --force to replace it, "
                    "or use --strategy symlink to manage links explicitly"
                )
        elif not force:
            raise InstallError(f"{dest} already exists; re-run with --force to overwrite")
        else:
            if src.resolve() == dest.resolve():
                return "unchanged"

    txn_tmp_root.mkdir(parents=True, exist_ok=True)
    stage_dir = txn_tmp_root / f"stage-{uuid.uuid4().hex[:10]}"
    shutil.copytree(src, stage_dir, symlinks=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        prev_slot = txn_tmp_root / f"prev-{uuid.uuid4().hex[:10]}"
        _write_txn_journal(txn_tmp_root, created_in_txn, replaced_in_txn, pending_pair=(dest, prev_slot))
        shutil.move(str(dest), str(prev_slot))
        replaced_in_txn.append((dest, prev_slot))

    shutil.move(str(stage_dir), str(dest))
    return "created"


def _stage_and_link_skill(
    src: Path,
    dest: Path,
    *,
    force: bool,
    txn_tmp_root: Path,
    created_in_txn: list[Path],
    replaced_in_txn: list[tuple[Path, Path]],
) -> str:
    if os.name == "nt":
        raise InstallError("symlink strategy is not reliable on Windows; use --strategy copy")

    existed = dest.exists() or dest.is_symlink()
    if dest.is_symlink():
        try:
            current = dest.resolve()
        except OSError:
            current = None
        if current == src.resolve():
            return "unchanged"
        if not force:
            raise InstallError(f"{dest} points at {current}; re-run with --force to repoint")
    elif dest.exists() and not force:
        raise InstallError(f"{dest} exists as a real directory; re-run with --force to replace it")

    dest.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        txn_tmp_root.mkdir(parents=True, exist_ok=True)
        prev_slot = txn_tmp_root / f"prev-{uuid.uuid4().hex[:10]}"
        _write_txn_journal(txn_tmp_root, created_in_txn, replaced_in_txn, pending_pair=(dest, prev_slot))
        shutil.move(str(dest), str(prev_slot))
        replaced_in_txn.append((dest, prev_slot))

    try:
        rel_target = os.path.relpath(src.resolve(), dest.parent.resolve())
        dest.symlink_to(Path(rel_target), target_is_directory=True)
    except ValueError:
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
    """Install one skill into the given harnesses transactionally.

    ``skill_dir`` is the source (must contain SKILL.md).
    """
    root = root.resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise InstallError(f"{skill_dir} is not a skill directory (no SKILL.md)")
    if strategy not in ("copy", "symlink"):
        raise InstallError(f"unknown strategy {strategy!r}; expected 'copy' or 'symlink'")

    doc = parse_skill(skill_dir / "SKILL.md")
    skill_name = validate_skill_name_segment(skill_name_override or skill_dir.name)
    meta = doc.frontmatter.get("metadata")
    inferred_version = version or (
        str(meta.get("version", "1.0.0")) if isinstance(meta, dict) else "1.0.0"
    )

    results: list[InstallResult] = []
    written: dict[Path, str] = {}
    created_in_txn: list[Path] = []
    replaced_in_txn: list[tuple[Path, Path]] = []
    backup_entries: list[BackupEntry] = []

    sdir_root = state_dir(root, scope=scope, home=home)
    txn_tmp_root = sdir_root / "tmp" / f"txn-{uuid.uuid4().hex[:12]}"

    with workspace_lock(root):
        recover_interrupted_transactions(root, scope=scope, home=home)
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
                validate_skill_name_segment(skill_name, base)
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

                if (
                    record_state
                    and dest.exists()
                    and not dest.is_symlink()
                    and dest.resolve() != skill_dir.resolve()
                ):
                    bentry = snapshot_skill_for_rollback(
                        root, skill_name, dest, existing_record, scope=scope, home=home
                    )
                    if bentry and all(b.tree_hash != bentry.tree_hash for b in backup_entries):
                        backup_entries.append(bentry)

                existed_before = dest.exists() or dest.is_symlink()
                try:
                    if strategy == "copy":
                        action = _stage_and_copy_skill(
                            skill_dir,
                            dest,
                            force=force,
                            txn_tmp_root=txn_tmp_root,
                            created_in_txn=created_in_txn,
                            replaced_in_txn=replaced_in_txn,
                        )
                    else:
                        action = _stage_and_link_skill(
                            skill_dir,
                            dest,
                            force=force,
                            txn_tmp_root=txn_tmp_root,
                            created_in_txn=created_in_txn,
                            replaced_in_txn=replaced_in_txn,
                        )
                except InstallError as exc:
                    raise InstallError(f"{h.name}: {exc}") from exc

                if not existed_before and action == "created":
                    created_in_txn.append(dest)

                detail_suffix = f"{strategy} via {primary.path if scope == 'project' else base}"
                if adapt and h.capabilities.adapted_format and scope == "project":
                    rel_adapt, adapt_content = render_adapted_skill(doc, h.capabilities.adapted_format)
                    adapt_path = root / rel_adapt
                    atomic_write_text(adapt_path, adapt_content)
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
            # 1. Remove any brand-new destinations created in this failed transaction
            for created_dest in created_in_txn:
                if created_dest.is_symlink():
                    created_dest.unlink(missing_ok=True)
                elif created_dest.is_dir():
                    shutil.rmtree(created_dest, ignore_errors=True)
            # 2. Restore any pre-existing destinations that were replaced in this transaction
            for orig_dest, prev_slot in reversed(replaced_in_txn):
                if orig_dest.is_symlink():
                    orig_dest.unlink(missing_ok=True)
                elif orig_dest.exists():
                    shutil.rmtree(orig_dest, ignore_errors=True)
                if prev_slot.exists() or prev_slot.is_symlink():
                    shutil.move(str(prev_slot), str(orig_dest))
            shutil.rmtree(txn_tmp_root, ignore_errors=True)
            raise

        # Clean up temporary replaced slots after all targets succeeded
        shutil.rmtree(txn_tmp_root, ignore_errors=True)
        with contextlib.suppress(OSError):
            if not record_state and sdir_root.exists() and not any((sdir_root / "tmp").iterdir()):
                (sdir_root / "tmp").rmdir()

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
                backup_entries=backup_entries,
                home=home,
            )

    return results


def install_many(
    root: Path,
    skill_dirs: list[Path],
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
) -> list[InstallResult]:
    """Install multiple skills as a single atomic batch transaction.

    Checks all conflicts across all skills upfront before modifying disk, and if
    any skill fails mid-batch, rolls back every skill installed earlier in the batch.
    """
    root = root.resolve()
    with workspace_lock(root):
        plan = plan_install(root, skill_dirs, targets, strategy=strategy, scope=scope, force=force, home=home)
        if plan.conflicts and not force:
            raise InstallError("; ".join(plan.conflicts))

        pre_state = load_state(root, scope=scope, home=home)
        batch_results: list[InstallResult] = []
        completed_skills: list[tuple[str, bool]] = []  # (skill_name, existed_in_pre_state)

        try:
            for sdir in skill_dirs:
                sname = validate_skill_name_segment(sdir.name)
                existed_in_state = sname in pre_state
                res = install(
                    root,
                    sdir,
                    targets,
                    strategy=strategy,
                    scope=scope,
                    force=force,
                    home=home,
                    source=source,
                    resolved_commit=resolved_commit,
                    version=version,
                    record_state=record_state,
                    adapt=adapt,
                )
                batch_results.extend(res)
                completed_skills.append((sname, existed_in_state))
        except Exception:
            for sname, existed_in_state in reversed(completed_skills):
                cur_records = load_state(root, scope=scope, home=home)
                rec = cur_records.get(sname)
                if rec and rec.history and existed_in_state:
                    with contextlib.suppress(Exception):
                        rollback_skill(root, sname, scope=scope, home=home)
                else:
                    with contextlib.suppress(Exception):
                        uninstall(root, sname, targets, scope=scope, home=home, record_state=record_state)
            save_state(root, pre_state, scope=scope, home=home)
            raise

        return batch_results


def uninstall(
    root: Path,
    skill_name: str,
    targets: list[str],
    *,
    scope: str = "project",
    home: Path | None = None,
    record_state: bool = False,
) -> list[InstallResult]:
    """Remove a skill from the given harnesses (never touches the source or outside paths)."""
    root = root.resolve()
    skill_name = validate_skill_name_segment(skill_name)
    results: list[InstallResult] = []
    removed_dests: set[str] = set()

    with workspace_lock(root):
        recover_interrupted_transactions(root, scope=scope, home=home)
        for target in targets:
            h = harnesses.get(target)
            paths = h.project_paths if scope == "project" else h.user_paths
            if not paths:
                results.append(InstallResult(skill_name, h.name, root, "skipped", f"no {scope} path"))
                continue
            base = resolve_path(paths[0].path, scope, root, home)
            validate_skill_name_segment(skill_name, base)
            dest = base / skill_name
            if dest.is_symlink():
                with contextlib.suppress(OSError):
                    removed_dests.add(str(dest.resolve()))
                dest.unlink()
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
    skill_name = validate_skill_name_segment(skill_name)

    with workspace_lock(root):
        recover_interrupted_transactions(root, scope=scope, home=home)
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

        actual_hash, _ = compute_tree_hash(bdir)
        if chosen.tree_hash and actual_hash != chosen.tree_hash:
            raise InstallError(
                f"backup {chosen.backup_id!r} for skill {skill_name!r} is corrupted "
                f"(expected sha256 {chosen.tree_hash[:12]}, got {actual_hash[:12] or 'empty'})"
            )

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
