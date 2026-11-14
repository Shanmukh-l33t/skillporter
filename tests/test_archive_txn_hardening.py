"""Archive Extraction & Transaction Engine Hardening Tests (P1 Section 7).

Covers:
  1. Unicode NFC/NFD normalization collision rejection in ZIP & TAR
  2. Windows reserved device names (CON, NUL, COM1, LPT1), trailing dots/spaces, and NTFS ADS colons
  3. ZIP special file mode bits (FIFO, device, socket) rejection & TAR setuid bit stripping
  4. Malformed / truncated ZIP & TAR headers raising SourceError with zero partial files
  5. Symlink race / pre-existing symlink inside extraction destination blocked (O_EXCL / O_NOFOLLOW)
  6. Harness directory replaced by symlink pointing outside workspace rejected on install
  7. Multi-harness SIGKILL crash AFTER target 1 was swapped -> recovery restores target 1 (zero partial install)
  8. Disk full (ENOSPC) and PermissionError mid-install roll back cleanly
  9. Concurrent multi-process installations serialize safely via workspace_lock
"""

from __future__ import annotations

import errno
import io
import os
import signal
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from skillporter.install import InstallError, install, recover_interrupted_transactions
from skillporter.security import compute_tree_hash
from skillporter.sources import SourceError, safe_extract_tar, safe_extract_zip

REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_TEMPLATE = """---
name: {name}
description: >
  Skill {name} used for archive and transaction hardening tests.
  Use when testing {name}.
license: MIT
---

# {name}

Body content {ver}.
"""


def _make_skill(base: Path, name: str = "txn-skill", ver: str = "v1") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(SKILL_TEMPLATE.format(name=name, ver=ver), encoding="utf-8")
    return sdir


# ---------------------------------------------------------------------------
# 1. Unicode NFC/NFD Collisions & Windows Reserved Filenames
# ---------------------------------------------------------------------------


def test_zip_and_tar_reject_unicode_nfc_nfd_collisions(tmp_path):
    nfc = "my-skill/caf\u00e9.md"
    nfd = "my-skill/cafe\u0301.md"
    assert nfc != nfd

    zpath = tmp_path / "unicode.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(nfc, b"one")
        zf.writestr(nfd, b"two")

    with pytest.raises(SourceError, match="duplicate|colliding"):
        safe_extract_zip(zpath, tmp_path / "out_z")

    tpath = tmp_path / "unicode.tar"
    with tarfile.open(tpath, "w") as tf:
        for entry_name in (nfc, nfd):
            ti = tarfile.TarInfo(entry_name)
            ti.size = 3
            tf.addfile(ti, io.BytesIO(b"abc"))

    with pytest.raises(SourceError, match="duplicate|colliding"):
        safe_extract_tar(tpath, tmp_path / "out_t")


def test_zip_and_tar_reject_windows_reserved_names_ads_and_trailing_dots(tmp_path):
    bad_names = [
        "my-skill/CON",
        "my-skill/NUL.txt",
        "my-skill/COM1/SKILL.md",
        "my-skill/LPT9.md",
        "my-skill/trailing./SKILL.md",
        "my-skill/SKILL.md:Zone.Identifier",
        "my-skill/ctrl\x07name.md",
    ]
    for idx, bad in enumerate(bad_names):
        zpath = tmp_path / f"win_{idx}.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr(bad, b"x")
        with pytest.raises(SourceError):
            safe_extract_zip(zpath, tmp_path / f"zout_{idx}")

        tpath = tmp_path / f"win_{idx}.tar"
        with tarfile.open(tpath, "w") as tf:
            ti = tarfile.TarInfo(bad)
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        with pytest.raises(SourceError):
            safe_extract_tar(tpath, tmp_path / f"tout_{idx}")


# ---------------------------------------------------------------------------
# 2. Special ZIP Modes, TAR Setuid Stripping & Malformed Headers
# ---------------------------------------------------------------------------


def test_zip_rejects_fifo_and_device_external_attr_and_tar_strips_setuid(tmp_path):
    fifo_zip = tmp_path / "fifo.zip"
    with zipfile.ZipFile(fifo_zip, "w") as zf:
        zi = zipfile.ZipInfo("my-skill/named.pipe")
        zi.external_attr = (0o010644) << 16  # S_IFIFO
        zf.writestr(zi, b"")

    with pytest.raises(SourceError, match="special|unsafe"):
        safe_extract_zip(fifo_zip, tmp_path / "fifo_out")

    if os.name != "nt":
        suid_tar = tmp_path / "suid.tar"
        with tarfile.open(suid_tar, "w") as tf:
            ti = tarfile.TarInfo("my-skill/SKILL.md")
            ti.mode = 0o4755  # setuid bit!
            ti.size = 4
            tf.addfile(ti, io.BytesIO(b"test"))
        out = safe_extract_tar(suid_tar, tmp_path / "suid_out")
        mode = (out / "my-skill" / "SKILL.md").stat().st_mode
        assert (mode & 0o4000) == 0, "setuid bit must never survive archive extraction"


def test_malformed_zip_and_tar_headers_raise_source_error_and_leave_no_partial_files(tmp_path):
    bad_zip = tmp_path / "truncated.zip"
    bad_zip.write_bytes(b"PK\x03\x04corrupted-header-bytes")
    out_z = tmp_path / "out_bad_zip"
    with pytest.raises(SourceError):
        safe_extract_zip(bad_zip, out_z)
    assert not out_z.exists() or list(out_z.iterdir()) == []

    bad_tar = tmp_path / "truncated.tar.gz"
    bad_tar.write_bytes(b"\x1f\x8b\x08\x00corrupted-gzip-stream")
    out_t = tmp_path / "out_bad_tar"
    with pytest.raises(SourceError):
        safe_extract_tar(bad_tar, out_t)
    assert not out_t.exists() or list(out_t.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink TOCTOU guard test")
def test_archive_extraction_blocks_preexisting_symlink_in_destination(tmp_path):
    outside_victim = tmp_path / "victim.txt"
    outside_victim.write_text("UNTOUCHED", encoding="utf-8")

    dest = tmp_path / "extract_dest"
    (dest / "my-skill").mkdir(parents=True)
    # Simulate a TOCTOU / pre-planted symlink at target path pointing to outside_victim
    (dest / "my-skill" / "SKILL.md").symlink_to(outside_victim)

    good_zip = tmp_path / "ok.zip"
    with zipfile.ZipFile(good_zip, "w") as zf:
        zf.writestr("my-skill/SKILL.md", b"OVERWRITTEN")

    with pytest.raises(SourceError):
        safe_extract_zip(good_zip, dest)
    assert outside_victim.read_text(encoding="utf-8") == "UNTOUCHED"


# ---------------------------------------------------------------------------
# 3. Transaction Engine: Symlinked Parent, Multi-Target SIGKILL, Disk Full & Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinked destination directory escape test")
def test_install_rejects_destination_parent_replaced_by_escaping_symlink(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".claude").mkdir(parents=True)
    outside = tmp_path / "outside-target"
    outside.mkdir()
    # Replace .claude/skills with a symlink escaping the workspace!
    (ws / ".claude" / "skills").symlink_to(outside)

    src = _make_skill(tmp_path / "src", "sym-parent-skill")
    with pytest.raises(InstallError, match="outside|symlink|escape"):
        install(ws, src, ["claude-code"], strategy="copy")
    assert not (outside / "sym-parent-skill").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX subprocess SIGKILL multi-target partial install test")
def test_sigkill_after_first_target_swap_rolls_back_partial_multi_harness_install(tmp_path):
    """If Target 1 (claude-code) completes its swap to v2 and SIGKILL hits before Target 2 (windsurf),
    recovery MUST roll Target 1 back to v1 and remove any newly created uncommitted targets!"""
    ws = tmp_path / "ws"
    v1_src = _make_skill(tmp_path / "v1", "multi-skill", ver="v1")
    install(ws, v1_src, ["claude-code"], strategy="copy", record_state=True)
    claude_dest = ws / ".claude" / "skills" / "multi-skill"
    v1_hash, _ = compute_tree_hash(claude_dest)

    v2_src = _make_skill(tmp_path / "v2", "multi-skill", ver="v2-uncommitted")

    # Child process completes claude-code swap to v2, then SIGKILLs itself when staging windsurf!
    child_script = f"""
import os, signal, shutil
from pathlib import Path
import skillporter.install as inst_mod

real_stage = inst_mod._stage_and_copy_skill
calls = [0]
def crash_on_second_target(src, dest, **kw):
    calls[0] += 1
    if calls[0] == 2:
        os.kill(os.getpid(), signal.SIGKILL)
    return real_stage(src, dest, **kw)

inst_mod._stage_and_copy_skill = crash_on_second_target
inst_mod.install(
    Path({str(ws)!r}), Path({str(v2_src)!r}),
    ["claude-code", "windsurf"], strategy="copy", force=True, record_state=True,
)
"""
    proc = subprocess.run(
        [sys.executable, "-c", child_script],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == -signal.SIGKILL

    # Before recovery, claude_dest had v2 moved into place while windsurf never finished!
    actions = recover_interrupted_transactions(ws)
    assert len(actions) >= 1
    assert claude_dest.is_dir()
    recovered_hash, _ = compute_tree_hash(claude_dest)
    assert recovered_hash == v1_hash, "Uncommitted partial v2 install on target 1 was not rolled back to v1!"
    assert not (ws / ".windsurf" / "skills" / "multi-skill").exists()


def test_disk_full_and_permission_denied_mid_install_rollback_cleanly(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    v1_src = _make_skill(tmp_path / "v1", "io-skill", ver="v1")
    install(ws, v1_src, ["claude-code"], strategy="copy", record_state=True)
    v1_hash, _ = compute_tree_hash(ws / ".claude" / "skills" / "io-skill")

    v2_src = _make_skill(tmp_path / "v2", "io-skill", ver="v2")
    import shutil as shutil_mod

    real_copytree = shutil_mod.copytree
    n = [0]

    def enospc_on_windsurf(src, dst, *a, **kw):
        # Allow backup snapshot + claude-code staging, fail on windsurf staging
        if "stage-" in str(dst):
            n[0] += 1
            if n[0] == 2:
                raise OSError(errno.ENOSPC, "No space left on device")
        return real_copytree(src, dst, *a, **kw)

    monkeypatch.setattr(shutil_mod, "copytree", enospc_on_windsurf)
    with pytest.raises(OSError, match="No space left on device"):
        install(ws, v2_src, ["claude-code", "windsurf"], strategy="copy", force=True, record_state=True)

    after_hash, _ = compute_tree_hash(ws / ".claude" / "skills" / "io-skill")
    assert after_hash == v1_hash
    assert not (ws / ".windsurf" / "skills" / "io-skill").exists()


def test_concurrent_multiprocess_installations_serialize_without_corruption(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    s1 = _make_skill(tmp_path / "src1", "concurrent-a", ver="1.0")
    s2 = _make_skill(tmp_path / "src2", "concurrent-b", ver="1.0")

    worker = """
import sys
from pathlib import Path
from skillporter.install import install
ws, src = Path(sys.argv[1]), Path(sys.argv[2])
install(ws, src, ["claude-code", "codex"], strategy="copy", force=True, record_state=True)
"""
    p1 = subprocess.Popen(
        [sys.executable, "-c", worker, str(ws), str(s1)],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p2 = subprocess.Popen(
        [sys.executable, "-c", worker, str(ws), str(s2)],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _, err1 = p1.communicate(timeout=15)
    _, err2 = p2.communicate(timeout=15)
    assert p1.returncode == 0, err1
    assert p2.returncode == 0, err2

    from skillporter.state import load_state

    records = load_state(ws)
    assert "concurrent-a" in records
    assert "concurrent-b" in records
    assert (ws / ".claude" / "skills" / "concurrent-a" / "SKILL.md").is_file()
    assert (ws / ".claude" / "skills" / "concurrent-b" / "SKILL.md").is_file()
