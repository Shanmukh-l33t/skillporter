"""Shared test isolation.

Harness detection looks at environment variables (HERMES_HOME, CLAUDE_CONFIG_DIR, ...), the user's home
directory (~/.claude, ~/.hermes, ...), and agent binaries on PATH (claude, opencode, hermes, ...).
A developer who uses those agents would otherwise see different results from CI, so every test starts with
those signals cleared while keeping system utilities (git, sh, python) available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skillporter import harnesses


def _detection_env_vars() -> set[str]:
    names: set[str] = {"HERMES_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"}
    for name in harnesses.names():
        names.update(harnesses.get(name).detection.env_vars)
    return names


def _agent_binary_names() -> set[str]:
    bins: set[str] = set()
    for name in harnesses.names():
        for b in harnesses.get(name).detection.binaries:
            bins.add(b)
            if os.name == "nt":
                bins.add(f"{b}.exe")
                bins.add(f"{b}.cmd")
    return bins


@pytest.fixture(autouse=True)
def _hermetic_agent_environment(tmp_path_factory, monkeypatch):
    for var in _detection_env_vars():
        monkeypatch.delenv(var, raising=False)
    empty_home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("USERPROFILE", str(empty_home))

    # Drop PATH directories that hold user-installed agent binaries, keeping the ones that also carry git/sh.
    agent_bins = _agent_binary_names()
    raw_dirs = os.environ.get("PATH", "").split(os.pathsep)
    kept_dirs: list[str] = []
    for d in raw_dirs:
        if not d:
            continue
        dp = Path(d)
        has_git_or_sh = (dp / "git").exists() or (dp / "git.exe").exists() or (dp / "sh").exists()
        has_agent = any((dp / ab).exists() for ab in agent_bins)
        if has_agent and not has_git_or_sh:
            continue
        kept_dirs.append(d)
    if kept_dirs:
        monkeypatch.setenv("PATH", os.pathsep.join(kept_dirs))
