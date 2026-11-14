"""Unified Environment Model & Environment Comparison Engine.

Provides a single coherent representation (:class:`EnvironmentSnapshot`) that
reconciles:
  1. Desired configuration (``skillporter.yaml`` and active environment profile)
  2. Cryptographic lock state (``skillporter.lock``)
  3. Managed installation ownership (``.skillporter/state.json``)
  4. Actual on-disk harness discovery (``diagnose()`` across project or user scope)

Also powers deterministic comparisons (:func:`diff_environments`) across local
workspaces, ``.skillpack`` portable archives, and named profiles.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .diagnose import diagnose
from .frontmatter import parse_skill
from .manifest import (
    LOCKFILE_FILENAME,
    MANIFEST_FILENAME,
    Lockfile,
    LockfileError,
    ProjectManifest,
    load_lockfile,
    load_manifest,
)
from .security import compute_tree_hash
from .state import load_state


@dataclass
class SkillEnvironmentEntry:
    """Reconciled status of one skill in an environment."""

    name: str
    version: str = "1.0.0"
    tree_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    source: str = ""
    resolved_commit: str = ""
    strategy: str = "copy"
    scope: str = "project"
    managed: bool = False
    in_manifest: bool = False
    in_lockfile: bool = False
    on_disk: bool = False
    valid: bool = True
    desired_harnesses: list[str] = field(default_factory=list)
    installed_harnesses: list[str] = field(default_factory=list)
    missing_harnesses: list[str] = field(default_factory=list)
    duplicate_harnesses: list[str] = field(default_factory=list)
    drifted: bool = False
    lock_drifted: bool = False
    status: str = "SYNCED"  # SYNCED | DRIFTED | OUT_OF_SYNC | UNMANAGED | ORPHANED | DUPLICATE | INVALID

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "tree_hash": self.tree_hash,
            "source": self.source,
            "resolved_commit": self.resolved_commit,
            "strategy": self.strategy,
            "scope": self.scope,
            "managed": self.managed,
            "in_manifest": self.in_manifest,
            "in_lockfile": self.in_lockfile,
            "on_disk": self.on_disk,
            "valid": self.valid,
            "desired_harnesses": self.desired_harnesses,
            "installed_harnesses": self.installed_harnesses,
            "missing_harnesses": self.missing_harnesses,
            "duplicate_harnesses": self.duplicate_harnesses,
            "drifted": self.drifted,
            "lock_drifted": self.lock_drifted,
            "status": self.status,
        }


@dataclass
class EnvironmentSnapshot:
    """Complete reconciled state of a Skillporter environment."""

    label: str
    root: Path
    scope: str = "project"
    active_profile: str = ""
    manifest_present: bool = False
    lockfile_present: bool = False
    manifest: ProjectManifest | None = None
    lockfile: Lockfile = field(default_factory=Lockfile)
    detected_harnesses: list[str] = field(default_factory=list)
    selected_harnesses: list[str] = field(default_factory=list)
    skills: dict[str, SkillEnvironmentEntry] = field(default_factory=dict)
    lock_drift: list[str] = field(default_factory=list)
    drifted_skills: list[str] = field(default_factory=list)
    duplicate_skills: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    remediations: list[str] = field(default_factory=list)
    healthy: bool = True

    @property
    def managed_skills(self) -> list[str]:
        return sorted(k for k, v in self.skills.items() if v.managed)

    @property
    def unmanaged_skills(self) -> list[str]:
        return sorted(k for k, v in self.skills.items() if v.status == "UNMANAGED")

    @property
    def orphaned_skills(self) -> list[str]:
        return sorted(k for k, v in self.skills.items() if v.status == "ORPHANED")

    @property
    def attention_skills(self) -> list[str]:
        return sorted(
            k
            for k, v in self.skills.items()
            if v.status in ("DRIFTED", "OUT_OF_SYNC", "ORPHANED", "DUPLICATE", "INVALID")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "root": str(self.root),
            "scope": self.scope,
            "active_profile": self.active_profile,
            "manifest_present": self.manifest_present,
            "lockfile_present": self.lockfile_present,
            "detected_harnesses": self.detected_harnesses,
            "selected_harnesses": self.selected_harnesses,
            "managed_skills": self.managed_skills,
            "unmanaged_skills": self.unmanaged_skills,
            "orphaned_skills": self.orphaned_skills,
            "attention_skills": self.attention_skills,
            "discovered_skills": sorted(k for k, v in self.skills.items() if v.on_disk),
            "locked_skills": sorted(self.lockfile.skills),
            "drifted_skills": self.drifted_skills,
            "lock_drift": self.lock_drift,
            "duplicates": self.duplicate_skills,
            "skills": {k: v.to_dict() for k, v in sorted(self.skills.items())},
            "findings": self.findings,
            "remediations": self.remediations,
            "healthy": self.healthy,
        }


def _read_active_profile_name(root: Path, scope: str = "project", home: Path | None = None) -> str:
    from .state import state_dir

    ap_file = state_dir(root, scope=scope, home=home) / "active_profile"
    if ap_file.is_file():
        with contextlib.suppress(OSError):
            val = ap_file.read_text(encoding="utf-8").strip()
            if val:
                return val
    if scope == "project":
        m = load_manifest(root)
        if m and m.profile:
            return m.profile
    return ""


def capture_environment(
    root: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
    only_harnesses: list[str] | None = None,
) -> EnvironmentSnapshot:
    """Capture the unified desired vs. actual environment state for *root*."""
    root = root.resolve()
    manifest = load_manifest(root) if scope == "project" else None
    manifest_present = (root / MANIFEST_FILENAME).is_file() if scope == "project" else False
    lockfile_present = (root / LOCKFILE_FILENAME).is_file() if scope == "project" else False

    lock_drift: list[str] = []
    if scope == "project":
        try:
            lock = load_lockfile(root, warn_migration=False)
        except LockfileError as exc:
            lock = Lockfile()
            lock_drift.append(str(exc))
    else:
        lock = Lockfile()

    records = load_state(root, scope=scope, home=home)
    diag = diagnose(root, only=only_harnesses, scope=scope, home=home)
    detected = [d.harness.name for d in harnesses.detect_harnesses(root, home=home) if d.installed]
    active_profile = _read_active_profile_name(root, scope=scope, home=home)

    if only_harnesses:
        selected_harnesses = [harnesses.get(h).name for h in only_harnesses]
    elif manifest and manifest.harnesses:
        selected_harnesses = []
        for mh in manifest.harnesses:
            with contextlib.suppress(KeyError):
                cname = harnesses.get(mh).name
                if cname not in selected_harnesses:
                    selected_harnesses.append(cname)
    elif scope == "user":
        selected_harnesses = sorted(
            {
                hname
                for hname, rep in diag.reports.items()
                if rep.reachable_skills or any(loc.exists for loc in rep.locations)
            }
            | {h for r in records.values() for h in r.harnesses}
        )
    else:
        selected_harnesses = sorted(
            set(harnesses.CORE_HARNESS_NAMES)
            | {d.harness.name for d in harnesses.detect_harnesses(root, home=home) if d.project_active}
        )

    manifest_map = {s.name: s for s in manifest.skills} if (manifest and manifest.skills) else {}

    for sname, locked in sorted(lock.skills.items()):
        copies = diag.skill_copies.get(sname, [])
        if not copies:
            lock_drift.append(f"{sname}: locked at {locked.tree_hash[:12]} but missing on disk")
            continue
        for cdir in copies:
            actual_hash, _ = compute_tree_hash(cdir)
            if locked.tree_hash and actual_hash != locked.tree_hash:
                rel_p = cdir.relative_to(root) if cdir.is_relative_to(root) else cdir
                lock_drift.append(
                    f"{sname} ({rel_p}): locked {locked.tree_hash[:12]} != disk {actual_hash[:12]}"
                )

    all_names = sorted(
        set(diag.skill_names)
        | set(records)
        | set(lock.skills)
        | set(manifest_map)
    )

    skills_map: dict[str, SkillEnvironmentEntry] = {}
    for sname in all_names:
        copies = diag.skill_copies.get(sname, [])
        on_disk = len(copies) > 0
        rec = records.get(sname)
        mspec = manifest_map.get(sname)
        lentry = lock.skills.get(sname)

        thash = ""
        fhashes: dict[str, str] = {}
        ver = "1.0.0"
        if on_disk:
            thash, fhashes = compute_tree_hash(copies[0])
            doc = parse_skill(copies[0] / "SKILL.md")
            meta = doc.frontmatter.get("metadata")
            if isinstance(meta, dict) and meta.get("version"):
                ver = str(meta["version"])
        if rec and rec.version and ver == "1.0.0":
            ver = rec.version
        if lentry and lentry.version and ver == "1.0.0":
            ver = lentry.version
        if mspec and mspec.version and ver == "1.0.0":
            ver = mspec.version
        if not thash:
            thash = (rec.tree_hash if rec else "") or (lentry.tree_hash if lentry else "")
        if not fhashes and lentry and lentry.file_hashes:
            fhashes = dict(lentry.file_hashes)

        src = (
            (mspec.source if mspec and mspec.source else "")
            or (rec.source if rec and rec.source else "")
            or (lentry.source if lentry and lentry.source else "")
        )
        if not src and on_disk:
            try:
                src = "./" + copies[0].resolve().relative_to(root).as_posix()
            except ValueError:
                src = str(copies[0])

        commit = (
            (rec.resolved_commit if rec and rec.resolved_commit else "")
            or (lentry.resolved_commit if lentry and lentry.resolved_commit else "")
            or (mspec.ref if mspec and mspec.ref else "")
        )
        strategy = (
            (mspec.strategy if mspec and mspec.strategy else "")
            or (rec.strategy if rec and rec.strategy else "")
            or (lentry.strategy if lentry and lentry.strategy else "copy")
        )

        installed_in = sorted(h for h, rep in diag.reports.items() if rep.loads(sname))
        dup_in = sorted(h for h, dmap in diag.duplicates.items() if sname in dmap)

        if mspec and mspec.harnesses:
            desired = [harnesses.get(h).name for h in mspec.harnesses if _known_harness(h)]
        elif mspec and manifest and manifest.harnesses:
            desired = list(selected_harnesses)
        elif rec and rec.harnesses:
            desired = [harnesses.get(h).name for h in rec.harnesses if _known_harness(h)]
        elif lentry and lentry.installed_targets:
            desired = [harnesses.get(h).name for h in lentry.installed_targets if _known_harness(h)]
        else:
            desired = []

        missing = sorted(h for h in desired if h not in installed_in)
        is_valid = diag.is_skill_valid(sname) if on_disk else True
        is_drifted = sname in diag.drifted
        is_lock_drifted = any(ld.startswith(f"{sname}:") or ld.startswith(f"{sname} ") for ld in lock_drift)
        is_managed = rec is not None

        if not on_disk and (is_managed or lentry is not None) and mspec is None:
            st = "ORPHANED"
        elif not on_disk and mspec is not None:
            st = "OUT_OF_SYNC"
        elif not is_valid:
            st = "INVALID"
        elif is_drifted or is_lock_drifted:
            st = "DRIFTED"
        elif dup_in:
            st = "DUPLICATE"
        elif missing:
            st = "OUT_OF_SYNC"
        elif not is_managed and mspec is None and lentry is None:
            st = "UNMANAGED"
        else:
            st = "SYNCED"

        skills_map[sname] = SkillEnvironmentEntry(
            name=sname,
            version=ver,
            tree_hash=thash,
            file_hashes=fhashes,
            source=src,
            resolved_commit=commit,
            strategy=strategy,
            scope=scope,
            managed=is_managed,
            in_manifest=mspec is not None,
            in_lockfile=lentry is not None,
            on_disk=on_disk,
            valid=is_valid,
            desired_harnesses=desired,
            installed_harnesses=installed_in,
            missing_harnesses=missing,
            duplicate_harnesses=dup_in,
            drifted=is_drifted,
            lock_drifted=is_lock_drifted,
            status=st,
        )

    findings = list(diag.findings)
    for sname, entry in sorted(skills_map.items()):
        if entry.status == "ORPHANED":
            msg = f"orphaned state: skill {sname!r} is recorded in state/lockfile but missing on disk"
            if msg not in findings:
                findings.append(msg)
        elif entry.status == "OUT_OF_SYNC" and not entry.on_disk:
            msg = f"manifest skill {sname!r} is declared in {MANIFEST_FILENAME} but not yet installed"
            if msg not in findings:
                findings.append(msg)

    remediations: list[str] = []
    if any(e.status == "OUT_OF_SYNC" for e in skills_map.values()):
        remediations.append("skillporter sync                  # install missing manifest/harness targets")
    if diag.drifted:
        remediations.append("skillporter sync --force          # reconcile drifted skill copies safely")
    if lock_drift:
        remediations.append("skillporter rollback <skill>      # or `skillporter lock` if edit was intentional")
    if any(e.status == "UNMANAGED" for e in skills_map.values()):
        remediations.append("skillporter adopt --all           # track existing unmanaged skills for backup & export")
    if not manifest_present and scope == "project" and skills_map:
        remediations.append("skillporter init                  # create skillporter.yaml for reproducible team sync")

    healthy = (
        len(findings) == 0
        and len(lock_drift) == 0
        and not any(
            e.status in ("DRIFTED", "OUT_OF_SYNC", "ORPHANED", "INVALID")
            for e in skills_map.values()
        )
    )

    return EnvironmentSnapshot(
        label=f"{scope}:{root}",
        root=root,
        scope=scope,
        active_profile=active_profile,
        manifest_present=manifest_present,
        lockfile_present=lockfile_present,
        manifest=manifest,
        lockfile=lock,
        detected_harnesses=detected,
        selected_harnesses=selected_harnesses,
        skills=skills_map,
        lock_drift=lock_drift,
        drifted_skills=sorted(diag.drifted),
        duplicate_skills=diag.duplicates,
        findings=findings,
        remediations=remediations,
        healthy=healthy,
    )


def _known_harness(name: str) -> bool:
    try:
        harnesses.get(name)
        return True
    except KeyError:
        return False


@dataclass
class EnvironmentDiff:
    """Structured comparison between a local/base environment and a target environment."""

    left_label: str
    right_label: str
    only_in_left: list[str] = field(default_factory=list)
    only_in_right: list[str] = field(default_factory=list)
    version_diffs: list[dict[str, object]] = field(default_factory=list)
    content_diffs: list[dict[str, object]] = field(default_factory=list)
    harness_diffs: list[dict[str, object]] = field(default_factory=list)
    identical: list[str] = field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(
            self.only_in_left
            or self.only_in_right
            or self.version_diffs
            or self.content_diffs
            or self.harness_diffs
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "left": self.left_label,
            "right": self.right_label,
            "identical_skills": self.identical,
            "only_in_left": self.only_in_left,
            "only_in_right": self.only_in_right,
            "version_diffs": self.version_diffs,
            "content_diffs": self.content_diffs,
            "harness_diffs": self.harness_diffs,
            "has_differences": self.has_differences,
        }


def diff_environments(left: EnvironmentSnapshot, right: EnvironmentSnapshot) -> EnvironmentDiff:
    """Compare *left* (e.g. current workspace) against *right* (e.g. .skillpack, profile, or directory)."""
    l_names = set(left.skills)
    r_names = set(right.skills)
    only_left = sorted(l_names - r_names)
    only_right = sorted(r_names - l_names)

    version_diffs: list[dict[str, object]] = []
    content_diffs: list[dict[str, object]] = []
    harness_diffs: list[dict[str, object]] = []
    identical: list[str] = []

    for sname in sorted(l_names & r_names):
        le = left.skills[sname]
        re = right.skills[sname]
        changed = False

        if le.version != re.version or (
            le.resolved_commit and re.resolved_commit and le.resolved_commit != re.resolved_commit
        ):
            version_diffs.append(
                {
                    "skill": sname,
                    "left_version": le.version,
                    "right_version": re.version,
                    "left_commit": le.resolved_commit[:12] if le.resolved_commit else "",
                    "right_commit": re.resolved_commit[:12] if re.resolved_commit else "",
                }
            )
            changed = True

        if le.tree_hash and re.tree_hash and le.tree_hash != re.tree_hash:
            changed_files: list[str] = []
            if le.file_hashes and re.file_hashes:
                all_f = sorted(set(le.file_hashes) | set(re.file_hashes))
                for fk in all_f:
                    if le.file_hashes.get(fk) != re.file_hashes.get(fk):
                        changed_files.append(fk)
            content_diffs.append(
                {
                    "skill": sname,
                    "left_hash": le.tree_hash[:12],
                    "right_hash": re.tree_hash[:12],
                    "changed_files": changed_files,
                }
            )
            changed = True

        l_h = sorted(set(le.installed_harnesses or le.desired_harnesses))
        r_h = sorted(set(re.installed_harnesses or re.desired_harnesses))
        if l_h != r_h:
            harness_diffs.append(
                {
                    "skill": sname,
                    "left_harnesses": l_h,
                    "right_harnesses": r_h,
                    "missing_in_left": [h for h in r_h if h not in l_h],
                    "extra_in_left": [h for h in l_h if h not in r_h],
                }
            )
            changed = True

        if not changed:
            identical.append(sname)

    return EnvironmentDiff(
        left_label=left.label,
        right_label=right.label,
        only_in_left=only_left,
        only_in_right=only_right,
        version_diffs=version_diffs,
        content_diffs=content_diffs,
        harness_diffs=harness_diffs,
        identical=identical,
    )


def load_snapshot_from_target(
    target: str | Path,
    *,
    base_dir: Path | None = None,
    scope: str = "project",
    home: Path | None = None,
) -> EnvironmentSnapshot:
    """Load an :class:`EnvironmentSnapshot` from a directory, ``.skillpack`` archive, or profile name."""
    raw = str(target).strip()
    cwd = (base_dir or Path.cwd()).resolve()

    if raw.startswith("profile:"):
        from .profiles import load_profile_snapshot

        pname = raw.split("profile:", 1)[1].strip()
        return load_profile_snapshot(cwd, pname, scope=scope, home=home)

    cand = Path(raw).expanduser()
    if not cand.is_absolute():
        cand = (cwd / cand).resolve()

    if cand.is_file() and (
        cand.name.endswith(".skillpack")
        or cand.name.endswith(".tar.gz")
        or cand.name.endswith(".tgz")
    ):
        from .portability import snapshot_from_skillpack

        return snapshot_from_skillpack(cand)

    if cand.is_dir():
        return capture_environment(cand, scope=scope, home=home)

    # Check if raw matches a named profile in the current workspace
    from .profiles import load_profile_snapshot, profile_exists

    if profile_exists(cwd, raw, scope=scope, home=home):
        return load_profile_snapshot(cwd, raw, scope=scope, home=home)

    raise FileNotFoundError(
        f"cannot resolve comparison target {raw!r}: expected a workspace directory, .skillpack file, or profile:<name>"
    )
