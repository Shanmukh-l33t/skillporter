"""State Management, Ownership Tracking, Backups, and Rollback Engine.

Tracks every Skillporter-managed installation in ``.skillporter/state.json``
(project scope) or ``~/.skillporter/state.json`` (user scope), including:
  * skill name, source, resolved commit, version, and SHA-256 tree hash
  * installed target destinations and harnesses
  * ownership verification (so unmanaged user files are never silently clobbered)
  * crash-safe staged backup snapshots under ``.skillporter/backups/<skill>/<id>/``
    supporting transactional restore and ``skillporter rollback <skill>``.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import atomic_write_text
from .security import compute_tree_hash

STATE_SCHEMA_VERSION = 1


@dataclass
class BackupEntry:
    """One historical backup snapshot of an installed skill."""

    backup_id: str
    version: str
    tree_hash: str
    source: str
    resolved_commit: str
    timestamp: str
    backup_dir: str

    def to_dict(self) -> dict[str, object]:
        return {
            "backup_id": self.backup_id,
            "version": self.version,
            "tree_hash": self.tree_hash,
            "source": self.source,
            "resolved_commit": self.resolved_commit,
            "timestamp": self.timestamp,
            "backup_dir": self.backup_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BackupEntry:
        return cls(
            backup_id=str(data.get("backup_id", "")),
            version=str(data.get("version", "")),
            tree_hash=str(data.get("tree_hash", "")),
            source=str(data.get("source", "")),
            resolved_commit=str(data.get("resolved_commit", "")),
            timestamp=str(data.get("timestamp", "")),
            backup_dir=str(data.get("backup_dir", "")),
        )


@dataclass
class ManagedSkillRecord:
    """State record for one installed skill."""

    name: str
    source: str
    resolved_commit: str = ""
    version: str = "1.0.0"
    tree_hash: str = ""
    strategy: str = "copy"
    scope: str = "project"
    harnesses: list[str] = field(default_factory=list)
    destinations: list[str] = field(default_factory=list)
    managed_by: str = "skillporter"
    updated_at: str = ""
    history: list[BackupEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source": self.source,
            "resolved_commit": self.resolved_commit,
            "version": self.version,
            "tree_hash": self.tree_hash,
            "strategy": self.strategy,
            "scope": self.scope,
            "harnesses": sorted(set(self.harnesses)),
            "destinations": sorted(set(self.destinations)),
            "managed_by": self.managed_by,
            "updated_at": self.updated_at,
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ManagedSkillRecord:
        raw_hist = data.get("history", [])
        hist = [BackupEntry.from_dict(x) for x in raw_hist if isinstance(x, dict)] if isinstance(raw_hist, list) else []
        raw_h = data.get("harnesses", [])
        raw_d = data.get("destinations", [])
        return cls(
            name=str(data.get("name", "")),
            source=str(data.get("source", "")),
            resolved_commit=str(data.get("resolved_commit", "")),
            version=str(data.get("version", "1.0.0")),
            tree_hash=str(data.get("tree_hash", "")),
            strategy=str(data.get("strategy", "copy")),
            scope=str(data.get("scope", "project")),
            harnesses=[str(x) for x in raw_h] if isinstance(raw_h, list) else [],
            destinations=[str(x) for x in raw_d] if isinstance(raw_d, list) else [],
            managed_by=str(data.get("managed_by", "skillporter")),
            updated_at=str(data.get("updated_at", "")),
            history=hist,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_dir(root: Path, scope: str = "project", home: Path | None = None) -> Path:
    if scope == "user":
        base = home or Path.home()
        return base / ".skillporter"
    return root / ".skillporter"


def state_file(root: Path, scope: str = "project", home: Path | None = None) -> Path:
    return state_dir(root, scope=scope, home=home) / "state.json"


def load_state(root: Path, scope: str = "project", home: Path | None = None) -> dict[str, ManagedSkillRecord]:
    sf = state_file(root, scope=scope, home=home)
    if not sf.is_file():
        return {}
    try:
        raw = json.loads(sf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    skills_raw = raw.get("skills", {}) if isinstance(raw, dict) else {}
    records: dict[str, ManagedSkillRecord] = {}
    if isinstance(skills_raw, dict):
        for k, v in skills_raw.items():
            if isinstance(v, dict):
                records[k] = ManagedSkillRecord.from_dict(v)
    return records


def save_state(
    root: Path,
    records: dict[str, ManagedSkillRecord],
    scope: str = "project",
    home: Path | None = None,
) -> Path:
    sf = state_file(root, scope=scope, home=home)
    sf.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": _now_iso(),
        "skills": {k: v.to_dict() for k, v in sorted(records.items())},
    }
    atomic_write_text(sf, json.dumps(payload, indent=2) + "\n")
    return sf


def is_managed_destination(
    root: Path,
    skill_name: str,
    dest: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
) -> bool:
    """Return True if *dest* is recorded as managed by Skillporter for *skill_name*."""
    records = load_state(root, scope=scope, home=home)
    rec = records.get(skill_name)
    if not rec:
        return False
    resolved_str = str(dest.resolve())
    raw_str = str(dest)
    return resolved_str in rec.destinations or raw_str in rec.destinations


def snapshot_skill_for_rollback(
    root: Path,
    skill_name: str,
    existing_dir: Path,
    record: ManagedSkillRecord | None = None,
    *,
    scope: str = "project",
    home: Path | None = None,
) -> BackupEntry | None:
    """Copy an existing skill tree into ``.skillporter/backups/<skill>/<id>/<skill>`` atomically."""
    if not existing_dir.exists() or existing_dir.is_symlink():
        return None
    tree_hash, _ = compute_tree_hash(existing_dir)
    if not tree_hash:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"{ts}-{tree_hash[:12]}"
    sdir = state_dir(root, scope=scope, home=home)
    bdir = sdir / "backups" / skill_name / backup_id / skill_name
    if bdir.exists():
        existing_bhash, _ = compute_tree_hash(bdir)
        if existing_bhash != tree_hash:
            shutil.rmtree(bdir, ignore_errors=True)

    if not bdir.exists():
        bdir.parent.mkdir(parents=True, exist_ok=True)
        tmp_stage = bdir.parent / f".stage-{uuid.uuid4().hex[:8]}"
        try:
            shutil.copytree(existing_dir, tmp_stage, symlinks=True)
            shutil.move(str(tmp_stage), str(bdir))
        except BaseException:
            shutil.rmtree(tmp_stage, ignore_errors=True)
            raise

    return BackupEntry(
        backup_id=backup_id,
        version=record.version if record else "1.0.0",
        tree_hash=tree_hash,
        source=record.source if record else str(existing_dir),
        resolved_commit=record.resolved_commit if record else "",
        timestamp=_now_iso(),
        backup_dir=str(bdir),
    )


def record_installation(
    root: Path,
    *,
    skill_name: str,
    source: str,
    skill_dir: Path,
    harnesses: list[str],
    destinations: list[Path],
    strategy: str = "copy",
    scope: str = "project",
    resolved_commit: str = "",
    version: str = "1.0.0",
    backup_entry: BackupEntry | None = None,
    backup_entries: list[BackupEntry] | None = None,
    home: Path | None = None,
) -> ManagedSkillRecord:
    """Record or update a managed skill installation in state.json."""
    records = load_state(root, scope=scope, home=home)
    existing = records.get(skill_name)
    tree_hash, _ = compute_tree_hash(skill_dir)

    history: list[BackupEntry] = list(existing.history) if existing else []
    candidates: list[BackupEntry] = []
    if backup_entry:
        candidates.append(backup_entry)
    if backup_entries:
        candidates.extend(backup_entries)

    for cand in candidates:
        if cand.tree_hash != tree_hash and all(b.tree_hash != cand.tree_hash for b in history):
            history.append(cand)
    history = history[-10:]  # keep most recent 10 snapshots

    merged_harnesses = sorted(set((existing.harnesses if existing else []) + list(harnesses)))
    merged_dests = sorted(
        set((existing.destinations if existing else []) + [str(d.resolve()) for d in destinations])
    )

    rec = ManagedSkillRecord(
        name=skill_name,
        source=source or (existing.source if existing else str(skill_dir)),
        resolved_commit=resolved_commit or (existing.resolved_commit if existing else ""),
        version=version or (existing.version if existing else "1.0.0"),
        tree_hash=tree_hash,
        strategy=strategy,
        scope=scope,
        harnesses=merged_harnesses,
        destinations=merged_dests,
        updated_at=_now_iso(),
        history=history,
    )
    records[skill_name] = rec
    save_state(root, records, scope=scope, home=home)
    return rec
