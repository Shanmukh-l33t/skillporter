"""Shared test isolation.

Harness detection looks at environment variables (HERMES_HOME, CLAUDE_CONFIG_DIR, ...) and at the user's home
directory (~/.claude, ~/.hermes, ...). A developer who uses those agents would otherwise see different results from
CI, so every test starts with those signals cleared. Tests that need one still set it with ``monkeypatch.setenv``.
"""

from __future__ import annotations

import pytest

from skillporter import harnesses


def _detection_env_vars() -> set[str]:
    names: set[str] = {"HERMES_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"}
    for name in harnesses.names():
        names.update(harnesses.get(name).detection.env_vars)
    return names


@pytest.fixture(autouse=True)
def _hermetic_agent_environment(tmp_path_factory, monkeypatch):
    for var in _detection_env_vars():
        monkeypatch.delenv(var, raising=False)
    empty_home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("USERPROFILE", str(empty_home))
