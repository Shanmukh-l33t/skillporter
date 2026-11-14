"""TDD suite for skill authoring, linting, native harness preview, and activation testing."""

from __future__ import annotations

import json
from pathlib import Path

from skillporter.cli import main


def test_new_scaffolds_valid_skill_with_scripts_references_and_tests(tmp_path, capsys):
    rc = main(
        [
            "new",
            "pdf-extractor",
            "--path",
            str(tmp_path),
            "--description",
            (
                "Extract tables, text, and form fields from PDF files. "
                "Use when the user asks to parse, merge, or extract PDF documents."
            ),
            "--with-scripts",
            "--with-references",
            "--with-tests",
            "--json",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    skill_dir = Path(out["skill_dir"])
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "scripts").is_dir()
    assert (skill_dir / "references").is_dir()
    assert (skill_dir / "skill.test.yaml").is_file()

    # Newly scaffolded skill must pass validate, lint, scan, and test with 0 errors
    assert main(["validate", str(skill_dir)]) == 0
    capsys.readouterr()
    assert main(["lint", str(skill_dir), "--json"]) == 0
    lint_out = json.loads(capsys.readouterr().out)
    assert lint_out["passed"] is True
    assert lint_out["error_count"] == 0

    assert main(["test", str(skill_dir), "--json"]) == 0
    test_out = json.loads(capsys.readouterr().out)
    assert test_out["passed"] is True
    assert test_out["evaluation_mode"] == "deterministic_lexical"


def test_lint_catches_missing_referenced_files_and_unreferenced_scripts(tmp_path, capsys):
    sdir = tmp_path / "broken-refs"
    (sdir / "scripts").mkdir(parents=True)
    (sdir / "scripts" / "orphan.py").write_text("print('unused')\n", encoding="utf-8")
    (sdir / "SKILL.md").write_text(
        "---\n"
        "name: broken-refs\n"
        "description: Validate reference links inside a skill. Use when testing skill linter.\n"
        "---\n\n"
        "# Broken Refs\n\n"
        "See [API Guide](references/missing-guide.md) and run `scripts/does-not-exist.py`.\n",
        encoding="utf-8",
    )

    rc = main(["lint", str(sdir), "--json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is False
    codes = {iss["code"] for iss in out["skills"]["broken-refs"]["issues"]}
    assert "missing-reference-file" in codes
    assert "unreferenced-script" in codes


def test_preview_shows_native_and_adapted_content_plus_lost_capabilities(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    sdir = tmp_path / "src" / "forked-pdf"
    (sdir / "scripts").mkdir(parents=True)
    (sdir / "scripts" / "parse.py").write_text("print('ok')\n", encoding="utf-8")
    (sdir / "SKILL.md").write_text(
        "---\n"
        "name: forked-pdf\n"
        "description: Extract PDF tables in an isolated subagent. Use when parsing PDF tables.\n"
        "allowed-tools: Bash Read\n"
        "context: fork\n"
        "---\n\n"
        "# Forked PDF\n\n"
        "Run `scripts/parse.py` on the input PDF.\n",
        encoding="utf-8",
    )

    # Install into claude-code so `preview forked-pdf --harness cursor` can resolve by installed name too
    assert main(["add", str(sdir), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()

    # Preview for Cursor (both native path and adapted .mdc, plus lost context: fork capability)
    assert main(["preview", "forked-pdf", "--harness", "cursor", "--path", str(ws), "--json"]) == 0
    prev_cursor = json.loads(capsys.readouterr().out)
    assert prev_cursor["harness"] == "cursor"
    assert prev_cursor["skill"] == "forked-pdf"
    assert any("context: fork" in loss for loss in prev_cursor["information_lost"])
    assert prev_cursor["adapted_preview"] is not None
    assert prev_cursor["adapted_preview"]["path"] == ".cursor/rules/forked-pdf.mdc"

    # Preview for Aider (ADAPTED harness) reports CONVENTIONS / adapted limitations honestly
    assert main(["preview", str(sdir), "--harness", "aider", "--json"]) == 0
    prev_aider = json.loads(capsys.readouterr().out)
    assert prev_aider["harness"] == "aider"
    assert prev_aider["support_status"] == "ADAPTED"
    assert len(prev_aider["information_lost"]) >= 1


def test_skill_activation_testing_detects_missed_triggers_and_false_positives(tmp_path, capsys):
    sdir = tmp_path / "pdf-helper"
    sdir.mkdir(parents=True)
    (sdir / "SKILL.md").write_text(
        "---\n"
        "name: pdf-helper\n"
        "description: Extract tables and merge PDF documents. "
        "Use when the user asks to extract tables from a PDF or merge PDF files.\n"
        "---\n\n"
        "# PDF Helper\n\n"
        "Extract tables and merge PDF files.\n",
        encoding="utf-8",
    )
    (sdir / "skill.test.yaml").write_text(
        "should_trigger:\n"
        "  - extract tables from this PDF\n"
        "  - merge these PDF files\n"
        "should_not:\n"
        "  - write a Python Fibonacci function\n"
        "  - fix this CSS flexbox layout\n",
        encoding="utf-8",
    )

    assert main(["test", str(sdir), "--json"]) == 0
    ok_res = json.loads(capsys.readouterr().out)
    assert ok_res["passed"] is True
    suite = ok_res["suites"][0]
    assert suite["missed_activations"] == []
    assert suite["false_positives"] == []

    # Now add a should_trigger prompt about Kubernetes helm charts that the PDF skill never mentions -> fails!
    (sdir / "skill.test.yaml").write_text(
        "should_trigger:\n"
        "  - deploy Kubernetes Helm chart to production cluster\n"
        "should_not:\n"
        "  - extract tables from this PDF\n",
        encoding="utf-8",
    )
    assert main(["test", str(sdir), "--json"]) == 1
    fail_res = json.loads(capsys.readouterr().out)
    assert fail_res["passed"] is False
    suite_f = fail_res["suites"][0]
    assert len(suite_f["missed_activations"]) == 1
    assert len(suite_f["false_positives"]) == 1
