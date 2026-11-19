"""Doctor repair preview and apply against temporary installations."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from skillporter.cli import main
from skillporter.manifest import LOCKFILE_FILENAME
from skillporter.policy import POLICY_FILENAME
from skillporter.state import load_state


def _skill(base: Path, body: str = "Original instructions.") -> Path:
    base.mkdir(parents=True)
    (base / "SKILL.md").write_text(
        f"---\nname: helper\ndescription: A helper for validating a workflow.\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return base


def _doctor(root, capsys, *flags):
    capsys.readouterr()
    rc = main(["doctor", str(root), "--fix", "--json", *flags])
    return rc, json.loads(capsys.readouterr().out)


def _files(root):
    return {
        p.relative_to(root): (p.readlink() if p.is_symlink() else p.read_bytes(), p.lstat().st_mtime_ns)
        for p in root.rglob("*") if (p.is_symlink() or p.is_file()) and p.name != "lock"
    }


def test_preview_then_restore_verified_snapshot_and_missing_install(tmp_path, capsys):
    root = tmp_path / "project"
    root.mkdir()
    src = _skill(tmp_path / "upstream" / "helper")
    assert main(["add", str(src), "--path", str(root), "--harness", "claude-code,windsurf,gemini-cli"]) == 0
    assert main(["lock", str(root)]) == 0
    claude = root / ".claude" / "skills" / "helper"
    windsurf = root / ".windsurf" / "skills" / "helper"
    shared = root / ".agents" / "skills" / "helper"
    assert shared.is_dir()
    shutil.rmtree(windsurf)
    (claude / "notes.txt").write_text("Local changes.", encoding="utf-8")
    stale = root / ".skillporter" / ".state.json.abandoned.tmp"
    stale.write_text("old state write", encoding="utf-8")
    age = time.time() - 3600
    os.utime(stale, (age, age))
    before = _files(root)

    rc, preview = _doctor(root, capsys, "--dry-run")
    assert rc == 1 and not preview["healthy"]
    assert preview["repaired"] == [] and preview["stale_tmp_removed"] == 0
    plan = preview["repair_plan"]
    assert {(step["action"], step["path"]) for step in plan} == {
        ("replace", str(claude)), ("create", str(windsurf)), ("remove-stale-temp", str(stale)),
    }
    assert str(shared) not in {step["path"] for step in plan}  # already synchronized copies stay untouched
    replace = next(step for step in plan if step["action"] == "replace")
    assert Path(replace["source"]) == shared  # the copy that still matches the lockfile, never the newest file
    assert str(root / ".skillporter" / "backups" / "helper") in replace["impact"]
    assert _files(root) == before

    capsys.readouterr()
    assert main(["doctor", str(root), "--fix", "--dry-run"]) == 1
    text = capsys.readouterr().out
    assert "Would replace" in text and str(claude) in text and str(stale) in text
    assert _files(root) == before

    rc, applied = _doctor(root, capsys)
    assert rc == 0 and applied["healthy"]
    assert applied["repair_plan"] == plan
    assert len(applied["repaired"]) == 2 and applied["stale_tmp_removed"] == 1
    assert not stale.exists() and not (claude / "notes.txt").exists()
    assert (windsurf / "SKILL.md").read_bytes() == (src / "SKILL.md").read_bytes()
    rec = load_state(root)["helper"]
    assert rec.source == str(src) and Path(rec.history[0].backup_dir, "notes.txt").is_file()

    after = _files(root)
    rc, rerun = _doctor(root, capsys)
    assert rc == 0 and rerun["repair_plan"] == [] and rerun["repaired"] == []
    assert _files(root) == after


@pytest.mark.parametrize("explicit", [False, True])
def test_conflicting_unmanaged_copies_are_not_overwritten(tmp_path, capsys, explicit):
    old = _skill(tmp_path / ".claude" / "skills" / "helper")
    new = _skill(tmp_path / ".windsurf" / "skills" / "helper", "Different instructions.")
    newer = time.time() + 60
    os.utime(new / "SKILL.md", (newer, newer))
    flags = ("--harness", "claude-code", "--harness", "windsurf") if explicit else ()
    before = _files(tmp_path)
    _, preview = _doctor(tmp_path, capsys, "--dry-run", *flags)
    rc, applied = _doctor(tmp_path, capsys, *flags)
    assert rc == 1 and applied["repair_plan"] == preview["repair_plan"]
    assert {p["path"] for p in applied["repair_plan"]} == {str(old), str(new)}
    assert all(p["action"] == "refuse" and "conflict" in p["impact"] for p in applied["repair_plan"])
    assert _files(tmp_path) == before and not (tmp_path / ".skillporter").exists()


@pytest.mark.parametrize("broken_link", [False, True])
def test_unscoped_copy_and_unrelated_broken_link_are_left_alone(tmp_path, capsys, broken_link):
    src = _skill(tmp_path / ".claude" / "skills" / "helper")
    link = src.parent / "unrelated"
    if broken_link:
        try:
            link.symlink_to(tmp_path / "missing", target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")

    before = _files(tmp_path)
    _, preview = _doctor(tmp_path, capsys, "--dry-run")
    rc, applied = _doctor(tmp_path, capsys)
    assert rc == 1 and applied["repair_plan"] == preview["repair_plan"]
    assert {p["path"] for p in applied["repair_plan"]} == ({str(src), str(link)} if broken_link else {str(src)})
    assert all(p["action"] == "refuse" for p in applied["repair_plan"])
    assert _files(tmp_path) == before and not (tmp_path / ".agents").exists()


@pytest.mark.parametrize("block", ["policy", "lockfile"])
def test_user_scope_repair_refuses_without_changing_either_scope(tmp_path, capsys, block):
    root = tmp_path / "project"
    root.mkdir()
    src = _skill(tmp_path / "upstream" / "helper")
    assert main([
        "add", str(src), "--path", str(root), "--scope", "user", "--harness", "claude-code,windsurf",
    ]) == 0
    dest = Path(load_state(root, scope="user")["helper"].destinations[-1])
    shutil.rmtree(dest)
    stop_path = root / (POLICY_FILENAME if block == "policy" else LOCKFILE_FILENAME)
    stop_path.write_text("allowed_harnesses:\n  - claude-code\n" if block == "policy" else "{", encoding="utf-8")
    before = _files(root), _files(Path.home())
    _, preview = _doctor(root, capsys, "--scope", "user", "--dry-run")
    rc, applied = _doctor(root, capsys, "--scope", "user")
    assert rc == 1 and applied["repair_plan"] == preview["repair_plan"]
    assert applied["repair_plan"][0]["action"] == "refuse"
    assert applied["repair_plan"][0]["path"] == str(dest if block == "policy" else stop_path)
    assert (_files(root), _files(Path.home())) == before
