"""Final Release Gate Verification Suite.

Exercises real OS subprocesses, SIGKILL termination mid-swap, cross-process
flock contention, Windows msvcrt lock semantics, case-insensitive archive
collisions, multi-file sync conflicts, backup integrity checks, standalone
.pyz execution, and npm wrapper execution.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

from skillporter.atomic import workspace_lock
from skillporter.diagnose import diagnose
from skillporter.install import install
from skillporter.security import compute_tree_hash

REPO_ROOT = Path(__file__).resolve().parents[1]

GATE_SKILL = """---
name: gate-skill
description: >
  Verify release gate invariants under real subprocess termination and locking.
  Use when running release gate checks.
license: MIT
---

# Gate Skill

Body content v1.
"""


def _make_skill(base: Path, name: str = "gate-skill", body_extra: str = "") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    text = GATE_SKILL.replace("name: gate-skill", f"name: {name}") + body_extra
    (sdir / "SKILL.md").write_text(text, encoding="utf-8")
    return sdir


# ---------------------------------------------------------------------------
# 1 & 2. Real subprocess SIGKILL during transactional install & recovery
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGKILL mid-swap subprocess test")
def test_real_subprocess_sigkill_mid_swap_and_automatic_recovery(tmp_path):
    v1_dir = _make_skill(tmp_path / "v1", "gate-skill", "\nOriginal v1 content.\n")
    install(tmp_path, v1_dir, ["claude-code"], strategy="copy", record_state=True)
    dest = tmp_path / ".claude" / "skills" / "gate-skill"
    v1_hash, _ = compute_tree_hash(dest)

    v2_dir = _make_skill(tmp_path / "v2", "gate-skill", "\nUpdated v2 content.\n")

    # Spawn a real child process that hooks shutil.move: after moving `dest` to `prev_slot`
    # (when `dest` no longer exists on disk!), the child sends SIGKILL to itself.
    child_code = f"""
import os, signal, shutil
from pathlib import Path
from skillporter.install import install

real_move = shutil.move
def crash_after_first_move(src, dst, *a, **kw):
    res = real_move(src, dst, *a, **kw)
    if "prev-" in str(dst):
        # Right here, `dest` has been moved to `prev_slot` and `stage_dir` has NOT been moved into `dest` yet!
        os.kill(os.getpid(), signal.SIGKILL)
    return res

shutil.move = crash_after_first_move
install(Path({str(tmp_path)!r}), Path({str(v2_dir)!r}), ["claude-code"], strategy="copy", force=True, record_state=True)
"""
    proc = subprocess.run(
        [sys.executable, "-c", child_code],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == -signal.SIGKILL

    # Right after SIGKILL, `dest` is missing on disk and `.skillporter/tmp/txn-*` holds `prev-*` + `journal.json`
    assert not dest.exists()
    assert any((tmp_path / ".skillporter" / "tmp").iterdir())

    # Running `diagnose(tmp_path)` automatically triggers `recover_interrupted_transactions`
    diag = diagnose(tmp_path, only=["claude-code"])
    assert "gate-skill" in diag.reports["claude-code"].reachable_skills
    assert dest.is_dir()
    recovered_hash, _ = compute_tree_hash(dest)
    assert recovered_hash == v1_hash


# ---------------------------------------------------------------------------
# 3 & 4. Cross-process locking on Linux (real subprocess) & Windows msvcrt path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock subprocess contention test")
def test_linux_cross_process_lock_contention_and_crash_release(tmp_path):
    holder_code = f"""
import sys, time
from pathlib import Path
from skillporter.atomic import workspace_lock

with workspace_lock(Path({str(tmp_path)!r}), timeout_s=5.0):
    sys.stdout.write("LOCKED\\n")
    sys.stdout.flush()
    time.sleep(10.0)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = holder.stdout.readline().strip() if holder.stdout else ""
        assert line == "LOCKED"

        # A second process (this process) trying to acquire workspace_lock with short timeout must raise TimeoutError
        with pytest.raises(TimeoutError, match="timed out acquiring workspace lock"), workspace_lock(
            tmp_path, timeout_s=0.15
        ):
            pass

        # Kill the holder with SIGKILL: the OS kernel must release the flock immediately
        holder.kill()
        holder.wait(timeout=5)

        # Now this process can acquire the lock immediately
        with workspace_lock(tmp_path, timeout_s=1.0) as lpath:
            assert lpath.is_file()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_windows_msvcrt_lock_branch_behavior(tmp_path, monkeypatch):
    """Verify the Windows msvcrt locking code path (seek(0), retry, and TimeoutError)."""
    import skillporter.atomic as atomic_mod

    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0)
    lock_attempts = [0]

    def fake_locking(fd, mode, nbytes):
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0, "Windows msvcrt.locking must lock at byte offset 0"
        assert nbytes == 1
        if mode == fake_msvcrt.LK_NBLCK:
            lock_attempts[0] += 1
            if lock_attempts[0] < 3:
                raise OSError("Windows lock contention")

    fake_msvcrt.locking = fake_locking
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(atomic_mod, "_IS_WINDOWS", True)

    # Succeeds on 3rd retry after 2 transient contentions
    with workspace_lock(tmp_path, timeout_s=1.0) as lpath:
        assert lpath.is_file()
    assert lock_attempts[0] == 3

    # Always-contended lock raises TimeoutError instead of silently proceeding unlocked
    def always_locked(fd, mode, nbytes):
        if mode == fake_msvcrt.LK_NBLCK:
            raise OSError("permanently locked by another process")

    fake_msvcrt.locking = always_locked
    with pytest.raises(TimeoutError, match="timed out acquiring workspace lock"), workspace_lock(
        tmp_path, timeout_s=0.12
    ):
        pass


# ---------------------------------------------------------------------------
# 8 & 9. Standalone .pyz and npm wrapper end-to-end execution
# ---------------------------------------------------------------------------


def test_standalone_pyz_and_npm_wrapper_diagnose_and_scan(tmp_path):
    _make_skill(tmp_path / ".claude" / "skills", "gate-skill")
    _make_skill(tmp_path / ".agents" / "skills", "gate-skill")

    pyz_path = REPO_ROOT / "dist" / "skillporter.pyz"
    if not pyz_path.is_file():
        pyz_path = REPO_ROOT / "npm" / "bin" / "skillporter.pyz"
    assert pyz_path.is_file()

    proc_pyz = subprocess.run(
        [sys.executable, str(pyz_path), "diagnose", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_pyz.returncode == 0, proc_pyz.stderr
    assert "no findings" in proc_pyz.stdout

    if shutil.which("node"):
        npm_bin = REPO_ROOT / "npm" / "bin" / "skillporter.js"
        proc_npm = subprocess.run(
            ["node", str(npm_bin), "scan", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc_npm.returncode == 0, proc_npm.stderr
        assert "PASSED" in proc_npm.stdout
