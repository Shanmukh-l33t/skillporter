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
  5. Recursive category directories (e.g. Hermes ``$HERMES_HOME/skills/<cat>/<skill>``
     where ``<cat> == <skill>``) are preserved safely without clobbering parent categories.
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
from .diagnose import load_custom_harness_paths, resolve_path, select_harness_install_raw_path
from .formats import render_adapted_skill
from .frontmatter import discover, parse_skill
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


def _verify_harness_base_within_scope(
    base: Path, scope: str, root: Path, home: Path | None = None
) -> None:
    """Reject harness skill directories that escape their scope root via symlinks."""
    resolved_base = base.resolve()
    if scope == "project":
        resolved_root = root.resolve()
        if not resolved_base.is_relative_to(resolved_root):
            raise InstallError(
                f"harness skill directory {base} ({resolved_base}) escapes workspace root {resolved_root} via symlink"
            )
    elif scope == "user":
        allowed_roots = [(home or Path(os.path.expanduser("~"))).resolve()]
        hermes_env = os.environ.get("HERMES_HOME", "").strip()
        if hermes_env:
            allowed_roots.append(Path(hermes_env).expanduser().resolve())
        if not any(resolved_base.is_relative_to(ar) for ar in allowed_roots):
            raise InstallError(
                f"user harness skill directory {base} ({resolved_base}) escapes user home scope via symlink"
            )


def _resolve_harness_skill_dest(
    base: Path, skill_name: str, *, src: Path | None = None, recursive: bool = False
) -> Path:
    """Compute the destination directory for *skill_name* under *base*.

    For recursive harnesses (such as ``hermes`` where skills live under
    ``skills/<category>/<name>``), if *src* is already nested inside *base* or
    if ``base / skill_name`` is an existing category directory containing nested
    skills rather than a ``SKILL.md`` root, preserve the nested path so category
    directories are never overwritten by a skill of the same name.
    """
    validate_skill_name_segment(skill_name, base)
    direct_dest = base / skill_name
    if not recursive:
        return direct_dest

    if src is not None:
        resolved_src = src.resolve()
        resolved_base = base.resolve()
        if resolved_src.is_relative_to(resolved_base) and resolved_src.name == skill_name:
            return resolved_src
        if direct_dest.exists() and resolved_src.is_relative_to(direct_dest.resolve()):
            return resolved_src

    if (
        direct_dest.is_dir()
        and not direct_dest.is_symlink()
        and not (direct_dest / "SKILL.md").is_file()
        and discover(direct_dest)
    ):
        return direct_dest / skill_name

    return direct_dest


def _is_safe_recovery_target(cand: Path, allowed_roots: list[Path]) -> bool:
    """Verify a journal path resolves strictly beneath an allowed scope root (never the root itself or .git)."""
    if not str(cand) or ".git" in cand.parts:
        return False
    try:
        resolved_parent = cand.parent.resolve()
        check_target = (resolved_parent / cand.name) if cand.is_symlink() else cand.resolve()
    except OSError:
        return False
    for ar in allowed_roots:
        if check_target == ar:
            return False
        if check_target.is_relative_to(ar) and resolved_parent.is_relative_to(ar):
            return True
    return False


def _is_safe_prev_slot(prev_p: Path, txn_dir_resolved: Path) -> bool:
    """Verify a journal `prev` slot resides directly inside the active transaction temp directory."""
    if not prev_p.name.startswith("prev-") or prev_p.is_symlink():
        try:
            if prev_p.parent.resolve() != txn_dir_resolved or not prev_p.name.startswith("prev-"):
                return False
        except OSError:
            return False
    try:
        return prev_p.parent.resolve() == txn_dir_resolved
    except OSError:
        return False


def recover_interrupted_transactions(
    root: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
) -> list[str]:
    """Recover any orphaned transaction directories left behind by a prior hard crash (SIGKILL)."""
    root = Path(root).resolve()
    sdir_root = state_dir(root, scope=scope, home=home)
    tmp_parent = sdir_root / "tmp"
    if not tmp_parent.is_dir():
        return []

    if scope == "user":
        allowed_roots = [(home or Path(os.path.expanduser("~"))).resolve()]
        hermes_env = os.environ.get("HERMES_HOME", "").strip()
        if hermes_env:
            allowed_roots.append(Path(hermes_env).expanduser().resolve())
    else:
        allowed_roots = [root]

    recovered: list[str] = []
    with workspace_lock(root):
        for txn_dir in sorted(tmp_parent.iterdir()):
            if not txn_dir.is_dir() or txn_dir.is_symlink() or not txn_dir.name.startswith("txn-"):
                continue
            txn_resolved = txn_dir.resolve()
            journal_file = txn_dir / "journal.json"
            if journal_file.is_file() and not journal_file.is_symlink():
                try:
                    jdata = json.loads(journal_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    jdata = {}
                replaced = jdata.get("replaced", []) if isinstance(jdata, dict) else []
                created = jdata.get("created", []) if isinstance(jdata, dict) else []
                for item in reversed(replaced):
                    if not isinstance(item, dict):
                        continue
                    dest_p = Path(str(item.get("dest", "")))
                    prev_p = Path(str(item.get("prev", "")))
                    if not _is_safe_prev_slot(prev_p, txn_resolved) or not _is_safe_recovery_target(
                        dest_p, allowed_roots
                    ):
                        continue
                    if prev_p.exists() or prev_p.is_symlink():
                        if dest_p.is_symlink():
                            dest_p.unlink(missing_ok=True)
                        elif dest_p.is_dir():
                            shutil.rmtree(dest_p, ignore_errors=True)
                        elif dest_p.exists():
                            dest_p.unlink(missing_ok=True)
                        dest_p.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(prev_p), str(dest_p))
                        recovered.append(f"restored interrupted destination {dest_p} from {prev_p.name}")
                for created_item in reversed(created):
                    cpath = Path(str(created_item))
                    if not _is_safe_recovery_target(cpath, allowed_roots):
                        continue
                    if cpath.is_symlink():
                        cpath.unlink(missing_ok=True)
                        recovered.append(f"removed uncommitted symlink {cpath}")
                    elif cpath.is_dir():
                        shutil.rmtree(cpath, ignore_errors=True)
                        recovered.append(f"removed uncommitted directory {cpath}")
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
    pending_created: Path | None = None,
) -> None:
    all_created = list(created_in_txn)
    if pending_created is not None and pending_created not in all_created:
        all_created.append(pending_created)
    all_replaced = list(replaced_in_txn)
    if pending_pair is not None:
        all_replaced.append(pending_pair)
    payload = {
        "pid": os.getpid(),
        "created": [str(p) for p in all_created],
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
    on_conflict: str = "fail",
    allow_managed_update: bool = False,
    home: Path | None = None,
    custom_paths: dict[str, str] | None = None,
    isolated: bool = False,
) -> InstallPlan:
    """Compute an installation plan without modifying the filesystem."""
    root = root.resolve()
    eff_conflict = "overwrite" if force else (on_conflict or "fail")
    eff_custom = load_custom_harness_paths(root, scope=scope, explicit=custom_paths)
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
            raw_primary = select_harness_install_raw_path(
                h, scope, custom_paths=eff_custom, isolated=isolated
            )
            if not raw_primary:
                continue
            base = resolve_path(raw_primary, scope, root, home)
            _verify_harness_base_within_scope(base, scope, root, home)
            raw_dest = _resolve_harness_skill_dest(base, sname, src=skill_dir, recursive=h.recursive)
            dest = raw_dest.resolve() if not raw_dest.is_symlink() else raw_dest

            if dest in seen_dests:
                seen_dests[dest].shared_with.append(h.name)
                plan.shared_count += 1
                continue

            exists = dest.exists() or dest.is_symlink()
            managed = is_managed_destination(root, sname, dest, scope=scope, home=home) if exists else False
            conflict = False
            if exists and eff_conflict == "fail" and not (allow_managed_update and managed):
                conflict = True
                plan.conflicts.append(f"{h.name}: {dest} already exists")

            pdest = PlannedDestination(
                harness=h.name,
                primary_path=raw_primary,
                resolved_dest=dest,
                exists=exists,
                managed=managed,
                conflict=conflict,
            )
            seen_dests[dest] = pdest
            plan.destinations.append(pdest)

    return plan


def _verify_no_escaping_symlinks(src: Path) -> None:
    """Reject any skill tree containing a symlink that resolves outside *src* (or is broken)."""
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
            resolved_src = src.resolve()
            resolved_dest = dest.resolve()
            if resolved_src == resolved_dest or resolved_src.is_relative_to(resolved_dest):
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
    else:
        _write_txn_journal(txn_tmp_root, created_in_txn, replaced_in_txn, pending_created=dest)

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
    elif dest.exists():
        if src.resolve() == dest.resolve() or src.resolve().is_relative_to(dest.resolve()):
            return "unchanged"
        if not force:
            raise InstallError(f"{dest} exists as a real directory; re-run with --force to replace it")

    dest.parent.mkdir(parents=True, exist_ok=True)
    txn_tmp_root.mkdir(parents=True, exist_ok=True)
    if existed:
        prev_slot = txn_tmp_root / f"prev-{uuid.uuid4().hex[:10]}"
        _write_txn_journal(txn_tmp_root, created_in_txn, replaced_in_txn, pending_pair=(dest, prev_slot))
        shutil.move(str(dest), str(prev_slot))
        replaced_in_txn.append((dest, prev_slot))
    else:
        _write_txn_journal(txn_tmp_root, created_in_txn, replaced_in_txn, pending_created=dest)

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
    on_conflict: str = "fail",
    home: Path | None = None,
    source: str = "",
    resolved_commit: str = "",
    version: str = "",
    record_state: bool = False,
    adapt: bool = False,
    skill_name_override: str = "",
    custom_paths: dict[str, str] | None = None,
    isolated: bool = False,
) -> list[InstallResult]:
    """Install one skill into the given harnesses transactionally."""
    root = root.resolve()
    eff_conflict = "overwrite" if force else (on_conflict or "fail")
    if eff_conflict not in ("fail", "skip", "overwrite"):
        raise InstallError(f"unknown conflict policy {eff_conflict!r}; expected 'fail', 'skip', or 'overwrite'")
    eff_force = eff_conflict == "overwrite"
    eff_custom = load_custom_harness_paths(root, scope=scope, explicit=custom_paths)
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
    installed_harnesses: list[str] = []
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
                raw_primary = select_harness_install_raw_path(
                    h, scope, custom_paths=eff_custom, isolated=isolated
                )
                if not raw_primary:
                    raise InstallError(f"harness {target!r} has no {scope}-level skill path")

                base = resolve_path(raw_primary, scope, root, home)
                _verify_harness_base_within_scope(base, scope, root, home)
                dest = _resolve_harness_skill_dest(base, skill_name, src=skill_dir, recursive=h.recursive)

                if dest in written:
                    via = raw_primary if scope == "project" else base
                    installed_harnesses.append(h.name)
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

                existed_before = dest.exists() or dest.is_symlink()
                if existed_before and eff_conflict == "skip":
                    results.append(
                        InstallResult(
                            skill=skill_name,
                            harness=h.name,
                            dest=dest,
                            action="skipped",
                            detail=f"existing installation preserved (--on-conflict skip: {dest})",
                        )
                    )
                    continue

                if (
                    record_state
                    and dest.exists()
                    and not dest.is_symlink()
                    and dest.resolve() != skill_dir.resolve()
                    and not skill_dir.resolve().is_relative_to(dest.resolve())
                ):
                    bentry = snapshot_skill_for_rollback(
                        root, skill_name, dest, existing_record, scope=scope, home=home
                    )
                    if bentry and all(b.tree_hash != bentry.tree_hash for b in backup_entries):
                        backup_entries.append(bentry)

                try:
                    if strategy == "copy":
                        action = _stage_and_copy_skill(
                            skill_dir,
                            dest,
                            force=eff_force,
                            txn_tmp_root=txn_tmp_root,
                            created_in_txn=created_in_txn,
                            replaced_in_txn=replaced_in_txn,
                        )
                    else:
                        action = _stage_and_link_skill(
                            skill_dir,
                            dest,
                            force=eff_force,
                            txn_tmp_root=txn_tmp_root,
                            created_in_txn=created_in_txn,
                            replaced_in_txn=replaced_in_txn,
                        )
                except InstallError as exc:
                    raise InstallError(f"{h.name}: {exc}") from exc

                if not existed_before and action == "created":
                    created_in_txn.append(dest)

                detail_suffix = f"{strategy} via {raw_primary if scope == 'project' else base}"
                if adapt and h.capabilities.adapted_format and scope == "project":
                    rel_adapt, adapt_content = render_adapted_skill(doc, h.capabilities.adapted_format)
                    adapt_path = root / rel_adapt
                    atomic_write_text(adapt_path, adapt_content)
                    detail_suffix += f" + adapted {rel_adapt}"

                written[dest] = h.name
                installed_harnesses.append(h.name)
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
            for created_dest in created_in_txn:
                if created_dest.is_symlink():
                    created_dest.unlink(missing_ok=True)
                elif created_dest.is_dir():
                    shutil.rmtree(created_dest, ignore_errors=True)
            for orig_dest, prev_slot in reversed(replaced_in_txn):
                if orig_dest.is_symlink():
                    orig_dest.unlink(missing_ok=True)
                elif orig_dest.exists():
                    shutil.rmtree(orig_dest, ignore_errors=True)
                if prev_slot.exists() or prev_slot.is_symlink():
                    shutil.move(str(prev_slot), str(orig_dest))
            shutil.rmtree(txn_tmp_root, ignore_errors=True)
            raise

        shutil.rmtree(txn_tmp_root, ignore_errors=True)
        with contextlib.suppress(OSError):
            if not record_state and sdir_root.exists() and not any((sdir_root / "tmp").iterdir()):
                (sdir_root / "tmp").rmdir()

        if record_state and written:
            first_written_dest = next(iter(written.keys()))
            effective_skill_dir = first_written_dest if first_written_dest.exists() else skill_dir
            record_installation(
                root,
                skill_name=skill_name,
                source=source or str(skill_dir),
                skill_dir=effective_skill_dir,
                harnesses=installed_harnesses,
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
    on_conflict: str = "fail",
    home: Path | None = None,
    source: str = "",
    resolved_commit: str = "",
    version: str = "",
    record_state: bool = False,
    adapt: bool = False,
    custom_paths: dict[str, str] | None = None,
    isolated: bool = False,
) -> list[InstallResult]:
    """Install multiple skills as a single atomic batch transaction."""
    root = root.resolve()
    eff_conflict = "overwrite" if force else (on_conflict or "fail")
    with workspace_lock(root):
        plan = plan_install(
            root,
            skill_dirs,
            targets,
            strategy=strategy,
            scope=scope,
            force=force,
            on_conflict=eff_conflict,
            home=home,
            custom_paths=custom_paths,
            isolated=isolated,
        )
        if plan.conflicts and eff_conflict == "fail":
            raise InstallError("; ".join(plan.conflicts))

        pre_state = load_state(root, scope=scope, home=home)
        batch_results: list[InstallResult] = []
        completed_skills: list[tuple[str, bool]] = []

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
                    on_conflict=eff_conflict,
                    home=home,
                    source=source,
                    resolved_commit=resolved_commit,
                    version=version,
                    record_state=record_state,
                    adapt=adapt,
                    custom_paths=custom_paths,
                    isolated=isolated,
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
        records = load_state(root, scope=scope, home=home)
        rec = records.get(skill_name)
        target_set = {harnesses.get(t).name for t in targets}
        eff_custom = load_custom_harness_paths(root, scope=scope)

        for target in targets:
            h = harnesses.get(target)
            paths = list(h.project_paths if scope == "project" else h.user_paths)
            if h.name in eff_custom:
                custom_raw = eff_custom[h.name]
                if all(p.path != custom_raw for p in paths):
                    paths.insert(0, harnesses.SkillPath(custom_raw, scope, "custom override"))
            if not paths:
                results.append(InstallResult(skill_name, h.name, root, "skipped", f"no {scope} path"))
                continue

            # 1. Remove any non-shared secondary native paths (e.g. redundant `.cursor/skills/<skill>`)
            secondary_removed = False
            for sp in paths[1:]:
                if sp.is_compatibility:
                    continue
                sec_base = resolve_path(sp.path, scope, root, home)
                _verify_harness_base_within_scope(sec_base, scope, root, home)
                validate_skill_name_segment(skill_name, sec_base)
                sec_dest = sec_base / skill_name
                if sec_dest.is_symlink():
                    with contextlib.suppress(OSError):
                        removed_dests.add(str(sec_dest.resolve()))
                    sec_dest.unlink()
                    results.append(InstallResult(skill_name, h.name, sec_dest, "removed", "symlink"))
                    secondary_removed = True
                elif sec_dest.is_dir():
                    removed_dests.add(str(sec_dest.resolve()))
                    shutil.rmtree(sec_dest)
                    results.append(InstallResult(skill_name, h.name, sec_dest, "removed", "directory"))
                    secondary_removed = True

            # 2. Check primary path — preserve shared `.agents/skills` if other managed harnesses still own it!
            base = resolve_path(paths[0].path, scope, root, home)
            _verify_harness_base_within_scope(base, scope, root, home)
            validate_skill_name_segment(skill_name, base)
            dest = base / skill_name

            shared_owners: list[str] = []
            if rec and (dest.exists() or dest.is_symlink()):
                dest_resolved = dest.resolve() if not dest.is_symlink() else dest
                for other_name in rec.harnesses:
                    if other_name in target_set:
                        continue
                    with contextlib.suppress(KeyError):
                        other_h = harnesses.get(other_name)
                        other_paths = other_h.project_paths if scope == "project" else other_h.user_paths
                        if other_paths:
                            other_base = resolve_path(other_paths[0].path, scope, root, home)
                            other_dest = other_base / skill_name
                            other_resolved = other_dest.resolve() if not other_dest.is_symlink() else other_dest
                            if other_resolved == dest_resolved:
                                shared_owners.append(other_name)

            if shared_owners:
                if not secondary_removed:
                    results.append(
                        InstallResult(
                            skill_name,
                            h.name,
                            dest,
                            "preserved-shared",
                            f"shared directory retained for {', '.join(sorted(shared_owners))}",
                        )
                    )
                continue

            if dest.is_symlink():
                with contextlib.suppress(OSError):
                    removed_dests.add(str(dest.resolve()))
                dest.unlink()
                results.append(InstallResult(skill_name, h.name, dest, "removed", "symlink"))
            elif dest.is_dir():
                removed_dests.add(str(dest.resolve()))
                shutil.rmtree(dest)
                results.append(InstallResult(skill_name, h.name, dest, "removed", "directory"))
            elif not secondary_removed:
                results.append(InstallResult(skill_name, h.name, dest, "skipped", "not installed"))

        if record_state and rec:
            rec.destinations = [d for d in rec.destinations if d not in removed_dests]
            rec.harnesses = [hn for hn in rec.harnesses if hn not in target_set]
            if not rec.destinations or not rec.harnesses:
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
    include_dependencies: bool = True,
) -> list[InstallResult]:
    """Restore a skill (and optionally its transitive dependency graph) to its previous backup snapshot."""
    root = root.resolve()
    if skill_name.strip() == "--all" or skill_name.strip() == "all":
        records_all = load_state(root, scope=scope, home=home)
        all_res: list[InstallResult] = []
        for sname in sorted(records_all):
            if records_all[sname].history:
                all_res.extend(
                    rollback_skill(root, sname, scope=scope, home=home, include_dependencies=False)
                )
        if not all_res:
            raise InstallError("no backup history available to roll back any skill in workspace")
        return all_res

    skill_name = validate_skill_name_segment(skill_name)

    with workspace_lock(root):
        recover_interrupted_transactions(root, scope=scope, home=home)
        records = load_state(root, scope=scope, home=home)
        rec = records.get(skill_name)
        if not rec:
            raise InstallError(
                f"no backup history available to roll back skill {skill_name!r}: "
                "skill is not installed or tracked by Skillporter (run `skillporter list`)"
            )
        if not rec.history:
            sdir = state_dir(root, scope=scope, home=home)
            store_cand = (
                sdir / "store" / skill_name / rec.tree_hash[:12] / skill_name
                if rec.tree_hash
                else None
            )
            has_local_corruption = False
            for d_str in rec.destinations:
                dp = Path(d_str)
                if not dp.exists():
                    has_local_corruption = True
                    break
                cur_h, _ = compute_tree_hash(dp)
                if rec.tree_hash and cur_h != rec.tree_hash:
                    has_local_corruption = True
                    break
            if (
                has_local_corruption
                and store_cand is not None
                and store_cand.is_dir()
                and compute_tree_hash(store_cand)[0] == rec.tree_hash
            ):
                targets = rec.harnesses or ["claude-code", "codex", "cursor"]
                results = install(
                    root,
                    store_cand,
                    targets,
                    strategy="copy",
                    scope=scope,
                    force=True,
                    home=home,
                    source=rec.source,
                    resolved_commit=rec.resolved_commit,
                    version=rec.version,
                    record_state=False,
                    skill_name_override=skill_name,
                )
                for r in results:
                    if r.action == "created":
                        r.action = "rolled-back"
                    r.detail = f"restored clean initial baseline {rec.tree_hash[:12]}"
                return results
            raise InstallError(
                f"no backup history available to roll back skill {skill_name!r}: "
                f"currently at initial installed version {rec.version} ({rec.tree_hash[:12] or 'unhashed'}) "
                "with no earlier update snapshots, and on-disk files match the clean install. "
                f"Backups are created before updates or --force overwrites; run `skillporter remove {skill_name}` "
                "to uninstall it."
            )

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

        # Transitive graph rollback: if skillporter.lock lists dependencies for this skill
        # and they also have backup snapshots, roll them back atomically.
        if include_dependencies:
            from .manifest import load_lockfile

            lock = load_lockfile(root, warn_migration=False)
            locked_node = lock.skills.get(skill_name)
            if locked_node and locked_node.dependencies:
                for dep_name in sorted(locked_node.dependencies):
                    dep_rec = records.get(dep_name)
                    if dep_rec and dep_rec.history:
                        with contextlib.suppress(InstallError):
                            dep_res = rollback_skill(
                                root,
                                dep_name,
                                scope=scope,
                                home=home,
                                include_dependencies=False,
                            )
                            results.extend(dep_res)

        return results


def move_skill(
    root: Path,
    skill_name: str,
    *,
    from_harnesses: list[str],
    to_harnesses: list[str],
    scope: str = "project",
    strategy: str = "copy",
    force: bool = False,
    on_conflict: str = "fail",
    isolated: bool = False,
    custom_paths: dict[str, str] | None = None,
    home: Path | None = None,
) -> list[InstallResult]:
    """Move an installed skill from *from_harnesses* to *to_harnesses* atomically.

    Installs into *to_harnesses* first so the skill is verified at its new
    destination before removing from *from_harnesses* (preserving shared
    ``.agents/skills`` directories if any destination harness still owns them).
    """
    root = root.resolve()
    skill_name = validate_skill_name_segment(skill_name)
    from_canonical = [harnesses.get(h).name for h in from_harnesses]
    to_canonical = [harnesses.get(h).name for h in to_harnesses]
    eff_custom = load_custom_harness_paths(root, scope=scope, explicit=custom_paths)

    with workspace_lock(root):
        records = load_state(root, scope=scope, home=home)
        rec = records.get(skill_name)
        src_dir: Path | None = None

        for fh in from_canonical:
            h = harnesses.get(fh)
            cand_raws = []
            if fh in eff_custom:
                cand_raws.append(eff_custom[fh])
            pts = h.project_paths if scope == "project" else h.user_paths
            cand_raws.extend(sp.path for sp in pts)
            for raw_p in cand_raws:
                cand = resolve_path(raw_p, scope, root, home) / skill_name
                if (cand / "SKILL.md").is_file():
                    src_dir = cand
                    break
            if src_dir is not None:
                break

        if src_dir is None and rec:
            for d_str in rec.destinations:
                dp = Path(d_str)
                if (dp / "SKILL.md").is_file():
                    src_dir = dp
                    break

        if src_dir is None:
            raise InstallError(
                f"skill {skill_name!r} is not installed in {', '.join(from_canonical)} (scope: {scope})"
            )

        with tempfile_staging_copy(src_dir, skill_name, root, scope=scope, home=home) as staged_src:
            inst_results = install(
                root,
                staged_src,
                to_canonical,
                strategy=strategy,
                scope=scope,
                force=force,
                on_conflict=on_conflict,
                home=home,
                source=rec.source if rec else str(src_dir),
                resolved_commit=rec.resolved_commit if rec else "",
                version=rec.version if rec else "",
                record_state=True,
                skill_name_override=skill_name,
                custom_paths=eff_custom,
                isolated=isolated,
            )
            rem_targets = [fh for fh in from_canonical if fh not in to_canonical]
            rem_results = (
                uninstall(root, skill_name, rem_targets, scope=scope, home=home, record_state=True)
                if rem_targets
                else []
            )
        return [*inst_results, *rem_results]


@contextlib.contextmanager
def tempfile_staging_copy(
    src_dir: Path,
    skill_name: str,
    root: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
):
    """Hold a temporary copy of *src_dir* while moving across harnesses."""
    sdir = state_dir(root, scope=scope, home=home) / "tmp" / f"move-{uuid.uuid4().hex[:10]}"
    stage_skill = sdir / skill_name
    sdir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src_dir, stage_skill, symlinks=True)
        yield stage_skill
    finally:
        shutil.rmtree(sdir, ignore_errors=True)
        with contextlib.suppress(OSError):
            if sdir.parent.is_dir() and not any(sdir.parent.iterdir()):
                sdir.parent.rmdir()


def adopt_skills(
    root: Path,
    skill_names: list[str] | None = None,
    *,
    scope: str = "project",
    home: Path | None = None,
    allow_risky: bool = False,
) -> list[dict[str, object]]:
    """Adopt existing unmanaged on-disk skills into Skillporter state (and manifest if present)."""
    from .diagnose import diagnose as run_diagnose
    from .frontmatter import validate
    from .manifest import ManifestSkillSpec, load_manifest, save_manifest
    from .security import scan_skill

    root = root.resolve()
    with workspace_lock(root):
        diag = run_diagnose(root, scope=scope, home=home)
        records = load_state(root, scope=scope, home=home)
        wanted = set(skill_names) if skill_names else None

        adopted: list[dict[str, object]] = []
        for sname, copies in sorted(diag.skill_copies.items()):
            if wanted is not None and sname not in wanted:
                continue
            if sname in records and wanted is None:
                continue

            primary_copy = copies[0]
            doc = parse_skill(primary_copy / "SKILL.md")
            spec_errs = [i for i in validate(doc) if i.level == "error"]
            if spec_errs:
                raise InstallError(f"cannot adopt invalid skill {sname!r}: {spec_errs[0]}")

            srep = scan_skill(primary_copy)
            if srep.has_structural_escape:
                raise InstallError(f"cannot adopt {sname!r}: structural symlink/path escape detected")
            if (not srep.passed or not srep.scan_complete) and not allow_risky:
                raise InstallError(
                    f"cannot adopt {sname!r}: blocked by static security policy "
                    f"(risk {srep.risk_score}/100; pass --allow-risky after reviewing `skillporter scan`)"
                )

            loaded_harnesses = sorted(h for h, rep in diag.reports.items() if rep.loads(sname))
            meta = doc.frontmatter.get("metadata")
            ver = str(meta.get("version", "1.0.0")) if isinstance(meta, dict) else "1.0.0"
            try:
                rel_src = "./" + primary_copy.resolve().relative_to(root).as_posix()
            except ValueError:
                rel_src = str(primary_copy)

            rec = record_installation(
                root,
                skill_name=sname,
                source=rel_src,
                skill_dir=primary_copy,
                harnesses=loaded_harnesses,
                destinations=copies,
                strategy="copy",
                scope=scope,
                version=ver,
                home=home,
            )
            adopted.append(
                {
                    "name": sname,
                    "version": rec.version,
                    "tree_hash": rec.tree_hash,
                    "harnesses": rec.harnesses,
                    "source": rec.source,
                }
            )

        if wanted is not None:
            found_names = set(diag.skill_copies)
            missing_wanted = sorted(wanted - found_names)
            if missing_wanted:
                raise InstallError(f"skill(s) not found on disk to adopt: {', '.join(missing_wanted)}")

        if scope == "project" and adopted:
            manifest = load_manifest(root)
            if manifest is not None:
                existing_m = {s.name for s in manifest.skills}
                for item in adopted:
                    iname = str(item["name"])
                    if iname not in existing_m:
                        manifest.skills.append(
                            ManifestSkillSpec(
                                name=iname,
                                source=str(item["source"]),
                                version=str(item["version"]),
                                harnesses=list(item["harnesses"]),  # type: ignore[arg-type]
                            )
                        )
                save_manifest(root, manifest)

        return adopted
