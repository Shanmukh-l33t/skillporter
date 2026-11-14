"""Lockfile Integrity & Reproducible Installation Tests (P1 Section 8).

Verifies all 8 mandatory reproducibility & fail-safe invariants:
  1. Two installations from the same lockfile produce equivalent content
  2. Changed upstream source is detected and blocked during sync / lock --check
  3. Changed installed content (including child files) is detected via tree_hash & file_hashes
  4. Moved git branches do NOT silently change pinned lockfile installations
  5. Missing dependencies are reported clearly
  6. Corrupted lockfiles fail safely with LockfileError (exit code != 0)
  7. Unsupported schema versions fail clearly with LockfileError
  8. Concurrent multi-process synchronization serializes cleanly without corruption
  9. Lockfile distinguishes pinned commits/content from mutable unpinned references
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skillporter.cli import main
from skillporter.manifest import LockfileError, load_lockfile
from skillporter.security import compute_tree_hash

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_skill(base: Path, name: str, *, version: str = "1.0.0", extra: str = "", deps: str = "") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    fm = (
        f"---\n"
        f"name: {name}\n"
        f"description: >\n"
        f"  Reproducible test skill {name} for lockfile verification.\n"
        f"  Use when testing {name}.\n"
        f"license: MIT\n"
        f"metadata:\n"
        f'  version: "{version}"\n'
    )
    if deps:
        fm += f"dependencies:\n  - {deps}\n"
    fm += f"---\n\n# {name}\n\n{extra}\n"
    (sdir / "SKILL.md").write_text(fm, encoding="utf-8")
    (sdir / "scripts").mkdir(exist_ok=True)
    (sdir / "scripts" / "helper.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
    return sdir


def _init_git_repo(repo_dir: Path) -> str:
    subprocess.run(["git", "init", "-b", "main", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "ci@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "CI"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "v1"], check=True, capture_output=True)
    rev = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return rev.stdout.strip()


# ---------------------------------------------------------------------------
# 1 & 4. Equivalent Reproduction & Moved Branches Do Not Change Pinned Installs
# ---------------------------------------------------------------------------


def test_two_installs_from_same_lockfile_reproduce_exact_commit_even_after_branch_moves(tmp_path, capsys):
    git_repo = tmp_path / "upstream-git"
    _write_skill(git_repo / "skills", "pinned-skill", version="1.0.0", extra="V1 pinned content.")
    commit_v1 = _init_git_repo(git_repo)

    # Workspace A: manifest tracks branch `main`, syncs, and locks commit_v1
    ws_a = tmp_path / "ws-a"
    ws_a.mkdir()
    manifest_text = (
        "schema_version: 2\n"
        "project: repro-team\n"
        "harnesses:\n"
        "  - claude-code\n"
        "  - codex\n"
        "skills:\n"
        "  - name: pinned-skill\n"
        f"    source: {git_repo.as_uri()}\n"
        "    ref: main\n"
    )
    (ws_a / "skillporter.yaml").write_text(manifest_text, encoding="utf-8")
    assert main(["sync", str(ws_a)]) == 0
    assert main(["lock", str(ws_a)]) == 0
    capsys.readouterr()

    lock_a = load_lockfile(ws_a)
    locked_node = lock_a.skills["pinned-skill"]
    assert locked_node.resolved_commit == commit_v1
    assert locked_node.pin_state == "PINNED_COMMIT"
    assert locked_node.adapter_version != ""
    assert "SKILL.md" in locked_node.file_hashes
    assert lock_a.reproducible is True

    # Advance `main` branch in upstream git repo to V2!
    _write_skill(git_repo / "skills", "pinned-skill", version="2.0.0", extra="V2 MUTATED BRANCH CONTENT!")
    subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "v2"], check=True, capture_output=True)
    commit_v2 = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert commit_v1 != commit_v2

    # Workspace B: receives ONLY `skillporter.yaml` (with `ref: main`) + `skillporter.lock` from Workspace A!
    ws_b = tmp_path / "ws-b"
    ws_b.mkdir()
    shutil.copy2(ws_a / "skillporter.yaml", ws_b / "skillporter.yaml")
    shutil.copy2(ws_a / "skillporter.lock", ws_b / "skillporter.lock")

    assert main(["sync", str(ws_b)]) == 0
    capsys.readouterr()

    hash_a, files_a = compute_tree_hash(ws_a / ".claude" / "skills" / "pinned-skill")
    hash_b, files_b = compute_tree_hash(ws_b / ".claude" / "skills" / "pinned-skill")
    assert hash_a == hash_b == locked_node.tree_hash
    assert files_a == files_b
    installed_text = (ws_b / ".claude" / "skills" / "pinned-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "V1 pinned content." in installed_text
    assert "V2 MUTATED BRANCH CONTENT!" not in installed_text


# ---------------------------------------------------------------------------
# 2 & 3. Changed Upstream Source & Changed Installed Content Detected
# ---------------------------------------------------------------------------


def test_changed_upstream_source_and_changed_installed_content_detected(tmp_path, capsys):
    upstream_local = tmp_path / "vendor"
    _write_skill(upstream_local, "vendor-skill", version="1.0.0", extra="Original vendor skill.")

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "skillporter.yaml").write_text(
        "schema_version: 2\n"
        "project: vendor-check\n"
        "harnesses:\n"
        "  - claude-code\n"
        "skills:\n"
        "  - name: vendor-skill\n"
        f"    source: {(upstream_local / 'vendor-skill').as_posix()}\n",
        encoding="utf-8",
    )
    assert main(["sync", str(ws)]) == 0
    assert main(["lock", str(ws)]) == 0
    capsys.readouterr()

    # 1. Mutate upstream local source -> fresh workspace sync with same lockfile MUST detect hash mismatch!
    (upstream_local / "vendor-skill" / "scripts" / "helper.py").write_text("VERSION = 'TAMPERED'\n", encoding="utf-8")
    ws_fresh = tmp_path / "ws-fresh"
    ws_fresh.mkdir()
    shutil.copy2(ws / "skillporter.yaml", ws_fresh / "skillporter.yaml")
    shutil.copy2(ws / "skillporter.lock", ws_fresh / "skillporter.lock")

    rc_tamper = main(["sync", str(ws_fresh)])
    assert rc_tamper == 1
    err_tamper = capsys.readouterr().err
    assert (
        "tree_hash" in err_tamper or "differs from skillporter.lock" in err_tamper or "integrity" in err_tamper.lower()
    )
    assert not (ws_fresh / ".claude" / "skills" / "vendor-skill").exists()

    # 2. Mutate installed child file in ws -> `lock --check` detects changed installed content
    (ws / ".claude" / "skills" / "vendor-skill" / "scripts" / "helper.py").write_text("EDITED = 1\n", encoding="utf-8")
    assert main(["lock", str(ws), "--check"]) == 1
    err_chk = capsys.readouterr().err
    assert "lockfile drift" in err_chk


# ---------------------------------------------------------------------------
# 5, 6, 7. Missing Dependencies, Corrupted Lockfiles & Unsupported Schema Versions
# ---------------------------------------------------------------------------


def test_missing_dependencies_corrupted_lockfile_and_unsupported_schema_fail_safely(tmp_path, capsys):
    # 5. Missing dependency reported clearly
    ws_dep = tmp_path / "ws-dep"
    _write_skill(ws_dep / ".claude" / "skills", "needs-dep", deps="missing-helper@^1.0.0")
    (ws_dep / "skillporter.yaml").write_text(
        "schema_version: 2\nproject: dep-miss\nharnesses: [claude-code]\nskills:\n"
        "  - name: needs-dep\n    source: ./.claude/skills/needs-dep\n",
        encoding="utf-8",
    )
    (ws_dep / "skillporter.lock").write_text(
        '{"schema_version": 2, "generated_at": "2026-01-01T00:00:00Z", "skills": {}}\n'
    )
    assert main(["lock", str(ws_dep), "--check"]) == 1
    err_dep = capsys.readouterr().err
    assert "missing-helper" in err_dep

    # 6. Corrupted lockfile JSON fails safely with LockfileError and non-zero exit code
    ws_corrupt = tmp_path / "ws-corrupt"
    ws_corrupt.mkdir()
    (ws_corrupt / "skillporter.lock").write_text("{corrupted json !!!", encoding="utf-8")
    with pytest.raises(LockfileError, match="corrupted|invalid"):
        load_lockfile(ws_corrupt)
    assert main(["lock", str(ws_corrupt), "--check"]) == 1
    capsys.readouterr()

    # 7. Unsupported future schema_version fails clearly with LockfileError
    ws_future = tmp_path / "ws-future"
    ws_future.mkdir()
    (ws_future / "skillporter.lock").write_text('{"schema_version": 99, "skills": {}}\n', encoding="utf-8")
    with pytest.raises(LockfileError, match="unsupported.*schema_version"):
        load_lockfile(ws_future)
    assert main(["lock", str(ws_future), "--check"]) == 1
    err_schema = capsys.readouterr().err
    assert "schema_version" in err_schema


# ---------------------------------------------------------------------------
# 8. Concurrent Synchronization Cannot Corrupt Installation
# ---------------------------------------------------------------------------


def test_concurrent_sync_processes_do_not_corrupt_lockfile_or_skills(tmp_path):
    ws = tmp_path / "ws-conc"
    _write_skill(ws / ".claude" / "skills", "sync-one", version="1.0.0")
    _write_skill(ws / ".claude" / "skills", "sync-two", version="1.0.0")
    (ws / "skillporter.yaml").write_text(
        "schema_version: 2\nproject: conc\nharnesses: [claude-code, codex, cursor]\nskills:\n"
        "  - name: sync-one\n    source: ./.claude/skills/sync-one\n"
        "  - name: sync-two\n    source: ./.claude/skills/sync-two\n",
        encoding="utf-8",
    )

    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "skillporter", "sync", str(ws)],
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    for p in procs:
        _, err = p.communicate(timeout=20)
        assert p.returncode == 0, err

    lock = load_lockfile(ws)
    assert set(lock.skills.keys()) == {"sync-one", "sync-two"}
    assert main(["lock", str(ws), "--check"]) == 0
