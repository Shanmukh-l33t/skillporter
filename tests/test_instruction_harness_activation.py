"""Harness activation details for generated instruction files (verified against real agent behavior)."""

from __future__ import annotations

import json

from skillporter.cli import main


def _project(tmp_path):
    body = "# Rules\n\n- Use pytest for tests.\n- Keep functions small.\n"
    (tmp_path / "AGENTS.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_aider_output_carries_an_activation_warning(tmp_path, capsys):
    ws = _project(tmp_path)
    assert main(["consolidate", str(ws), "--apply", "--harness", "aider", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "CONVENTIONS.md" in out["written_files"]
    assert any("aider --read CONVENTIONS.md" in w for w in out["warnings"])
    assert (ws / "CONVENTIONS.md").is_file()
    assert not (ws / ".aider.conf.yml").exists()  # skillporter must not edit the user's aider config


def test_windsurf_rule_declares_an_always_on_trigger(tmp_path, capsys):
    ws = _project(tmp_path)
    assert main(["consolidate", str(ws), "--apply", "--harness", "windsurf", "--json"]) == 0
    capsys.readouterr()
    text = (ws / ".windsurf" / "rules" / "project-instructions.md").read_text(encoding="utf-8")
    assert text.startswith("---\ntrigger: always_on\n---\n")
    assert "Use pytest for tests." in text


def test_scoped_windsurf_and_cline_rules_are_never_rewritten(tmp_path, capsys):
    ws = _project(tmp_path)
    (ws / ".windsurf" / "rules").mkdir(parents=True)
    glob_rule = "---\ntrigger: glob\nglobs: src/api/**\n---\n\n- Return problem+json from every handler.\n"
    (ws / ".windsurf" / "rules" / "api.md").write_text(glob_rule, encoding="utf-8")
    (ws / ".clinerules").mkdir()
    cline_rule = "---\npaths:\n  - docs/**\n---\n\n- Write docs in plain English.\n"
    (ws / ".clinerules" / "docs.md").write_text(cline_rule, encoding="utf-8")

    assert main(["consolidate", str(ws), "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert {".windsurf/rules/api.md", ".clinerules/docs.md"} <= set(preview["preserved_scoped_files"])

    assert main(["consolidate", str(ws), "--apply", "--json"]) == 0
    capsys.readouterr()
    assert (ws / ".windsurf" / "rules" / "api.md").read_text(encoding="utf-8") == glob_rule
    assert (ws / ".clinerules" / "docs.md").read_text(encoding="utf-8") == cline_rule
