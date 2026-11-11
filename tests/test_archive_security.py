"""Security regression tests for archive extraction (Zip Slip / Tar Slip).

Every case here is a real attack archive, not a synthetic mock. The Windows
backslash case was a genuine bypass: ``Path("..\\\\..\\\\x").parts`` on POSIX does
not split on backslash, so the traversal arrived as one opaque component and
passed a naive ``".." in parts`` guard — while the same archive is traversal on
Windows.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from skillporter.sources import SourceError, safe_extract_tar, safe_extract_zip


def _zip(tmp_path: Path, name: str, entries: list[tuple[str, bytes]], *, symlink: bool = False) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for entry_name, data in entries:
            if symlink:
                info = zipfile.ZipInfo(entry_name)
                info.external_attr = 0o120777 << 16
                zf.writestr(info, data)
            else:
                zf.writestr(entry_name, data)
    return path


def _tar(tmp_path: Path, name: str, members: list[tuple[str, bytes, bytes]]) -> Path:
    """members: (name, typeflag, payload) — typeflag b"0" file, b"2" symlink."""
    path = tmp_path / name
    with tarfile.open(path, "w") as tf:
        for member_name, typeflag, payload in members:
            info = tarfile.TarInfo(member_name)
            info.type = typeflag
            if typeflag == tarfile.SYMTYPE:
                info.linkname = payload.decode()
                tf.addfile(info)
            else:
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
    return path


# ---------------------------------------------------------------- zip slip
def test_zip_rejects_dotdot_traversal(tmp_path):
    archive = _zip(tmp_path, "t.zip", [("../../pwned.txt", b"x")])
    with pytest.raises(SourceError, match="traversal"):
        safe_extract_zip(archive, tmp_path / "out")
    assert not (tmp_path.parent / "pwned.txt").exists()


def test_zip_rejects_absolute_path(tmp_path):
    archive = _zip(tmp_path, "a.zip", [("/tmp/pwned_abs.txt", b"x")])
    with pytest.raises(SourceError, match="absolute"):
        safe_extract_zip(archive, tmp_path / "out")


def test_zip_rejects_windows_backslash_traversal(tmp_path):
    """Regression: ..\\\\..\\\\x was accepted because POSIX Path() does not split on backslash."""
    archive = _zip(tmp_path, "b.zip", [("..\\..\\pwned_bs.txt", b"x")])
    with pytest.raises(SourceError, match="traversal"):
        safe_extract_zip(archive, tmp_path / "out")


def test_zip_rejects_drive_qualified_path(tmp_path):
    archive = _zip(tmp_path, "c.zip", [("C:\\Windows\\pwned.txt", b"x")])
    with pytest.raises(SourceError, match="drive-qualified"):
        safe_extract_zip(archive, tmp_path / "out")


def test_zip_rejects_nul_byte_name(tmp_path):
    """zipfile truncates at NUL on write, so construct the check directly.

    The guard still rejects NUL bytes (an attacker-controlled archive may carry
    them when produced by another tool), we just cannot round-trip one through
    zipfile to prove it.
    """
    from skillporter.sources import _unsafe_member_name

    # Traversal is reported first (it is the more severe finding); a name that
    # is only NUL-tainted without traversal is still rejected.
    assert _unsafe_member_name("safe\x00name") == "NUL byte in name"
    assert _unsafe_member_name("safe\x00/../../x") == "path traversal"
    assert _unsafe_member_name("normal/skill.md") == ""


def test_zip_rejects_symlink_entry(tmp_path):
    archive = _zip(tmp_path, "s.zip", [("link", b"/etc/passwd")], symlink=True)
    with pytest.raises(SourceError, match="symlink"):
        safe_extract_zip(archive, tmp_path / "out")


# ---------------------------------------------------------------- tar slip
def test_tar_rejects_dotdot_traversal(tmp_path):
    archive = _tar(tmp_path, "t.tar", [("../../pwned_tar.txt", tarfile.REGTYPE, b"x")])
    with pytest.raises(SourceError, match="traversal"):
        safe_extract_tar(archive, tmp_path / "out")


def test_tar_rejects_windows_backslash_traversal(tmp_path):
    archive = _tar(tmp_path, "tb.tar", [("..\\..\\pwned_tb.txt", tarfile.REGTYPE, b"x")])
    with pytest.raises(SourceError, match="traversal"):
        safe_extract_tar(archive, tmp_path / "out")


def test_tar_rejects_symlink_member(tmp_path):
    archive = _tar(tmp_path, "ts.tar", [("evil", tarfile.SYMTYPE, b"/etc/passwd")])
    with pytest.raises(SourceError, match="symlink"):
        safe_extract_tar(archive, tmp_path / "out")


def test_tar_rejects_hardlink_member(tmp_path):
    archive = _tar(tmp_path, "th.tar", [("hard", tarfile.LNKTYPE, b"target")])
    with pytest.raises(SourceError):
        safe_extract_tar(archive, tmp_path / "out")


# ---------------------------------------------------------------- happy path
def test_zip_extracts_legitimate_skill(tmp_path):
    archive = _zip(tmp_path, "ok.zip", [
        ("my-skill/SKILL.md", b"---\nname: my-skill\ndescription: d. Use when x.\n---\nbody\n"),
        ("my-skill/scripts/run.sh", b"#!/bin/sh\n"),
    ])
    out = safe_extract_zip(archive, tmp_path / "out")
    assert (out / "my-skill" / "SKILL.md").is_file()
    assert (out / "my-skill" / "scripts" / "run.sh").is_file()


def test_zip_allows_safe_dot_segments(tmp_path):
    """`./a/b` is legitimate and must not be rejected as traversal."""
    archive = _zip(tmp_path, "dots.zip", [("./my-skill/SKILL.md", b"x")])
    out = safe_extract_zip(archive, tmp_path / "out")
    assert (out / "my-skill" / "SKILL.md").is_file()


def test_tar_extracts_legitimate_skill(tmp_path):
    archive = _tar(tmp_path, "ok.tar", [
        ("my-skill/SKILL.md", tarfile.REGTYPE, b"---\nname: my-skill\n---\n"),
    ])
    out = safe_extract_tar(archive, tmp_path / "out")
    assert (out / "my-skill" / "SKILL.md").is_file()
