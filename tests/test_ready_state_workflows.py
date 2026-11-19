"""Source-checkout CLI regressions for profile, move and init state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skillporter.manifest import load_manifest


@pytest.fixture
def cli(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    env = os.environ.copy()
    for key in ("APPDATA", "LOCALAPPDATA", "HERMES_HOME"):
        env[key] = str(tmp_path / key.lower())

    def run(*args, code=0):
        result = subprocess.run(
            [sys.executable, "-m", "skillporter", *map(str, args)],
            cwd=ws,
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == code, result.stdout + result.stderr
        return result.stdout

    return ws, run


def skill(base, name="notes", body="Keep useful project notes."):
    md = base / name / "SKILL.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(f"---\nname: {name}\ndescription: Write project notes.\n---\n\n{body}\n", encoding="utf-8")
    return md


@pytest.mark.parametrize("prefer", [False, True])
def test_sync_excludes_targets_in_preview_and_apply(cli, prefer):
    ws, run = cli
    src = skill(ws / "upstream").parent
    (ws / "skillporter.yaml").write_text(
        "harnesses: [claude-code, hermes]\nskills:\n"
        "  - name: notes\n    source: ./upstream/notes\n    harnesses: [claude-code, hermes]\n",
        encoding="utf-8",
    )
    flags = ["--prefer", str(src)] if prefer else []
    args = ("sync", "--exclude-harness", "hermes", "--json", *flags)
    preview = json.loads(run(*args, "--dry-run"))
    expected = ws / ".claude/skills/notes"
    assert preview["destinations"] == [str(expected)]
    assert not expected.exists()
    run(*args)
    assert (expected / "SKILL.md").is_file()
    assert not (ws / ".hermes/skills/notes").exists()


def test_profile_round_trip_counts_actual_targets_and_writes(cli, tmp_path):
    ws, run = cli
    src = skill(tmp_path / "src")
    targets = ["claude-code", "codex", "cursor"]
    run("add", src.parent, "--harness", ",".join(targets), "--offline")
    run("profile", "save", "rel")
    profile = json.loads(run("profile", "show", "rel", "--json"))
    print("profile header:", profile["harnesses"], "skill targets:", profile["skills"][0]["harnesses"])
    pack = tmp_path / "rel.skillpack"
    run("export", pack)
    restored = tmp_path / "restored"
    run("import", pack, "--path", restored)
    # Restore into a partial environment: two targets share one missing directory.
    (restored / ".agents/skills/notes/SKILL.md").unlink()
    (restored / ".agents/skills/notes").rmdir()
    out = run("profile", "use", "rel", "--path", restored)
    print(out, "skill files:", sorted(str(p.relative_to(restored)) for p in restored.glob(".*/skills/*/SKILL.md")))
    assert profile["harnesses"] == profile["skills"][0]["harnesses"] == targets
    assert sorted(p.relative_to(restored).as_posix() for p in restored.glob(".*/skills/*/SKILL.md")) == [
        ".agents/skills/notes/SKILL.md", ".claude/skills/notes/SKILL.md"
    ]
    assert "3 harness target(s)" in out and "1 destination(s) written" in out
    report = json.loads(run("profile", "use", "rel", "--path", restored, "--json"))
    assert report["synced_skills"] == 1
    assert report["harnesses"] == targets
    assert report["harness_targets"] == 3
    assert report["destinations_written"] == 0


def test_profile_save_explicit_targets_control_activation(cli, tmp_path):
    ws, run = cli
    src = skill(tmp_path / "src")
    run("add", src.parent, "--harness", "claude-code,codex", "--offline")
    run("profile", "save", "narrow", "--harness", "codex")
    report = json.loads(run("profile", "use", "narrow", "--json"))
    profile = json.loads(run("profile", "show", "narrow", "--json"))
    assert profile["skills"][0]["harnesses"] == report["harnesses"] == ["codex"]
    assert (ws / ".claude/skills/notes/SKILL.md").is_file()  # Activation doesn't prune other copies.


def test_adopt_move_outdated_and_rollback_keep_the_local_origin(cli):
    ws, run = cli
    original = skill(ws / ".claude/skills")
    original_bytes = original.read_bytes()
    run("init")
    run("adopt", "notes")
    run("lock")
    run("move", "notes", "--from", "claude-code", "--to", "hermes")
    moved = ws / ".hermes/skills/notes/SKILL.md"
    assert moved.read_bytes() == original_bytes
    assert not original.exists()
    row, = json.loads(run("outdated", "notes", "--json"))["skills"]
    print(row)
    assert row["status"] == "UP-TO-DATE"
    assert (ws / row["source"]).resolve() == moved.parent
    manifest = load_manifest(ws)
    assert manifest and manifest.skills[0].source == row["source"]
    run("lock", "--check")
    moved.write_text(moved.read_text(encoding="utf-8") + "\nA local edit.\n", encoding="utf-8")
    run("rollback", "notes", "--dry-run", code=2)  # The preview only checks update history, not the baseline.
    assert moved.read_bytes() != original_bytes
    run("rollback", "notes")
    assert moved.read_bytes() == original_bytes
    assert not original.exists()
    assert not (ws / ".agents/skills/notes").exists()
    run("lock", "--check")


@pytest.mark.parametrize("conflict,code", [("fail", 2), ("skip", 0)])
def test_move_conflict_preserves_adopted_source_and_tracking(cli, conflict, code):
    ws, run = cli
    original = skill(ws / ".claude/skills")
    run("adopt", "notes")
    state = ws / ".skillporter/state.json"
    before = original.read_bytes(), state.read_bytes()
    other = skill(ws / ".hermes/skills", body="Different notes already live here.")
    other_before = other.read_bytes()
    # On failure the first target is rolled back, too.
    targets = "codex,hermes" if conflict == "fail" else "hermes"
    run("move", "notes", "--from", "claude-code", "--to", targets, "--on-conflict", conflict, code=code)
    assert original.is_file()
    assert (original.read_bytes(), state.read_bytes()) == before
    assert other.read_bytes() == other_before
    assert not (ws / ".agents/skills/notes").exists()


def test_move_preserves_external_upstream(cli, tmp_path):
    ws, run = cli
    src = skill(tmp_path / "src")
    run("add", src.parent, "--harness", "claude-code", "--offline")
    run("move", "notes", "--from", "claude-code", "--to", "cursor", "--isolated")
    row, = json.loads(run("outdated", "notes", "--json"))["skills"]
    assert row["status"] == "UP-TO-DATE"
    assert (ws / row["source"]).resolve() == src.parent
    assert src.read_bytes() == (ws / ".cursor/skills/notes/SKILL.md").read_bytes()


@pytest.mark.parametrize("targets", ["claude-code,codex,hermes", "claude-code,codex,cursor"])
def test_init_uses_add_targets_and_keeps_lock_check_clean(cli, tmp_path, targets):
    ws, run = cli
    src = skill(tmp_path / "src")
    run("add", src.parent, "--harness", targets, "--offline")
    init = json.loads(run("init", "--json"))
    print(init)
    assert init["harnesses"] == sorted(targets.split(","))
    sync = json.loads(run("sync", "--json"))
    assert sorted(row["harness"] for row in sync["synchronized"]) == init["harnesses"]
    run("lock")
    assert "0 drift" in run("lock", "--check")
    manifest = load_manifest(ws)
    assert manifest and (ws / manifest.skills[0].source).resolve() == src.parent


def test_init_and_sync_keep_per_skill_targets_separate(cli, tmp_path):
    ws, run = cli
    for name, target in (("notes", "codex"), ("draft", "hermes")):
        run("add", skill(tmp_path / "src", name).parent, "--harness", target, "--offline")
    assert json.loads(run("init", "--json"))["harnesses"] == ["codex", "hermes"]
    preview = json.loads(run("sync", "--dry-run", "--json"))
    assert {Path(p).relative_to(ws).as_posix() for p in preview["destinations"]} == {
        ".agents/skills/notes", ".hermes/skills/draft"
    }
    run("sync")
    assert not (ws / ".agents/skills/draft").exists()
    assert not (ws / ".hermes/skills/notes").exists()
    run("lock")
    run("lock", "--check")


@pytest.mark.parametrize("with_managed", [False, True])
def test_init_does_not_assign_untracked_shared_readers(cli, tmp_path, with_managed):
    ws, run = cli
    skill(ws / ".agents/skills")
    targets = ["hermes"] if with_managed else []
    if with_managed:
        run("add", skill(tmp_path / "src", "draft").parent, "--harness", "hermes", "--offline")
    assert json.loads(run("init", "--json"))["harnesses"] == targets
    manifest = load_manifest(ws)
    assert manifest and manifest.harnesses == targets
    run("sync")
    assert sorted(p.relative_to(ws).as_posix() for p in ws.glob(".*/skills/notes/SKILL.md")) == [
        ".agents/skills/notes/SKILL.md"
    ]
    run("lock", "--check")
