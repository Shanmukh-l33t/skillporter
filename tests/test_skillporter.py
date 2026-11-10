"""Functional tests for skillporter.

Each test builds a throwaway skill tree in tmp_path; nothing touches the real
home directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skillporter import harnesses
from skillporter.cli import main
from skillporter.diagnose import diagnose, resolve_path
from skillporter.frontmatter import parse_skill, split_frontmatter, validate
from skillporter.install import InstallError, install, uninstall

GOOD_SKILL = """---
name: pdf-tools
description: Extract text from PDFs and fill forms. Use when the user mentions PDFs, forms, or document extraction.
license: MIT
metadata:
  author: test
---

# PDF tools

Step 1. Run scripts/extract.py.
"""


def make_skill(root: Path, name: str = "pdf-tools", body: str = GOOD_SKILL) -> Path:
    skill_dir = root / ".agents" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    text = body.replace("name: pdf-tools", f"name: {name}")
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir


# --------------------------------------------------------------------------
# frontmatter parsing / validation
# --------------------------------------------------------------------------

def test_split_frontmatter_extracts_metadata_and_body():
    fm, body = split_frontmatter(GOOD_SKILL)
    assert fm["name"] == "pdf-tools"
    assert fm["license"] == "MIT"
    assert fm["metadata"] == {"author": "test"}
    assert body.startswith("# PDF tools")


def test_block_scalar_description_is_joined():
    text = "---\nname: a-b\ndescription: >\n  Do a thing.\n  Use when needed.\n---\nbody\n"
    fm, _ = split_frontmatter(text)
    assert fm["description"] == "Do a thing. Use when needed."


def test_valid_skill_has_no_errors(tmp_path):
    skill = make_skill(tmp_path)
    issues = validate(parse_skill(skill / "SKILL.md"))
    assert [i for i in issues if i.level == "error"] == []


def test_name_must_match_directory(tmp_path):
    skill = make_skill(tmp_path, name="pdf-tools")
    doc = parse_skill(skill / "SKILL.md")
    doc.frontmatter["name"] = "different-name"
    codes = {i.code for i in validate(doc)}
    assert "name-directory-mismatch" in codes


def test_name_rejects_uppercase_and_double_hyphen():
    from skillporter.frontmatter import SkillDoc

    for bad in ("PDF-Tools", "pdf--tools", "-pdf", "pdf-"):
        doc = SkillDoc(path=Path(f"/tmp/{bad}/SKILL.md"), frontmatter={
            "name": bad, "description": "A description long enough to pass the vague check. Use when testing.",
        }, body="x")
        codes = {i.code for i in validate(doc)}
        assert "name-invalid-chars" in codes, bad


def test_description_too_long_is_error(tmp_path):
    skill = make_skill(tmp_path)
    doc = parse_skill(skill / "SKILL.md")
    doc.frontmatter["description"] = "x" * 1025
    codes = {i.code for i in validate(doc)}
    assert "description-too-long" in codes


def test_missing_frontmatter_is_error(tmp_path):
    p = tmp_path / "bad" / "SKILL.md"
    p.parent.mkdir()
    p.write_text("# no frontmatter\n", encoding="utf-8")
    codes = {i.code for i in validate(parse_skill(p))}
    assert "no-frontmatter" in codes


def test_vague_description_warns(tmp_path):
    skill = make_skill(tmp_path)
    doc = parse_skill(skill / "SKILL.md")
    doc.frontmatter["description"] = "Helps with PDFs"
    codes = {i.code for i in validate(doc)}
    assert "description-vague" in codes


# --------------------------------------------------------------------------
# harness matrix
# --------------------------------------------------------------------------

def test_matrix_paths_match_published_docs():
    """Guard the matrix against silent drift: these came from vendor docs."""
    claude = {p.path for p in harnesses.get("claude-code").paths}
    codex = {p.path for p in harnesses.get("codex").paths}
    cursor = {p.path for p in harnesses.get("cursor").paths}

    assert ".claude/skills" in claude
    assert ".agents/skills" not in claude, "Claude Code does not read .agents/skills"
    assert ".agents/skills" in codex
    assert ".claude/skills" not in codex, "Codex does not read .claude/skills"
    # Cursor is the permissive one: it reads all four roots.
    assert {".agents/skills", ".cursor/skills", ".claude/skills", ".codex/skills"} <= cursor


def test_unknown_harness_lists_known_ones():
    with pytest.raises(KeyError) as exc:
        harnesses.get("nope")
    assert "claude-code" in str(exc.value)


def test_resolve_path_is_profile_safe(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "custom-hermes"))
    resolved = resolve_path("$HERMES_HOME/skills", "user", tmp_path, home=home)
    assert resolved == tmp_path / "custom-hermes" / "skills"


def test_resolve_path_falls_back_to_dot_hermes(monkeypatch, tmp_path):
    """With no HERMES_HOME set, never hardcode an absolute user path."""
    home = tmp_path / "home"
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert resolve_path("$HERMES_HOME/skills", "user", tmp_path, home=home) == home / ".hermes" / "skills"


# --------------------------------------------------------------------------
# the bug this tool exists for
# --------------------------------------------------------------------------

def test_diagnose_flags_skill_invisible_to_codex(tmp_path):
    """Skill authored only in .claude/skills is invisible to Codex."""
    skill_dir = tmp_path / ".claude" / "skills" / "pdf-tools"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(GOOD_SKILL, encoding="utf-8")

    diag = diagnose(tmp_path)
    assert "pdf-tools" in diag.reports["claude-code"].reachable_skills
    assert "pdf-tools" not in diag.reports["codex"].reachable_skills
    assert any("codex" in f for f in diag.findings)


def test_diagnose_agents_skills_reaches_codex_and_cursor(tmp_path):
    make_skill(tmp_path)  # authors under .agents/skills
    diag = diagnose(tmp_path)
    assert "pdf-tools" in diag.reports["codex"].reachable_skills
    assert "pdf-tools" in diag.reports["cursor"].reachable_skills
    # ...but not Claude Code, which never reads .agents/skills
    assert "pdf-tools" not in diag.reports["claude-code"].reachable_skills


def test_diagnose_detects_broken_symlink(tmp_path):
    """The worktree/clean-clone failure: a link whose target is gone."""
    skills = tmp_path / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "ghost-skill").symlink_to(tmp_path / "does-not-exist")

    diag = diagnose(tmp_path)
    statuses = [loc.status for loc in diag.reports["claude-code"].locations]
    assert "broken" in statuses
    assert any("broken symlink" in f for f in diag.findings)


def test_diagnose_empty_when_no_skills(tmp_path):
    diag = diagnose(tmp_path)
    assert diag.skills == []
    assert all(not r.reachable_skills for r in diag.reports.values())


def test_diagnose_reports_invalid_frontmatter(tmp_path):
    skill = make_skill(tmp_path)
    (skill / "SKILL.md").write_text("---\nname: BAD_NAME\n---\nbody\n", encoding="utf-8")
    diag = diagnose(tmp_path)
    joined = "\n".join(diag.findings)
    assert "name-invalid-chars" in joined or "description" in joined


# --------------------------------------------------------------------------
# install / uninstall
# --------------------------------------------------------------------------

def test_install_copy_reaches_harness(tmp_path):
    src = make_skill(tmp_path / "src", name="porter-demo")
    results = install(tmp_path, src, ["codex"], strategy="copy")
    assert results[0].action == "created"
    assert (tmp_path / ".agents" / "skills" / "porter-demo" / "SKILL.md").is_file()


def test_install_copy_into_claude(tmp_path):
    src = make_skill(tmp_path / "src", name="porter-demo")
    install(tmp_path, src, ["claude-code"], strategy="copy")
    assert (tmp_path / ".claude" / "skills" / "porter-demo" / "SKILL.md").is_file()
    diag = diagnose(tmp_path)
    assert "porter-demo" in diag.reports["claude-code"].reachable_skills


def test_install_is_idempotent_and_refuses_overwrite(tmp_path):
    src = make_skill(tmp_path / "src", name="porter-demo")
    install(tmp_path, src, ["codex"], strategy="copy")
    with pytest.raises(InstallError):
        install(tmp_path, src, ["codex"], strategy="copy")
    # --force overwrites cleanly
    results = install(tmp_path, src, ["codex"], strategy="copy", force=True)
    assert results[0].action == "created"


def test_install_symlink_strategy(tmp_path):
    if os.name == "nt":
        pytest.skip("symlink install is refused on Windows by design")
    src = make_skill(tmp_path / "src", name="porter-demo")
    install(tmp_path, src, ["claude-code"], strategy="symlink")
    dest = tmp_path / ".claude" / "skills" / "porter-demo"
    assert dest.is_symlink()
    assert (dest / "SKILL.md").is_file()


def test_install_rejects_non_skill_directory(tmp_path):
    empty = tmp_path / "not-a-skill"
    empty.mkdir()
    with pytest.raises(InstallError):
        install(tmp_path, empty, ["codex"])


def test_install_rejects_unknown_harness(tmp_path):
    src = make_skill(tmp_path / "src", name="porter-demo")
    with pytest.raises(KeyError):
        install(tmp_path, src, ["not-a-harness"])


def test_uninstall_removes_copy(tmp_path):
    src = make_skill(tmp_path / "src", name="porter-demo")
    install(tmp_path, src, ["codex"], strategy="copy")
    uninstall(tmp_path, "porter-demo", ["codex"])
    assert not (tmp_path / ".agents" / "skills" / "porter-demo").exists()


def test_uninstall_missing_is_skipped(tmp_path):
    results = uninstall(tmp_path, "never-installed", ["codex"])
    assert results[0].action == "skipped"


# --------------------------------------------------------------------------
# CLI behaviour (exit codes are the CI contract)
# --------------------------------------------------------------------------

def test_cli_validate_ok(tmp_path, capsys):
    make_skill(tmp_path)
    assert main(["validate", str(tmp_path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_validate_fails_on_error(tmp_path):
    bad = tmp_path / "BadName"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: BadName\ndescription: short\n---\n", encoding="utf-8")
    assert main(["validate", str(tmp_path)]) == 1


def test_cli_diagnose_exit_codes(tmp_path):
    make_skill(tmp_path)
    # .agents/skills only: Claude Code cannot see it -> exit 1
    assert main(["diagnose", str(tmp_path)]) == 1


def test_cli_diagnose_json_is_valid(tmp_path, capsys):
    make_skill(tmp_path)
    main(["diagnose", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["skills"] == ["pdf-tools"]
    assert "claude-code" in payload["harnesses"]


def test_cli_matrix_json(capsys):
    assert main(["matrix", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(r["harness"] == "cursor" and r["recursive"] for r in rows)


def test_cli_install_then_diagnose_clean(tmp_path):
    src = make_skill(tmp_path / "src", name="porter-demo")
    assert main(["install", str(src), "--harness", "claude-code", "--harness", "codex", "--path", str(tmp_path)]) == 0
    diag = diagnose(tmp_path)
    for harness in ("claude-code", "codex"):
        assert "porter-demo" in diag.reports[harness].reachable_skills


def test_module_entrypoint_runs():
    """`python -m skillporter` must work without installation."""
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "skillporter", "matrix"],
        capture_output=True, text=True, cwd=root, timeout=60,
        env={**os.environ, "PYTHONPATH": str(root)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "claude-code" in proc.stdout
