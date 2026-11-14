"""Named Environment Profiles for Skillporter.

Allows developers to maintain and switch between clean, named configurations
(such as ``frontend-development``, ``backend-development``, ``security-review``,
``personal-workflow``) stored as standard ``ProjectManifest`` YAML files under
``.skillporter/profiles/<name>.yaml`` (project scope) or
``~/.skillporter/profiles/<name>.yaml`` (user scope).

Design invariant: Zero custom DSL. A profile file uses the exact same schema as
``skillporter.yaml``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import harnesses
from .atomic import atomic_write_text
from .environment import EnvironmentSnapshot, SkillEnvironmentEntry, capture_environment
from .manifest import ManifestSkillSpec, ProjectManifest, parse_manifest, save_manifest
from .state import state_dir

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class ProfileError(ValueError):
    """Raised when an environment profile name or operation is invalid."""


def validate_profile_name(name: str) -> str:
    clean = name.strip()
    if not _PROFILE_NAME_RE.match(clean) or ".." in clean:
        raise ProfileError(
            f"invalid profile name {name!r}: use letters, digits, '.', '_', or '-' (max 64 chars)"
        )
    return clean


def profiles_dir(root: Path, scope: str = "project", home: Path | None = None) -> Path:
    return state_dir(root.resolve(), scope=scope, home=home) / "profiles"


def active_profile_file(root: Path, scope: str = "project", home: Path | None = None) -> Path:
    return state_dir(root.resolve(), scope=scope, home=home) / "active_profile"


def profile_path(root: Path, name: str, scope: str = "project", home: Path | None = None) -> Path:
    pname = validate_profile_name(name)
    return profiles_dir(root, scope=scope, home=home) / f"{pname}.yaml"


def profile_exists(root: Path, name: str, scope: str = "project", home: Path | None = None) -> bool:
    try:
        p = profile_path(root, name, scope=scope, home=home)
    except ProfileError:
        return False
    return p.is_file()


def get_active_profile(root: Path, scope: str = "project", home: Path | None = None) -> str:
    af = active_profile_file(root, scope=scope, home=home)
    if af.is_file():
        return af.read_text(encoding="utf-8").strip()
    return ""


def list_profiles(root: Path, scope: str = "project", home: Path | None = None) -> list[dict[str, object]]:
    pdir = profiles_dir(root, scope=scope, home=home)
    active = get_active_profile(root, scope=scope, home=home)
    rows: list[dict[str, object]] = []
    if not pdir.is_dir():
        return rows
    for pfile in sorted(pdir.glob("*.yaml")):
        pname = pfile.stem
        manifest = parse_manifest(pfile.read_text(encoding="utf-8"))
        rows.append(
            {
                "name": pname,
                "active": pname == active,
                "harnesses": list(manifest.harnesses),
                "skills": [s.name for s in manifest.skills],
                "skill_count": len(manifest.skills),
                "strategy": manifest.strategy,
                "scope": scope,
                "path": str(pfile),
            }
        )
    return rows


def save_profile_from_environment(
    root: Path,
    name: str,
    *,
    scope: str = "project",
    home: Path | None = None,
    explicit_harnesses: list[str] | None = None,
    explicit_skills: list[str] | None = None,
    overwrite: bool = True,
) -> ProjectManifest:
    """Capture the current environment (or explicit selection) as named profile *name*."""
    pname = validate_profile_name(name)
    ppath = profile_path(root, pname, scope=scope, home=home)
    if ppath.exists() and not overwrite:
        raise ProfileError(f"profile {pname!r} already exists at {ppath} (pass --force to overwrite)")

    snap = capture_environment(root, scope=scope, home=home)
    wanted_skills = set(explicit_skills) if explicit_skills else None

    if explicit_harnesses:
        harnesses_list = [harnesses.get(h).name for h in explicit_harnesses]
    elif snap.manifest and snap.manifest.harnesses:
        harnesses_list = list(snap.manifest.harnesses)
    elif snap.selected_harnesses:
        harnesses_list = list(snap.selected_harnesses)
    else:
        harnesses_list = ["claude-code", "codex", "cursor"]

    from .diagnose import diagnose as run_diagnose

    diag = run_diagnose(root, scope=scope, home=home)
    sdir_root = state_dir(root.resolve(), scope=scope, home=home)
    specs: list[ManifestSkillSpec] = []
    for sname, entry in sorted(snap.skills.items()):
        if wanted_skills is not None and sname not in wanted_skills:
            continue
        if not entry.on_disk and not entry.in_manifest:
            continue

        eff_source = entry.source or f"./{sname}"
        copies = diag.skill_copies.get(sname, [])
        if copies and (
            eff_source.startswith(("./.", "../"))
            or any(str(c) == eff_source for c in copies)
            or (
                eff_source.startswith("./")
                and (root.resolve() / eff_source).resolve() in {c.resolve() for c in copies}
            )
        ):
            thash_short = entry.tree_hash[:12] if entry.tree_hash else "latest"
            store_dest = sdir_root / "store" / sname / thash_short / sname
            if not (store_dest / "SKILL.md").is_file():
                store_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(copies[0], store_dest, symlinks=True, dirs_exist_ok=True)
            try:
                eff_source = "./" + store_dest.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                eff_source = str(store_dest.resolve())

        specs.append(
            ManifestSkillSpec(
                name=sname,
                source=eff_source,
                ref=entry.resolved_commit[:12] if entry.resolved_commit else "",
                version=entry.version,
                strategy=entry.strategy,
                harnesses=list(entry.installed_harnesses or entry.desired_harnesses or harnesses_list),
            )
        )

    prof_manifest = ProjectManifest(
        project=snap.manifest.project if snap.manifest else (root.resolve().name or "my-project"),
        scope=scope,
        strategy=snap.manifest.strategy if snap.manifest else "copy",
        harnesses=harnesses_list,
        security_policy=snap.manifest.security_policy if snap.manifest else "HIGH",
        max_risk_score=snap.manifest.max_risk_score if snap.manifest else None,
        harness_paths=dict(snap.manifest.harness_paths) if snap.manifest else {},
        profile=pname,
        skills=specs,
    )
    ppath.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(ppath, prof_manifest.to_yaml())
    return prof_manifest


def load_profile(root: Path, name: str, *, scope: str = "project", home: Path | None = None) -> ProjectManifest:
    ppath = profile_path(root, name, scope=scope, home=home)
    if not ppath.is_file():
        raise ProfileError(f"profile {name!r} does not exist (run `skillporter profile list`)")
    manifest = parse_manifest(ppath.read_text(encoding="utf-8"))
    manifest.profile = validate_profile_name(name)
    return manifest


def load_profile_snapshot(
    root: Path,
    name: str,
    *,
    scope: str = "project",
    home: Path | None = None,
) -> EnvironmentSnapshot:
    """Convert a stored profile into an :class:`EnvironmentSnapshot` for ``skillporter diff``."""
    prof = load_profile(root, name, scope=scope, home=home)
    entries: dict[str, SkillEnvironmentEntry] = {}
    for s in prof.skills:
        eff_h = list(s.harnesses) if s.harnesses else list(prof.harnesses)
        entries[s.name] = SkillEnvironmentEntry(
            name=s.name,
            version=s.version or "1.0.0",
            source=s.source,
            resolved_commit=s.ref,
            strategy=s.strategy or prof.strategy,
            scope=scope,
            managed=True,
            in_manifest=True,
            on_disk=True,
            desired_harnesses=eff_h,
            installed_harnesses=eff_h,
            status="SYNCED",
        )
    return EnvironmentSnapshot(
        label=f"profile:{prof.profile}",
        root=root.resolve(),
        scope=scope,
        active_profile=prof.profile,
        manifest_present=True,
        manifest=prof,
        selected_harnesses=list(prof.harnesses),
        skills=entries,
        healthy=True,
    )


def delete_profile(root: Path, name: str, *, scope: str = "project", home: Path | None = None) -> Path:
    pname = validate_profile_name(name)
    ppath = profile_path(root, pname, scope=scope, home=home)
    if not ppath.is_file():
        raise ProfileError(f"profile {pname!r} does not exist")
    ppath.unlink()
    af = active_profile_file(root, scope=scope, home=home)
    if af.is_file() and af.read_text(encoding="utf-8").strip() == pname:
        af.unlink(missing_ok=True)
    return ppath


def activate_profile_manifest(
    root: Path,
    name: str,
    *,
    scope: str = "project",
    home: Path | None = None,
) -> ProjectManifest:
    """Record *name* as active profile and write ``skillporter.yaml`` when in project scope."""
    prof = load_profile(root, name, scope=scope, home=home)
    af = active_profile_file(root, scope=scope, home=home)
    af.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(af, prof.profile + "\n")
    if scope == "project":
        save_manifest(root.resolve(), prof)
    return prof


def export_profiles_dict(root: Path, *, scope: str = "project", home: Path | None = None) -> dict[str, str]:
    pdir = profiles_dir(root, scope=scope, home=home)
    if not pdir.is_dir():
        return {}
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(pdir.glob("*.yaml"))}


def import_profiles_dict(
    root: Path,
    profiles_map: dict[str, object],
    *,
    scope: str = "project",
    home: Path | None = None,
    overwrite: bool = False,
) -> list[str]:
    imported: list[str] = []
    for raw_name, raw_yaml in sorted(profiles_map.items()):
        if not isinstance(raw_yaml, str):
            continue
        pname = validate_profile_name(str(raw_name))
        ppath = profile_path(root, pname, scope=scope, home=home)
        if ppath.exists() and not overwrite:
            continue
        parsed = parse_manifest(raw_yaml)
        parsed.profile = pname
        ppath.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(ppath, parsed.to_yaml())
        imported.append(pname)
    return imported
