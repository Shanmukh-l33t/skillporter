"""Regression tests for issues found by using the tool on a real layout."""

from __future__ import annotations

from pathlib import Path

from skillporter.diagnose import diagnose
from skillporter.install import install

SKILL = """---
name: my-helper
description: Summarize long documents into bullet points. Use when the user asks for a summary or a TLDR.
---

# My helper
"""


def _author_for_claude(root: Path) -> Path:
    d = root / ".claude" / "skills" / "my-helper"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL, encoding="utf-8")
    return d


def test_install_then_diagnose_does_not_duplicate_skill_rows(tmp_path):
    """Installing for a second harness must not double-report the same skill."""
    src = _author_for_claude(tmp_path)
    install(tmp_path, src, ["codex"], strategy="copy")

    diag = diagnose(tmp_path)
    assert diag.skill_names == ["my-helper"], diag.skill_names


def test_diagnose_findings_are_not_duplicated(tmp_path):
    src = _author_for_claude(tmp_path)
    install(tmp_path, src, ["codex"], strategy="copy")

    diag = diagnose(tmp_path)
    assert len(diag.findings) == len(set(diag.findings))


def test_full_bridge_install_satisfies_all_verified_project_harnesses(tmp_path):
    """install for every project-scoped verified harness -> no findings for it."""
    author = tmp_path / "authoring" / "my-helper"
    author.mkdir(parents=True)
    (author / "SKILL.md").write_text(SKILL, encoding="utf-8")

    install(tmp_path, author, ["claude-code", "codex", "cursor"], strategy="copy")

    diag = diagnose(tmp_path, only=["claude-code", "codex", "cursor"])
    assert diag.findings == [], diag.findings


def test_project_scope_ignores_user_home(tmp_path):
    """Diagnosing a repo must not pick up the operator's own installed skills."""
    home = tmp_path / "fakehome"
    (home / ".claude" / "skills" / "foreign-skill").mkdir(parents=True)
    (home / ".claude" / "skills" / "foreign-skill" / "SKILL.md").write_text(SKILL, encoding="utf-8")

    project = tmp_path / "project"
    project.mkdir()

    diag = diagnose(project, home=home)
    assert "foreign-skill" not in diag.reports["claude-code"].reachable_skills
