"""Crash-safe file writes.

A plain ``Path.write_text`` truncates the destination and then streams the new
content. If the process dies (OOM, Ctrl-C, power loss) between those two steps,
the user is left with a truncated or empty file — for skillporter that means a
corrupted state file, manifest or lockfile, which is precisely the
"failed operations must not leave the environment inconsistent" case.

``atomic_write_text`` writes to a sibling temp file in the *same directory*
(same filesystem, so ``os.replace`` is atomic) and renames it into place.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically.

    The destination is either the previous content or the complete new content —
    never a partial write. File permissions of an existing destination are
    preserved so we do not silently widen them.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_mode: int | None = None
    try:
        if path.exists():
            existing_mode = path.stat().st_mode & 0o777
    except OSError:
        existing_mode = None

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        if existing_mode is not None:
            with contextlib.suppress(OSError):
                os.chmod(tmp, existing_mode)
        os.replace(tmp, path)
    except BaseException:
        # Never leave a temp file behind, even on KeyboardInterrupt.
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
