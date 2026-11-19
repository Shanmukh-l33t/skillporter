"""Regression tests for remove / update / add --dry-run fixes (D3, D4, B19, D7, B15, D13)."""

from __future__ import annotations

import builtins
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skillporter.cli import build_parser, main
from skillporter.manifest import load_lockfile, load_manifest, save_manifest
from skillporter.state import load_state


def _skill(base: Path, name: str, *, body: str = "Safe instructions.\n") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Execute {name} workflow reliably. Use when running {name}.\n"
        f"license: MIT\nmetadata:\n  version: \"1.0.0\"\n---\n\n# {name}\n\n{body}",
        encoding="utf-8",
    )
    return sdir


class _FakeStdin(io.StringIO):
    def __init__(self, tty: bool, text: str = "") -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    monkeypatch.delenv("SKILLPORTER_HARNESS_PATHS", raising=False)


def _ws_with_skill(tmp_path: Path, name: str = "rm-skill", harness: str = "claude-code,windsurf") -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _skill(tmp_path / "upstream", name)
    assert main(["add", str(src), "--harness", harness, "--path", str(ws), "--json"]) == 0
    return ws, src


# ---------------------------------------------------------------- D3


def test_remove_without_harness_non_tty_requires_yes(tmp_path, monkeypatch, capsys):
    ws, src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(False))
    rc = main(["remove", "rm-skill", "--path", str(ws)])
    cap = capsys.readouterr()
    assert rc == 2
    assert "-y" in cap.err and "--dry-run" in cap.err
    assert "would-remove" in cap.out
    assert (ws / ".claude" / "skills" / "rm-skill" / "SKILL.md").is_file()
    assert (ws / ".windsurf" / "skills" / "rm-skill" / "SKILL.md").is_file()
    assert "rm-skill" in load_state(ws)


def test_remove_without_harness_yes_flag_skips_prompt(tmp_path, monkeypatch, capsys):
    ws, src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(True))

    def _boom(*_a, **_k):
        raise AssertionError("must not prompt when -y is given")

    monkeypatch.setattr(builtins, "input", _boom)
    assert main(["remove", "rm-skill", "-y", "--path", str(ws), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(r["harness"] for r in payload["results"] if r["action"] == "removed") == ["claude-code", "windsurf"]
    assert not (ws / ".claude" / "skills" / "rm-skill").exists()
    assert (src / "SKILL.md").is_file()


def test_remove_without_harness_force_flag_is_accepted_non_tty(tmp_path, monkeypatch, capsys):
    ws, _src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(False))
    # `--force` is not a registered flag on remove; the handler honours it only when present on the namespace.
    from skillporter.commands.remove import cmd_uninstall

    ns = build_parser().parse_args(["remove", "rm-skill", "--path", str(ws), "--json"])
    ns.force = True
    assert cmd_uninstall(ns) == 0
    assert not (ws / ".claude" / "skills" / "rm-skill").exists()


def test_remove_without_harness_tty_prompt_defaults_to_no(tmp_path, monkeypatch, capsys):
    ws, _src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(True))
    monkeypatch.setattr(builtins, "input", lambda *_a, **_k: "")
    rc = main(["remove", "rm-skill", "--path", str(ws)])
    out = capsys.readouterr()
    assert rc != 0
    assert "would-remove" in out.out
    assert (ws / ".claude" / "skills" / "rm-skill" / "SKILL.md").is_file()
    assert "rm-skill" in load_state(ws)


def test_remove_without_harness_tty_prompt_yes_removes(tmp_path, monkeypatch, capsys):
    ws, src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(True))
    monkeypatch.setattr(builtins, "input", lambda *_a, **_k: "y")
    assert main(["remove", "rm-skill", "--path", str(ws)]) == 0
    assert not (ws / ".claude" / "skills" / "rm-skill").exists()
    assert not (ws / ".windsurf" / "skills" / "rm-skill").exists()
    assert (src / "SKILL.md").is_file()


def test_remove_preview_lists_each_shared_destination_once(tmp_path, monkeypatch, capsys):
    ws, _src = _ws_with_skill(tmp_path, harness="codex,zed")
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(False))
    rc = main(["remove", "rm-skill", "--path", str(ws)])
    out = capsys.readouterr().out
    assert rc == 2
    rows = [ln for ln in out.splitlines() if ln.startswith("would-remove")]
    assert len(rows) == 1
    assert ".agents/skills/rm-skill" in rows[0].replace("\\", "/")  # Windows prints backslashes


def test_remove_with_explicit_harness_never_prompts(tmp_path, monkeypatch, capsys):
    ws, _src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(False))
    assert main(["remove", "rm-skill", "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    assert not (ws / ".claude" / "skills" / "rm-skill").exists()
    assert (ws / ".windsurf" / "skills" / "rm-skill" / "SKILL.md").is_file()


def test_remove_dry_run_never_prompts_and_never_deletes(tmp_path, monkeypatch, capsys):
    ws, _src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", _FakeStdin(False))
    assert main(["remove", "rm-skill", "--dry-run", "--path", str(ws)]) == 0
    assert (ws / ".claude" / "skills" / "rm-skill" / "SKILL.md").is_file()


@pytest.mark.parametrize(
    ("layout", "other", "survivor_base", "removed_base"),
    [
        ("shared", "codex", ".agents/skills", None),
        ("isolated", "codex", ".agents/skills", ".cursor/skills"),
        ("custom", "codex", ".agents/skills", "custom/skills"),
        ("custom-shared", "claude-code", "custom/skills", None),
    ],
)
def test_remove_preview_matches_action_and_next_sync(tmp_path, capsys, layout, other, survivor_base, removed_base):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _skill(tmp_path / "upstream", "rm-skill")
    unrelated = _skill(tmp_path / "upstream", "unrelated", body="Unrelated marker.\n")
    args = ["--path", str(ws), "--json"]
    assert main(["init", str(ws)]) == 0
    manifest = load_manifest(ws)
    if layout.startswith("custom"):
        manifest.harness_paths["cursor"] = "custom/skills"
    if layout == "custom-shared":
        manifest.harness_paths[other] = "custom/skills"
    save_manifest(ws, manifest)
    assert main(["add", str(src), "--harness", other, *args]) == 0
    flags = ["--isolated"] if layout == "isolated" else []
    assert main(["add", str(src), "--harness", "cursor", "--force", *flags, *args]) == 0
    assert main(["add", str(unrelated), "--harness", other, *args]) == 0
    manifest = load_manifest(ws)
    manifest.harnesses = [other, "cursor"]
    # Exercise inherited targets too; sync must not restore a removed owner from the defaults.
    manifest.skills[0].harnesses = [] if layout == "shared" else [other, "cursor"]
    save_manifest(ws, manifest)
    assert main(["lock", str(ws), "--json"]) == 0
    capsys.readouterr()

    survivor = ws / survivor_base / "rm-skill"
    removed = ws / removed_base / "rm-skill" if removed_base else None
    marker = ws / survivor_base / "unrelated" / "SKILL.md"
    marker_before = (marker.read_bytes(), marker.stat().st_mtime_ns)
    survivor_before = (survivor / "SKILL.md").read_bytes()
    metadata = [ws / path for path in (".skillporter/state.json", "skillporter.yaml", "skillporter.lock")]
    before = [path.read_bytes() for path in metadata]
    cmd = ["remove", "rm-skill", "--harness", "cursor", *args]
    assert main([*cmd, "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)["results"]
    assert [path.read_bytes() for path in metadata] == before
    assert removed is None or removed.is_dir()
    assert (survivor / "SKILL.md").read_bytes() == survivor_before
    assert main(cmd) == 0
    actual = json.loads(capsys.readouterr().out)["results"]
    expected = {str(survivor): "preserved-shared"}
    if removed:
        expected[str(removed)] = "removed"
    assert {row["dest"]: row["action"] for row in actual if row["action"] != "skipped"} == expected
    labels = {"removed": "would-remove", "skipped": "not-installed"}
    assert preview == [dict(row, action=labels.get(row["action"], row["action"])) for row in actual]

    for sync in (False, True):
        if sync:
            assert main(["sync", str(ws), "--json"]) == 0
            capsys.readouterr()
        rec = load_state(ws)["rm-skill"]
        assert rec.harnesses == [other]
        assert rec.destinations == [str(survivor.resolve())]
        assert load_manifest(ws).skills[0].harnesses == [other]
        pin = load_lockfile(ws).skills["rm-skill"]
        assert pin.installed_targets == [other]
        assert pin.tree_hash == rec.tree_hash
        assert removed is None or not removed.exists()
        assert (survivor / "SKILL.md").read_bytes() == survivor_before
        assert (src / "SKILL.md").read_bytes() == survivor_before
        assert (marker.read_bytes(), marker.stat().st_mtime_ns) == marker_before

    assert main(["uninstall", "rm-skill", "-y", *args]) == 0
    assert not survivor.exists()
    assert main(["sync", str(ws), "--json"]) == 0
    assert "rm-skill" not in load_state(ws)
    assert "rm-skill" not in load_lockfile(ws).skills
    assert [s.name for s in load_manifest(ws).skills] == ["unrelated"]
    assert not survivor.exists()
    assert (marker.read_bytes(), marker.stat().st_mtime_ns) == marker_before


# ---------------------------------------------------------------- D4


def test_remove_ignores_custom_override_that_was_not_used_for_install(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _skill(tmp_path / "upstream", "rm-skill")
    unrelated = _skill(tmp_path / "upstream", "unrelated")
    args = ["--path", str(ws), "--json"]
    assert main(["init", str(ws)]) == 0
    assert main(["add", str(src), "--harness", "cursor", *args]) == 0
    # Override added later: nothing of rm-skill lives there, and its unrelated sibling must never be touched.
    manifest = load_manifest(ws)
    manifest.harness_paths["cursor"] = "custom/skills"
    save_manifest(ws, manifest)
    assert main(["add", str(unrelated), "--harness", "codex", *args]) == 0
    custom_sibling = ws / "custom" / "skills" / "unrelated"
    shutil.copytree(unrelated, custom_sibling)
    capsys.readouterr()

    cmd = ["remove", "rm-skill", "--harness", "cursor", *args]
    assert main([*cmd, "--dry-run"]) == 0
    preview = json.loads(capsys.readouterr().out)["results"]
    assert main(cmd) == 0
    actual = json.loads(capsys.readouterr().out)["results"]
    installed = ws / ".agents" / "skills" / "rm-skill"
    assert [(row["dest"], row["action"]) for row in actual] == [(str(installed), "removed")]
    assert [dict(row, action="would-remove") for row in actual] == preview
    assert not installed.exists()
    assert (custom_sibling / "SKILL.md").is_file()
    assert not (ws / "custom" / "skills" / "rm-skill").exists()




def _ws_with_manifest_and_lock(tmp_path: Path, harness: str = "claude-code,windsurf") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    assert main(["init", str(ws)]) == 0
    src = _skill(tmp_path / "upstream", "mf-skill")
    assert main(["add", str(src), "--harness", harness, "--path", str(ws), "--json"]) == 0
    assert main(["lock", str(ws)]) == 0
    assert [s.name for s in load_manifest(ws).skills] == ["mf-skill"]
    assert "mf-skill" in load_lockfile(ws).skills
    return ws


def test_full_remove_drops_skill_from_manifest_and_lock(tmp_path, capsys):
    ws = _ws_with_manifest_and_lock(tmp_path)
    capsys.readouterr()
    assert main(["remove", "mf-skill", "-y", "--path", str(ws), "--json"]) == 0
    assert load_manifest(ws).skills == []
    assert "mf-skill" not in load_lockfile(ws).skills
    capsys.readouterr()
    assert main(["status", str(ws), "--json"]) == 0


def test_remove_keep_manifest_flag_retains_entries(tmp_path, capsys):
    ws = _ws_with_manifest_and_lock(tmp_path)
    capsys.readouterr()
    assert main(["remove", "mf-skill", "-y", "--keep-manifest", "--path", str(ws), "--json"]) == 0
    assert [s.name for s in load_manifest(ws).skills] == ["mf-skill"]
    assert "mf-skill" in load_lockfile(ws).skills


def test_partial_remove_does_not_drop_manifest_entry_but_trims_harnesses(tmp_path, capsys):
    ws = _ws_with_manifest_and_lock(tmp_path)
    capsys.readouterr()
    assert main(["remove", "mf-skill", "--harness", "windsurf", "--path", str(ws), "--json"]) == 0
    specs = load_manifest(ws).skills
    assert [s.name for s in specs] == ["mf-skill"]
    assert "windsurf" not in specs[0].harnesses
    assert "claude-code" in specs[0].harnesses
    assert "mf-skill" in load_lockfile(ws).skills
    assert (ws / ".claude" / "skills" / "mf-skill" / "SKILL.md").is_file()


def test_remove_without_manifest_still_works(tmp_path, capsys):
    ws, _src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    assert main(["remove", "rm-skill", "-y", "--path", str(ws), "--json"]) == 0
    assert not (ws / "skillporter.yaml").exists()


# ---------------------------------------------------------------- B19


def test_purge_source_deletes_in_workspace_source(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _skill(ws / "my-skills", "purge-me")
    assert main(["add", str(src), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert main(["remove", "purge-me", "-y", "--purge-source", "--path", str(ws), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("purged_source") == str(src.resolve())
    assert not src.exists()


def test_purge_source_keeps_out_of_workspace_source(tmp_path, capsys):
    ws, src = _ws_with_skill(tmp_path)
    capsys.readouterr()
    assert main(["remove", "rm-skill", "-y", "--purge-source", "--path", str(ws), "--json"]) == 0
    assert "purged_source" not in json.loads(capsys.readouterr().out)
    assert (src / "SKILL.md").is_file()


def test_purge_source_keeps_source_that_is_another_harness_destination(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    # The source dir doubles as claude-code's install location, so it must survive removal from codex.
    shared = _skill(ws / ".claude" / "skills", "shared-src")
    assert main(["add", str(shared), "--harness", "codex", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    rc = main(["remove", "shared-src", "--harness", "codex", "--purge-source", "--path", str(ws), "--json"])
    assert rc == 0
    assert "purged_source" not in json.loads(capsys.readouterr().out)
    assert (shared / "SKILL.md").is_file()
    assert not (ws / ".agents" / "skills" / "shared-src").exists()


# ---------------------------------------------------------------- D7


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _bare_repo(tmp_path: Path, name: str = "good") -> Path:
    work = tmp_path / f"{name}-work"
    _skill(work, "git-skill")
    _git("init", "-q", str(work))
    _git("-C", str(work), "add", "-A")
    _git("-C", str(work), "commit", "-q", "-m", "init")
    bare = tmp_path / f"{name}.git"
    _git("clone", "-q", "--bare", str(work), str(bare))
    return bare


def test_file_url_git_source_preserves_scheme_and_update_check_works(tmp_path, capsys):
    bare = _bare_repo(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    url = bare.resolve().as_uri()
    assert main(["add", url, "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    rec = load_state(ws)["git-skill"]
    assert rec.source.startswith("file://")
    assert main(["update", "--check", "--path", str(ws), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["updates_available"] == 0
    assert main(["outdated", "--path", str(ws), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["outdated_count"] == 0


def test_add_bare_repo_path_is_treated_as_git_source(tmp_path, capsys):
    bare = _bare_repo(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    assert main(["add", str(bare), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert (ws / ".claude" / "skills" / "git-skill" / "SKILL.md").is_file()
    assert main(["update", "--check", "--path", str(ws), "--json"]) == 0


def test_update_with_unresolvable_source_reports_error_not_traceback(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _skill(tmp_path / "up", "vanish")
    assert main(["add", str(src), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    shutil.rmtree(src)
    rc = main(["update", "--check", "--path", str(ws)])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.startswith("error:")
    assert "Traceback" not in err


# ---------------------------------------------------------------- B15


def test_add_dry_run_json_reports_policy_violations_and_exits_1(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "skillporter.policy.yaml").write_text("allowed_harnesses:\n  - codex\n", encoding="utf-8")
    src = _skill(tmp_path / "up", "pol-skill")
    rc = main(["add", str(src), "--harness", "claude-code", "--path", str(ws), "--dry-run", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["policy_violations"]
    assert not (ws / ".claude" / "skills" / "pol-skill").exists()


def test_add_dry_run_json_clean_policy_has_empty_violations(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _skill(tmp_path / "up", "ok-skill")
    rc = main(["add", str(src), "--harness", "claude-code", "--path", str(ws), "--dry-run", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["policy_violations"] == []


# ---------------------------------------------------------------- D13


def _two_skill_ws(tmp_path: Path) -> tuple[Path, Path, Path]:
    ws = tmp_path / "ws"
    ws.mkdir()
    up = tmp_path / "up"
    a = _skill(up, "skill-a")
    b = _skill(up, "skill-b")
    assert main(["add", str(a), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    assert main(["add", str(b), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    return ws, a, b


def test_update_dry_run_counts_only_outdated_skills(tmp_path, capsys):
    ws, a, _b = _two_skill_ws(tmp_path)
    (a / "SKILL.md").write_text((a / "SKILL.md").read_text() + "\nNew upstream line.\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["update", "--dry-run", "--path", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "1 skill(s) ready to update" in out
    assert main(["update", "--dry-run", "--path", str(ws), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)["updated"]
    assert {i["skill"]: i["action"] for i in items} == {"skill-a": "would-update", "skill-b": "unchanged"}


def test_update_reports_unchanged_for_up_to_date_skill(tmp_path, capsys):
    ws, a, _b = _two_skill_ws(tmp_path)
    (a / "SKILL.md").write_text((a / "SKILL.md").read_text() + "\nNew upstream line.\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["update", "--path", str(ws)]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert any(ln.startswith("updated") and "skill-a" in ln for ln in lines)
    assert any(ln.startswith("unchanged") and "skill-b" in ln for ln in lines)
    assert not any(ln.startswith("updated") and "skill-b" in ln for ln in lines)
    assert "New upstream line" in (ws / ".claude" / "skills" / "skill-a" / "SKILL.md").read_text()
