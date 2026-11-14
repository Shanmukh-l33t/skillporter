"""Portable Skill Environment Packaging (.skillpack Export & Import).

Implements the hybrid ``.skillpack`` archive specification (schema v1):
  * Deterministic ``.tar.gz`` archive containing ``skillpack.json`` + ``skills/<name>/``
  * Full offline restoration (all skill files bundled and content-addressed by SHA-256)
  * Full upstream continuity (preserves source URLs, commits, lockfile metadata, and profiles)
  * Strict security invariants:
      - Excludes dotfiles/credential files (``.env*``, ``*.pem``, ``*.key``, ``.npmrc``, ``.git``)
      - Blocks export if ``scan_skill`` detects embedded secrets or structural symlink escapes
      - Extracts exclusively via bounded ``safe_extract_tar`` (Zip-Slip / Tar-Bomb safe)
      - Verifies per-file and tree SHA-256 digests against ``skillpack.json`` before staging
      - Runs static security scanning on every skill prior to installation; never executes scripts.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, harnesses
from .atomic import workspace_lock
from .audit import redact_sensitive_text
from .environment import EnvironmentSnapshot, SkillEnvironmentEntry, capture_environment
from .frontmatter import parse_skill, validate
from .install import InstallError, install, plan_install, uninstall, validate_skill_name_segment
from .manifest import (
    LockedSkill,
    Lockfile,
    ManifestSkillSpec,
    load_manifest,
    parse_manifest,
    save_lockfile,
    save_manifest,
)
from .resolver import DependencyConflictError, DependencyCycleError, DependencyError, SkillDependency
from .security import compute_tree_hash, scan_skill
from .sources import SourceError, resolve_source, safe_extract_tar
from .state import load_state, save_state

SKILLPACK_SCHEMA_VERSION = 1
SKILLPACK_FORMAT = "skillporter-skillpack"

_EXCLUDED_EXPORT_DIRS = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
)
_SENSITIVE_EXPORT_FILENAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
        "credentials.json",
    }
)
_SENSITIVE_EXPORT_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx")
_SECRET_FINDING_CODES = frozenset({"sec-private-key", "sec-aws-key", "sec-github-token", "sec-api-key"})


class SkillpackError(RuntimeError):
    """Raised when a .skillpack archive fails integrity, schema, or security checks."""


def _is_excluded_export_file(rel_posix: str) -> tuple[bool, bool]:
    """Return ``(exclude, is_sensitive)`` for a relative path inside a skill directory."""
    parts = [p for p in rel_posix.split("/") if p]
    if any(p in _EXCLUDED_EXPORT_DIRS for p in parts):
        return True, False
    leaf = parts[-1] if parts else ""
    low = leaf.lower()
    if low in _SENSITIVE_EXPORT_FILENAMES or low.startswith(".env.") or low.endswith(_SENSITIVE_EXPORT_SUFFIXES):
        return True, True
    if low.endswith(".pyc") or low == ".ds_store":
        return True, False
    return False, False


@dataclass
class ExportReport:
    """Summary of a completed ``skillporter export`` operation."""

    output_path: Path
    archive_sha256: str
    size_bytes: int
    scope: str
    manifest_only: bool
    skills_exported: list[str]
    harnesses: list[str]
    profiles_exported: list[str] = field(default_factory=list)
    excluded_sensitive_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "output_path": str(self.output_path),
            "archive_sha256": self.archive_sha256,
            "size_bytes": self.size_bytes,
            "scope": self.scope,
            "manifest_only": self.manifest_only,
            "skills_exported": self.skills_exported,
            "harnesses": self.harnesses,
            "profiles_exported": self.profiles_exported,
            "excluded_sensitive_files": self.excluded_sensitive_files,
        }


@dataclass
class ImportPlan:
    """Previewable plan and validation summary for ``skillporter import``."""

    pack_path: Path
    pack_sha256: str
    schema_version: int
    source_scope: str
    target_scope: str
    skills: list[dict[str, object]]
    available_harnesses: list[str]
    missing_harnesses: list[str]
    target_harnesses_by_skill: dict[str, list[str]]
    version_conflicts: list[str] = field(default_factory=list)
    destination_conflicts: list[str] = field(default_factory=list)
    security_findings: list[dict[str, object]] = field(default_factory=list)
    security_blocked: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    profiles_included: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.security_blocked and not self.destination_conflicts and not self.missing_dependencies

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_path": str(self.pack_path),
            "pack_sha256": self.pack_sha256,
            "schema_version": self.schema_version,
            "source_scope": self.source_scope,
            "target_scope": self.target_scope,
            "skills": self.skills,
            "available_harnesses": self.available_harnesses,
            "missing_harnesses": self.missing_harnesses,
            "target_harnesses_by_skill": self.target_harnesses_by_skill,
            "version_conflicts": self.version_conflicts,
            "destination_conflicts": self.destination_conflicts,
            "security_findings": self.security_findings,
            "security_blocked": self.security_blocked,
            "missing_dependencies": self.missing_dependencies,
            "profiles_included": self.profiles_included,
            "ready": self.ready,
        }


def _add_bytes_to_tar(tf: tarfile.TarFile, arcname: str, payload: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(payload)
    info.mtime = 0
    info.mode = mode
    info.type = tarfile.REGTYPE
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tf.addfile(info, io.BytesIO(payload))


def export_skillpack(
    root: Path,
    output_path: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
    skill_filter: list[str] | None = None,
    include_unmanaged: bool = True,
    manifest_only: bool = False,
) -> ExportReport:
    """Package a managed Skillporter environment into a portable ``.skillpack`` archive."""
    root = root.resolve()
    snap = capture_environment(root, scope=scope, home=home)
    wanted = set(skill_filter) if skill_filter else None

    selected_entries: list[SkillEnvironmentEntry] = []
    for sname, entry in sorted(snap.skills.items()):
        if wanted is not None and sname not in wanted:
            continue
        if not include_unmanaged and not entry.managed and not entry.in_manifest:
            continue
        if not entry.on_disk and not manifest_only:
            continue
        selected_entries.append(entry)

    if wanted is not None:
        found = {e.name for e in selected_entries}
        missing = sorted(wanted - found)
        if missing:
            raise SkillpackError(f"requested skill(s) not found to export: {', '.join(missing)}")

    if not selected_entries:
        raise SkillpackError(f"no skills found in {scope} environment at {root} to export")

    diag_copies = {}
    from .diagnose import diagnose as run_diagnose

    diag = run_diagnose(root, scope=scope, home=home)
    diag_copies = diag.skill_copies

    excluded_sensitive: list[str] = []
    staged_files_by_skill: dict[str, Path] = {}
    skills_meta: dict[str, dict[str, object]] = {}

    stage_root = Path(tempfile.mkdtemp(prefix="skillporter-export-"))
    try:
        for entry in selected_entries:
            sname = validate_skill_name_segment(entry.name)
            src_copies = diag_copies.get(sname, [])
            clean_source = redact_sensitive_text(entry.source)
            if clean_source.startswith(str(root)):
                with contextlib.suppress(ValueError):
                    clean_source = "./" + Path(clean_source).resolve().relative_to(root).as_posix()
            elif home and clean_source.startswith(str(home.resolve())) or Path(clean_source).is_absolute():
                clean_source = f"local:{sname}"

            deps_dict: dict[str, str] = {}
            if snap.manifest:
                for ms in snap.manifest.skills:
                    if ms.name == sname and ms.dependencies:
                        deps_dict = {d.name: d.version for d in ms.dependencies}
                        break
            if not deps_dict and sname in snap.lockfile.skills:
                deps_dict = dict(snap.lockfile.skills[sname].dependencies)

            if not manifest_only:
                if not src_copies:
                    raise SkillpackError(f"cannot bundle skill {sname!r}: directory missing on disk")
                src_dir = src_copies[0]
                srep = scan_skill(src_dir, offline=True)
                if srep.has_structural_escape:
                    raise SkillpackError(f"refusing to export {sname!r}: structural symlink or path escape detected")
                secret_hits = [f for f in srep.findings if f.code in _SECRET_FINDING_CODES]
                if secret_hits:
                    hit = secret_hits[0]
                    raise SkillpackError(
                        f"refusing to export {sname!r}: embedded credential detected "
                        f"({hit.code} in {hit.file}:{hit.line}); remove secrets before exporting"
                    )

                clean_stage = stage_root / sname
                clean_stage.mkdir(parents=True, exist_ok=True)
                for fpath in sorted(src_dir.rglob("*")):
                    if fpath.is_symlink():
                        target_r = fpath.resolve()
                        if not target_r.is_relative_to(src_dir.resolve()):
                            raise SkillpackError(f"refusing to export escaping symlink in {sname!r}: {fpath.name}")
                        continue
                    if not fpath.is_file():
                        continue
                    rel_p = fpath.relative_to(src_dir).as_posix()
                    excl, is_sens = _is_excluded_export_file(rel_p)
                    if excl:
                        if is_sens:
                            excluded_sensitive.append(f"{sname}/{rel_p}")
                        continue
                    dst_f = clean_stage / rel_p
                    dst_f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fpath, dst_f)

                if not (clean_stage / "SKILL.md").is_file():
                    raise SkillpackError(f"skill {sname!r} has no SKILL.md after staging")

                thash, fhashes = compute_tree_hash(clean_stage)
                staged_files_by_skill[sname] = clean_stage
            else:
                if clean_source.startswith(("local:", "./", "../")):
                    raise SkillpackError(
                        f"cannot use --manifest-only for local skill {sname!r} ({entry.source}); "
                        "omit --manifest-only to bundle skill files inside the .skillpack"
                    )
                thash = entry.tree_hash
                fhashes = dict(entry.file_hashes)

            eff_harnesses = sorted(set(entry.installed_harnesses or entry.desired_harnesses))
            skills_meta[sname] = {
                "name": sname,
                "version": entry.version,
                "source": clean_source,
                "resolved_commit": entry.resolved_commit,
                "strategy": entry.strategy or "copy",
                "harnesses": eff_harnesses,
                "dependencies": deps_dict,
                "tree_hash": thash,
                "file_hashes": {k: fhashes[k] for k in sorted(fhashes)},
                "bundled": not manifest_only,
                "archive_dir": f"skills/{sname}" if not manifest_only else "",
            }

        from .profiles import export_profiles_dict

        profiles_map = export_profiles_dict(root, scope=scope, home=home)

        manifest_dict: dict[str, object] | None = None
        if snap.manifest is not None:
            manifest_dict = {
                "schema_version": snap.manifest.schema_version,
                "project": snap.manifest.project,
                "scope": snap.manifest.scope,
                "strategy": snap.manifest.strategy,
                "security_policy": snap.manifest.security_policy,
                "max_risk_score": snap.manifest.max_risk_score,
                "harnesses": list(snap.manifest.harnesses),
                "harness_paths": dict(snap.manifest.harness_paths),
                "profile": snap.manifest.profile,
                "skills": [
                    {
                        **s.to_dict(),
                        "source": redact_sensitive_text(s.source),
                    }
                    for s in snap.manifest.skills
                    if wanted is None or s.name in wanted
                ],
            }

        all_harnesses = sorted({h for meta in skills_meta.values() for h in meta["harnesses"]})  # type: ignore[attr-defined]
        pack_doc = {
            "schema_version": SKILLPACK_SCHEMA_VERSION,
            "format": SKILLPACK_FORMAT,
            "skillporter_version": __version__,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": scope,
            "active_profile": snap.active_profile,
            "harnesses": all_harnesses,
            "manifest_only": manifest_only,
            "manifest": manifest_dict,
            "profiles": profiles_map,
            "skills": {k: skills_meta[k] for k in sorted(skills_meta)},
        }

        out_resolved = output_path.expanduser().resolve()
        out_resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp_archive = out_resolved.parent / f".tmp-{os.getpid()}-{out_resolved.name}"

        try:
            with (
                open(tmp_archive, "wb") as raw_fh,
                tarfile.open(fileobj=raw_fh, mode="w:gz", format=tarfile.PAX_FORMAT) as tf,
            ):
                pack_bytes = (json.dumps(pack_doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
                _add_bytes_to_tar(tf, "skillpack.json", pack_bytes, mode=0o644)

                for sname in sorted(staged_files_by_skill):
                    sstage = staged_files_by_skill[sname]
                    for fpath in sorted(sstage.rglob("*")):
                        if not fpath.is_file():
                            continue
                        rel_f = fpath.relative_to(sstage).as_posix()
                        arc_p = f"skills/{sname}/{rel_f}"
                        mode = 0o755 if rel_f.startswith("scripts/") and rel_f.endswith(".sh") else 0o644
                        _add_bytes_to_tar(tf, arc_p, fpath.read_bytes(), mode=mode)

            os.replace(tmp_archive, out_resolved)
        except BaseException:
            tmp_archive.unlink(missing_ok=True)
            raise

        digest = hashlib.sha256(out_resolved.read_bytes()).hexdigest()
        size_b = out_resolved.stat().st_size
        return ExportReport(
            output_path=out_resolved,
            archive_sha256=digest,
            size_bytes=size_b,
            scope=scope,
            manifest_only=manifest_only,
            skills_exported=sorted(skills_meta),
            harnesses=all_harnesses,
            profiles_exported=sorted(profiles_map),
            excluded_sensitive_files=excluded_sensitive,
        )
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _extract_and_verify_skillpack(pack_path: Path) -> tuple[dict[str, object], Path, str]:
    """Safely extract *pack_path*, validate ``skillpack.json``, and verify every skill's SHA-256."""
    resolved_pack = pack_path.expanduser().resolve()
    if not resolved_pack.is_file():
        raise SkillpackError(f"skillpack file does not exist: {resolved_pack}")

    pack_sha256 = hashlib.sha256(resolved_pack.read_bytes()).hexdigest()
    extract_dir = Path(tempfile.mkdtemp(prefix="skillporter-import-"))
    try:
        try:
            safe_extract_tar(resolved_pack, extract_dir)
        except SourceError as exc:
            raise SkillpackError(f"invalid or unsafe skillpack archive {resolved_pack}: {exc}") from exc

        manifest_json_path = extract_dir / "skillpack.json"
        if not manifest_json_path.is_file():
            raise SkillpackError(f"invalid skillpack {resolved_pack}: missing root skillpack.json")

        try:
            doc = json.loads(manifest_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillpackError(f"corrupted skillpack.json in {resolved_pack}: {exc}") from exc

        if not isinstance(doc, dict) or doc.get("format") != SKILLPACK_FORMAT:
            raise SkillpackError(f"unsupported archive format in {resolved_pack}: expected {SKILLPACK_FORMAT!r}")

        schema_ver = doc.get("schema_version")
        if isinstance(schema_ver, bool) or not isinstance(schema_ver, int) or schema_ver != SKILLPACK_SCHEMA_VERSION:
            raise SkillpackError(
                f"unsupported skillpack schema_version {schema_ver!r} (supported: {SKILLPACK_SCHEMA_VERSION})"
            )

        skills_raw = doc.get("skills")
        if not isinstance(skills_raw, dict) or not skills_raw:
            raise SkillpackError("skillpack contains no skills")

        for sname, smeta in sorted(skills_raw.items()):
            validate_skill_name_segment(sname)
            if not isinstance(smeta, dict):
                raise SkillpackError(f"corrupted skill metadata for {sname!r}")
            if smeta.get("bundled", True):
                sdir = extract_dir / "skills" / sname
                if not (sdir / "SKILL.md").is_file():
                    raise SkillpackError(
                        f"corrupted skillpack: bundled skill {sname!r} is missing skills/{sname}/SKILL.md"
                    )
                actual_tree, actual_files = compute_tree_hash(sdir)
                expected_tree = str(smeta.get("tree_hash", ""))
                if expected_tree and actual_tree != expected_tree:
                    raise SkillpackError(
                        f"integrity verification failed for skill {sname!r}: "
                        f"expected tree_hash {expected_tree[:12]}, got {actual_tree[:12]}"
                    )
                expected_files = smeta.get("file_hashes")
                if isinstance(expected_files, dict) and expected_files:
                    norm_expected = {str(k): str(v) for k, v in expected_files.items()}
                    if actual_files != norm_expected:
                        raise SkillpackError(
                            f"file hash integrity mismatch in skill {sname!r}: package contents were modified"
                        )

        return doc, extract_dir, pack_sha256
    except BaseException:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise


def snapshot_from_skillpack(pack_path: Path) -> EnvironmentSnapshot:
    """Convert a ``.skillpack`` archive into an :class:`EnvironmentSnapshot` for ``skillporter diff``."""
    doc, extract_dir, _ = _extract_and_verify_skillpack(pack_path)
    try:
        skills_raw = doc.get("skills", {})
        entries: dict[str, SkillEnvironmentEntry] = {}
        if isinstance(skills_raw, dict):
            for sname, smeta in sorted(skills_raw.items()):
                if not isinstance(smeta, dict):
                    continue
                h_list = (
                    [str(x) for x in smeta.get("harnesses", [])] if isinstance(smeta.get("harnesses"), list) else []
                )
                fhashes = (
                    {str(k): str(v) for k, v in smeta.get("file_hashes", {}).items()}
                    if isinstance(smeta.get("file_hashes"), dict)
                    else {}
                )
                entries[sname] = SkillEnvironmentEntry(
                    name=sname,
                    version=str(smeta.get("version", "1.0.0")),
                    tree_hash=str(smeta.get("tree_hash", "")),
                    file_hashes=fhashes,
                    source=str(smeta.get("source", "")),
                    resolved_commit=str(smeta.get("resolved_commit", "")),
                    strategy=str(smeta.get("strategy", "copy")),
                    scope=str(doc.get("scope", "project")),
                    managed=True,
                    on_disk=bool(smeta.get("bundled", True)),
                    desired_harnesses=h_list,
                    installed_harnesses=h_list,
                    status="SYNCED",
                )
        raw_h = doc.get("harnesses", [])
        sel_h = [str(x) for x in raw_h] if isinstance(raw_h, list) else []
        return EnvironmentSnapshot(
            label=f"skillpack:{pack_path.name}",
            root=pack_path.resolve(),
            scope=str(doc.get("scope", "project")),
            active_profile=str(doc.get("active_profile", "")),
            selected_harnesses=sel_h,
            skills=entries,
            healthy=True,
        )
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def _resolve_import_targets(
    requested_harnesses: list[str],
    *,
    explicit_harnesses: list[str] | None,
    exclude_harnesses: set[str],
    detected_set: set[str],
    scope: str,
    only_detected: bool,
) -> tuple[list[str], list[str]]:
    """Return ``(selected_targets, missing_on_machine)`` for one skill during import."""
    candidates = list(explicit_harnesses) if explicit_harnesses is not None else list(requested_harnesses)
    if not candidates:
        candidates = sorted(detected_set) if detected_set else ["claude-code", "codex", "cursor"]

    missing_on_host: list[str] = []
    selected: list[str] = []
    for raw_h in candidates:
        try:
            h = harnesses.get(raw_h)
        except KeyError:
            missing_on_host.append(raw_h)
            continue
        if h.name in exclude_harnesses:
            continue
        scoped_paths = h.project_paths if scope == "project" else h.user_paths
        if not scoped_paths:
            missing_on_host.append(h.name)
            continue
        if h.name not in detected_set:
            missing_on_host.append(h.name)
            if only_detected and explicit_harnesses is None:
                continue
        if h.name not in selected:
            selected.append(h.name)

    return selected, sorted(set(missing_on_host))


def plan_import_skillpack(
    root: Path,
    pack_path: Path,
    *,
    scope: str | None = None,
    home: Path | None = None,
    explicit_harnesses: list[str] | None = None,
    exclude_harnesses: list[str] | None = None,
    only_detected: bool = False,
    on_conflict: str = "fail",
    force: bool = False,
    allow_risky: bool = False,
    max_risk_score: int | None = None,
) -> ImportPlan:
    """Validate a ``.skillpack`` and generate a complete restoration plan without writing files."""
    doc, extract_dir, pack_sha256 = _extract_and_verify_skillpack(pack_path)
    try:
        return _build_import_plan_from_extracted(
            root=root.resolve(),
            pack_path=pack_path.expanduser().resolve(),
            pack_sha256=pack_sha256,
            doc=doc,
            extract_dir=extract_dir,
            scope=scope,
            home=home,
            explicit_harnesses=explicit_harnesses,
            exclude_harnesses=exclude_harnesses,
            only_detected=only_detected,
            on_conflict=on_conflict,
            force=force,
            allow_risky=allow_risky,
            max_risk_score=max_risk_score,
        )
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def _build_import_plan_from_extracted(
    *,
    root: Path,
    pack_path: Path,
    pack_sha256: str,
    doc: dict[str, object],
    extract_dir: Path,
    scope: str | None,
    home: Path | None,
    explicit_harnesses: list[str] | None,
    exclude_harnesses: list[str] | None,
    only_detected: bool,
    on_conflict: str,
    force: bool,
    allow_risky: bool,
    max_risk_score: int | None,
) -> ImportPlan:
    source_scope = str(doc.get("scope", "project"))
    target_scope = scope or source_scope
    eff_conflict = "overwrite" if force else (on_conflict or "fail")
    excl_set = {harnesses.get(x).name for x in (exclude_harnesses or [])}

    detected_objs = harnesses.detect_harnesses(root, home=home)
    detected_set = {d.harness.name for d in detected_objs if d.installed}
    current_snap = capture_environment(root, scope=target_scope, home=home)

    skills_raw = doc["skills"]  # type: ignore[index]
    all_pack_skills = set(skills_raw.keys())  # type: ignore[union-attr]
    existing_skills = {k for k, v in current_snap.skills.items() if v.on_disk}

    plan_skills: list[dict[str, object]] = []
    target_by_skill: dict[str, list[str]] = {}
    all_missing_harnesses: set[str] = set()
    version_conflicts: list[str] = []
    dest_conflicts: list[str] = []
    sec_findings: list[dict[str, object]] = []
    sec_blocked: list[str] = []
    missing_deps: list[str] = []

    for sname, smeta in sorted(skills_raw.items()):  # type: ignore[union-attr]
        ver = str(smeta.get("version", "1.0.0"))
        thash = str(smeta.get("tree_hash", ""))
        req_h = [str(x) for x in smeta.get("harnesses", [])] if isinstance(smeta.get("harnesses"), list) else []
        targets, missing_h = _resolve_import_targets(
            req_h,
            explicit_harnesses=explicit_harnesses,
            exclude_harnesses=excl_set,
            detected_set=detected_set,
            scope=target_scope,
            only_detected=only_detected,
        )
        all_missing_harnesses.update(missing_h)
        target_by_skill[sname] = targets

        # Dependency availability check
        raw_deps = smeta.get("dependencies", {})
        if isinstance(raw_deps, dict):
            for dep_name, dep_constraint in sorted(raw_deps.items()):
                if dep_name not in all_pack_skills and dep_name not in existing_skills:
                    missing_deps.append(f"{sname} requires missing dependency {dep_name} ({dep_constraint})")

        # Version / content comparison against existing workspace
        if sname in current_snap.skills and current_snap.skills[sname].on_disk:
            cur_e = current_snap.skills[sname]
            if cur_e.tree_hash and thash and cur_e.tree_hash != thash:
                version_conflicts.append(
                    f"{sname}: local v{cur_e.version} ({cur_e.tree_hash[:8]}) != package v{ver} ({thash[:8]})"
                )

        if smeta.get("bundled", True):
            sdir = extract_dir / "skills" / sname
            issues = [i for i in validate(parse_skill(sdir / "SKILL.md")) if i.level == "error"]
            if issues:
                sec_blocked.append(f"{sname}: spec error ({issues[0]})")
            srep = scan_skill(sdir, offline=True)
            if target_scope == "project":
                from .policy import evaluate_policy, load_policy

                pol = load_policy(root)
                pol_errs = evaluate_policy(
                    pol,
                    skill_dirs=[sdir],
                    source_candidates=[str(smeta.get("source", ""))],
                    resolved_commit=str(smeta.get("resolved_commit", "")),
                    target_harnesses=targets,
                    sec_reports={sdir.name: srep},
                )
                sec_blocked.extend(f"{sname}: {pe}" for pe in pol_errs)
            for f in srep.findings:
                fd = f.to_dict()
                fd["skill"] = sname
                sec_findings.append(fd)
            exceeds = srep.exceeds_risk_threshold(max_risk_score)
            if srep.has_structural_escape:
                sec_blocked.append(f"{sname}: structural escape (non-overridable)")
            elif (not srep.passed or not srep.scan_complete or exceeds) and not allow_risky:
                sec_blocked.append(f"{sname}: security risk {srep.risk_score}/100 ({srep.recommendation})")

            if targets:
                iplan = plan_install(
                    root,
                    [sdir],
                    targets,
                    strategy=str(smeta.get("strategy", "copy")),
                    scope=target_scope,
                    force=(eff_conflict == "overwrite"),
                    on_conflict=eff_conflict,
                    home=home,
                )
                dest_conflicts.extend(iplan.conflicts)

        plan_skills.append(
            {
                "name": sname,
                "version": ver,
                "tree_hash": thash[:12],
                "bundled": bool(smeta.get("bundled", True)),
                "source": str(smeta.get("source", "")),
                "target_harnesses": targets,
            }
        )

    profiles_raw = doc.get("profiles", {})
    prof_names = sorted(profiles_raw.keys()) if isinstance(profiles_raw, dict) else []

    return ImportPlan(
        pack_path=pack_path,
        pack_sha256=pack_sha256,
        schema_version=int(doc.get("schema_version", SKILLPACK_SCHEMA_VERSION)),  # type: ignore[arg-type]
        source_scope=source_scope,
        target_scope=target_scope,
        skills=plan_skills,
        available_harnesses=sorted(detected_set),
        missing_harnesses=sorted(all_missing_harnesses),
        target_harnesses_by_skill=target_by_skill,
        version_conflicts=version_conflicts,
        destination_conflicts=dest_conflicts,
        security_findings=sec_findings,
        security_blocked=sec_blocked,
        missing_dependencies=missing_deps,
        profiles_included=prof_names,
    )


def import_skillpack(
    root: Path,
    pack_path: Path,
    *,
    scope: str | None = None,
    home: Path | None = None,
    explicit_harnesses: list[str] | None = None,
    exclude_harnesses: list[str] | None = None,
    only_detected: bool = False,
    on_conflict: str = "fail",
    force: bool = False,
    allow_risky: bool = False,
    max_risk_score: int | None = None,
    restore_manifest: bool = True,
    dry_run: bool = False,
) -> dict[str, object]:
    """Validate and restore a ``.skillpack`` environment transactionally."""
    root = root.resolve()
    doc, extract_dir, pack_sha256 = _extract_and_verify_skillpack(pack_path)
    try:
        plan = _build_import_plan_from_extracted(
            root=root,
            pack_path=pack_path.expanduser().resolve(),
            pack_sha256=pack_sha256,
            doc=doc,
            extract_dir=extract_dir,
            scope=scope,
            home=home,
            explicit_harnesses=explicit_harnesses,
            exclude_harnesses=exclude_harnesses,
            only_detected=only_detected,
            on_conflict=on_conflict,
            force=force,
            allow_risky=allow_risky,
            max_risk_score=max_risk_score,
        )
        if dry_run:
            return {"dry_run": True, "plan": plan.to_dict(), "installed": [], "skipped": []}

        if plan.security_blocked:
            raise SkillpackError("import blocked by security/validation policy: " + "; ".join(plan.security_blocked))
        if plan.missing_dependencies:
            raise SkillpackError(
                "import blocked by unresolved skill dependencies: " + "; ".join(plan.missing_dependencies)
            )
        eff_conflict = "overwrite" if force else (on_conflict or "fail")
        if plan.destination_conflicts and eff_conflict == "fail":
            raise SkillpackError(
                "destination conflict(s) detected (use --force / --on-conflict overwrite, or --on-conflict skip): "
                + "; ".join(plan.destination_conflicts)
            )

        skills_raw = doc["skills"]  # type: ignore[index]
        target_scope = plan.target_scope
        installed_rows: list[dict[str, str]] = []
        skipped_rows: list[dict[str, str]] = []
        effective_source_by_skill: dict[str, str] = {}

        with workspace_lock(root):
            pre_state = load_state(root, scope=target_scope, home=home)
            completed: list[tuple[str, list[str], bool]] = []
            try:
                for sname, smeta in sorted(skills_raw.items()):  # type: ignore[union-attr]
                    targets = plan.target_harnesses_by_skill.get(sname, [])
                    if not targets:
                        skipped_rows.append(
                            {"skill": sname, "harness": "(none)", "reason": "no matching target harnesses"}
                        )
                        continue

                    resolved_remote = None
                    try:
                        if smeta.get("bundled", True):
                            sdir = extract_dir / "skills" / sname
                        else:
                            resolved_remote = resolve_source(
                                str(smeta["source"]),
                                base_dir=root,
                                ref_override=str(smeta.get("resolved_commit", "")),
                            )
                            matches = [d for d in resolved_remote.skill_dirs if d.name == sname]
                            sdir = matches[0] if matches else resolved_remote.skill_dirs[0]
                            srep = scan_skill(sdir, offline=True)
                            if srep.has_structural_escape or (not srep.passed and not allow_risky):
                                raise SkillpackError(f"fetched source for {sname!r} blocked by static security scan")
                            expected_h = str(smeta.get("tree_hash", ""))
                            if expected_h:
                                actual_h, _ = compute_tree_hash(sdir)
                                if actual_h != expected_h:
                                    raise SkillpackError(
                                        f"fetched source hash mismatch for {sname!r}: "
                                        f"expected {expected_h[:12]}, got {actual_h[:12]}"
                                    )

                        raw_src = str(smeta.get("source", ""))
                        res = install(
                            root,
                            sdir,
                            targets,
                            strategy=str(smeta.get("strategy", "copy")),
                            scope=target_scope,
                            force=(eff_conflict == "overwrite"),
                            on_conflict=eff_conflict,
                            home=home,
                            source=raw_src,
                            resolved_commit=str(smeta.get("resolved_commit", "")),
                            version=str(smeta.get("version", "1.0.0")),
                            record_state=True,
                            skill_name_override=sname,
                        )
                        eff_src = raw_src
                        non_skipped = [r for r in res if r.action != "skipped"]
                        if non_skipped and (
                            not raw_src
                            or raw_src.startswith("local:")
                            or (raw_src.startswith(("./", "../")) and not (root / raw_src).exists())
                        ):
                            first_dest = non_skipped[0].dest
                            try:
                                eff_src = "./" + first_dest.resolve().relative_to(root).as_posix()
                            except ValueError:
                                eff_src = str(first_dest.resolve())
                            cur_recs = load_state(root, scope=target_scope, home=home)
                            if sname in cur_recs:
                                cur_recs[sname].source = eff_src
                                save_state(root, cur_recs, scope=target_scope, home=home)
                        effective_source_by_skill[sname] = eff_src

                        completed.append((sname, targets, sname in pre_state))
                        for r in res:
                            row = {
                                "skill": r.skill,
                                "harness": r.harness,
                                "dest": str(r.dest),
                                "action": r.action,
                                "detail": r.detail,
                            }
                            if r.action == "skipped":
                                skipped_rows.append(row)
                            else:
                                installed_rows.append(row)
                    finally:
                        if resolved_remote is not None:
                            resolved_remote.cleanup()

                if restore_manifest and target_scope == "project":
                    existing_manifest = load_manifest(root)
                    raw_m = doc.get("manifest")
                    if existing_manifest is None and isinstance(raw_m, dict):
                        restored_m = parse_manifest(json.dumps(raw_m))
                        for ms in restored_m.skills:
                            if ms.name in effective_source_by_skill:
                                ms.source = effective_source_by_skill[ms.name]
                            if ms.name in plan.target_harnesses_by_skill:
                                ms.harnesses = plan.target_harnesses_by_skill[ms.name]
                        save_manifest(root, restored_m)
                    elif existing_manifest is not None:
                        have = {s.name for s in existing_manifest.skills}
                        for sname, smeta in sorted(skills_raw.items()):  # type: ignore[union-attr]
                            if sname not in have and sname in effective_source_by_skill:
                                raw_deps = smeta.get("dependencies", {})
                                deps = (
                                    [SkillDependency(name=str(k), version=str(v)) for k, v in raw_deps.items()]
                                    if isinstance(raw_deps, dict)
                                    else []
                                )
                                existing_manifest.skills.append(
                                    ManifestSkillSpec(
                                        name=sname,
                                        source=effective_source_by_skill[sname],
                                        ref=str(smeta.get("resolved_commit", ""))[:12],
                                        version=str(smeta.get("version", "1.0.0")),
                                        harnesses=plan.target_harnesses_by_skill.get(sname, []),
                                        dependencies=deps,
                                    )
                                )
                        save_manifest(root, existing_manifest)

                    # Update lockfile deterministically
                    lock = Lockfile()
                    for sname, smeta in sorted(skills_raw.items()):  # type: ignore[union-attr]
                        targets = plan.target_harnesses_by_skill.get(sname, [])
                        if not targets or sname not in effective_source_by_skill:
                            continue
                        fhashes = (
                            {str(k): str(v) for k, v in smeta.get("file_hashes", {}).items()}
                            if isinstance(smeta.get("file_hashes"), dict)
                            else {}
                        )
                        deps_d = (
                            {str(k): str(v) for k, v in smeta.get("dependencies", {}).items()}
                            if isinstance(smeta.get("dependencies"), dict)
                            else {}
                        )
                        lock.skills[sname] = LockedSkill(
                            name=sname,
                            source=effective_source_by_skill[sname],
                            resolved_commit=str(smeta.get("resolved_commit", "")),
                            version=str(smeta.get("version", "1.0.0")),
                            tree_hash=str(smeta.get("tree_hash", "")),
                            strategy=str(smeta.get("strategy", "copy")),
                            installed_targets=targets,
                            dependencies=deps_d,
                            file_hashes=fhashes,
                            adapter_version=__version__,
                            scope=target_scope,
                        )
                    if lock.skills:
                        save_lockfile(root, lock)

                profiles_raw = doc.get("profiles")
                if isinstance(profiles_raw, dict) and profiles_raw:
                    from .profiles import import_profiles_dict

                    import_profiles_dict(
                        root, profiles_raw, scope=target_scope, home=home, overwrite=eff_conflict == "overwrite"
                    )

            except (InstallError, DependencyError, DependencyCycleError, DependencyConflictError) as exc:
                for sname, targets, existed_in_pre in reversed(completed):
                    if not existed_in_pre:
                        with contextlib.suppress(Exception):
                            uninstall(root, sname, targets, scope=target_scope, home=home, record_state=True)
                save_state(root, pre_state, scope=target_scope, home=home)
                raise SkillpackError(f"import failed and rolled back cleanly: {exc}") from exc

        return {
            "dry_run": False,
            "plan": plan.to_dict(),
            "installed": installed_rows,
            "skipped": skipped_rows,
            "missing_harnesses": plan.missing_harnesses,
        }
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
