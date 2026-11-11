"""Crash-safety tests for atomic writes.

A non-atomic write truncates the destination before streaming the new content,
so a crash mid-write corrupts the user's state file / manifest / lockfile.
These tests prove the destination is never observable in a partial state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from skillporter.atomic import atomic_write_text


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "out.json"
    atomic_write_text(target, '{"a": 1}\n')
    assert json.loads(target.read_text()) == {"a": 1}


def test_atomic_write_replaces_existing_content(tmp_path):
    target = tmp_path / "out.json"
    target.write_text("OLD")
    atomic_write_text(target, "NEW")
    assert target.read_text() == "NEW"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "out.json"
    atomic_write_text(target, "x")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftovers == []


def test_atomic_write_preserves_original_on_failure(tmp_path, monkeypatch):
    """If the write blows up mid-way, the old content must survive intact."""
    target = tmp_path / "out.json"
    target.write_text('{"original": true}')

    real_fdopen = os.fdopen

    def exploding_fdopen(fd, *a, **kw):
        fh = real_fdopen(fd, *a, **kw)

        class Boom:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                fh.close()
                return False

            def write(self, data):
                fh.write(data[:2])  # partially write, then fail
                raise OSError("disk full")

            def flush(self):
                pass

            def fileno(self):
                return fh.fileno()

        return Boom()

    monkeypatch.setattr(os, "fdopen", exploding_fdopen)

    with pytest.raises(OSError):
        atomic_write_text(target, '{"new": true}')

    assert json.loads(target.read_text()) == {"original": True}


def test_atomic_write_cleans_temp_file_on_exception(tmp_path, monkeypatch):
    target = tmp_path / "out.json"

    def boom(*a, **kw):
        raise OSError("nope")

    monkeypatch.setattr("skillporter.atomic.os.replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "x")

    # destination untouched and no temp residue
    assert not target.exists()
    assert [p.name for p in tmp_path.iterdir()] == []


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows has no POSIX permission bits; chmod only toggles the read-only flag",
)
def test_atomic_write_preserves_mode(tmp_path):
    target = tmp_path / "run.sh"
    target.write_text("#!/bin/sh\n")
    os.chmod(target, 0o750)
    atomic_write_text(target, "#!/bin/sh\necho hi\n")
    assert (target.stat().st_mode & 0o777) == 0o750


def test_atomic_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "out.json"
    atomic_write_text(target, "{}\n")
    assert target.is_file()


def test_state_file_write_is_atomic(tmp_path, monkeypatch):
    """save_state must go through the atomic path, not write_text."""
    from skillporter import state

    calls = []
    real = state.atomic_write_text

    def spy(path, content, **kw):
        calls.append(Path(path))
        return real(path, content, **kw)

    monkeypatch.setattr(state, "atomic_write_text", spy)

    sf = state.state_file(tmp_path, scope="project")
    sf.parent.mkdir(parents=True, exist_ok=True)
    state.save_state(tmp_path, {}, scope="project")
    assert calls, "save_state did not use atomic_write_text"
    assert sf.is_file()


def test_manifest_and_lockfile_writes_are_atomic(tmp_path, monkeypatch):
    from skillporter import manifest

    calls = []
    real = manifest.atomic_write_text

    def spy(path, content, **kw):
        calls.append(Path(path))
        return real(path, content, **kw)

    monkeypatch.setattr(manifest, "atomic_write_text", spy)

    manifest.save_manifest(tmp_path, manifest.ProjectManifest())
    manifest.save_lockfile(tmp_path, manifest.Lockfile())
    assert len(calls) == 2, calls
