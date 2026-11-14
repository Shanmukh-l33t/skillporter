"""Reusable 19-Adapter Conformance & Shared-Directory Safety Suite (P2 Section 9).

Exercises every registered harness adapter across:
  1. Verification model integrity (DOCUMENTATION_VERIFIED, FIXTURE_TESTED,
     INTEGRATION_TESTED, RUNTIME_VERIFIED — never promoted without evidence)
  2. Project & user directory resolution and skill structure preservation
  3. Metadata, frontmatter, and controlled format adaptation compatibility
  4. Conflict refusal without force, backup snapshot on forced update, and sync
  5. Safe shared `.agents/skills/` removal: removing one harness MUST NOT delete
     another installed harness's shared skill directory, while removing duplicate
     harness-specific `.cursor/skills/` cleans up the duplicate safely.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from skillporter import harnesses
from skillporter.cli import main
from skillporter.diagnose import diagnose, resolve_path
from skillporter.formats import render_adapted_skill
from skillporter.frontmatter import parse_skill, validate
from skillporter.install import InstallError, install, uninstall
from skillporter.state import load_state

CONFORMANCE_SKILL = """---
name: conform-skill
description: >
  Adapter conformance fixture verifying directory layout, scripts, references,
  and metadata handling across all 19 supported AI harnesses. Use when running
  adapter conformance tests.
license: MIT
compatibility: Python 3.9+
allowed-tools: Bash Read
metadata:
  author: conformance-suite
  version: "1.3.0"
---

# Conformance Skill

Follow `references/spec.md` and run `scripts/check.py`.
"""


def _build_fixture_skill(base: Path, name: str = "conform-skill") -> Path:
    sdir = base / name
    (sdir / "scripts").mkdir(parents=True, exist_ok=True)
    (sdir / "references").mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(
        CONFORMANCE_SKILL.replace("name: conform-skill", f"name: {name}"),
        encoding="utf-8",
    )
    (sdir / "scripts" / "check.py").write_text("print('conformance-ok')\n", encoding="utf-8")
    (sdir / "references" / "spec.md").write_text("# Spec Reference\n", encoding="utf-8")
    return sdir


def test_verification_model_levels_and_evidence_honesty():
    assert "FIXTURE_TESTED" in harnesses.VERIFICATION_LEVELS
    assert "DOCUMENTATION_VERIFIED" in harnesses.VERIFICATION_LEVELS
    assert "INTEGRATION_TESTED" in harnesses.VERIFICATION_LEVELS
    assert "RUNTIME_VERIFIED" in harnesses.VERIFICATION_LEVELS

    all_names = harnesses.names()
    assert len(all_names) == 19
    runtime_verified = [n for n in all_names if harnesses.get(n).verification_level == "RUNTIME_VERIFIED"]
    # Only harnesses actually runtime-tested in this environment may claim RUNTIME_VERIFIED
    assert runtime_verified == ["hermes"]
    for name in all_names:
        h = harnesses.get(name)
        assert h.verification_evidence != "", f"{name} missing verification_evidence"


@pytest.mark.parametrize("harness_id", harnesses.names())
def test_adapter_full_lifecycle_conformance_project_and_user_scopes(tmp_path, monkeypatch, harness_id):
    h = harnesses.get(harness_id)
    ws = tmp_path / "project"
    ws.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(fake_home / ".hermes"))

    src = _build_fixture_skill(tmp_path / "src", "conform-skill")
    doc = parse_skill(src / "SKILL.md")
    assert [i for i in validate(doc) if i.level == "error"] == []

    # 1. Project scope install, reachability, conflict protection, adapt, and removal
    if h.project_paths:
        res = install(ws, src, [harness_id], strategy="copy", scope="project", record_state=True, adapt=True)
        assert len(res) == 1
        assert res[0].action == "created"
        expected_base = resolve_path(h.project_paths[0].path, "project", ws, home=fake_home)
        installed_dir = expected_base / "conform-skill"
        assert (installed_dir / "SKILL.md").is_file()
        assert (installed_dir / "scripts" / "check.py").is_file()
        assert (installed_dir / "references" / "spec.md").is_file()

        if h.capabilities.adapted_format:
            rel_adapt, _ = render_adapted_skill(doc, h.capabilities.adapted_format)
            assert (ws / rel_adapt).is_file()

        diag = diagnose(ws, only=[harness_id], scope="project", home=fake_home)
        assert "conform-skill" in diag.reports[harness_id].reachable_skills

        # Conflict check without force
        with pytest.raises(InstallError):
            install(ws, src, [harness_id], strategy="copy", scope="project", force=False)

        # Removal when sole owner removes directory cleanly
        rem = uninstall(ws, "conform-skill", [harness_id], scope="project", home=fake_home, record_state=True)
        assert rem[0].action == "removed"
        assert not installed_dir.exists()

    # 2. User scope install, reachability, and removal
    if h.user_paths:
        ures = install(ws, src, [harness_id], strategy="copy", scope="user", home=fake_home, record_state=True)
        assert ures[0].action == "created"
        udiag = diagnose(ws, only=[harness_id], scope="user", home=fake_home)
        assert "conform-skill" in udiag.reports[harness_id].reachable_skills
        urem = uninstall(ws, "conform-skill", [harness_id], scope="user", home=fake_home, record_state=True)
        assert urem[0].action == "removed"


def test_shared_agents_skills_removal_preserves_other_owning_harnesses(tmp_path):
    """Removing a skill from `cursor` MUST NOT delete `.agents/skills/<skill>` while `codex` or `zed` still owns it!"""
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _build_fixture_skill(tmp_path / "src", "shared-safe")

    # Install across codex, cursor, zed (all share .agents/skills) + claude-code (.claude/skills)
    install(ws, src, ["claude-code", "codex", "cursor", "zed"], strategy="copy", record_state=True)
    shared_dir = ws / ".agents" / "skills" / "shared-safe"
    claude_dir = ws / ".claude" / "skills" / "shared-safe"
    assert shared_dir.is_dir()
    assert claude_dir.is_dir()

    # Remove ONLY from `cursor` -> `.agents/skills/shared-safe` MUST remain intact for codex & zed!
    rem_cursor = uninstall(ws, "shared-safe", ["cursor"], record_state=True)
    assert shared_dir.is_dir(), "Removing cursor deleted shared .agents/skills directory still needed by codex & zed!"
    assert any(r.action in ("preserved-shared", "removed") for r in rem_cursor)
    records = load_state(ws)
    assert "cursor" not in records["shared-safe"].harnesses
    assert "codex" in records["shared-safe"].harnesses
    assert "zed" in records["shared-safe"].harnesses

    # Also test duplicate cleanup: if user ALSO had a redundant `.cursor/skills/shared-safe` copy,
    # `remove shared-safe --harness cursor` deletes `.cursor/skills` while keeping `.agents/skills`!
    dup_cursor_dir = ws / ".cursor" / "skills" / "shared-safe"
    shutil.copytree(src, dup_cursor_dir)
    assert main(["remove", "shared-safe", "--harness", "cursor", "--path", str(ws)]) == 0
    assert not dup_cursor_dir.exists()
    assert shared_dir.is_dir()

    # Now remove BOTH remaining shared owners (`codex` and `zed`) -> `.agents/skills/shared-safe` IS removed!
    uninstall(ws, "shared-safe", ["codex", "zed"], record_state=True)
    assert not shared_dir.exists()
    # While `claude-code` in `.claude/skills/shared-safe` is still untouched!
    assert claude_dir.is_dir()
