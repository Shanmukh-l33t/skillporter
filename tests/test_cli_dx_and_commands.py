"""CLI Modularization, Dry-Run, JSON Contracts & Developer Experience Tests (P2 Sections 10 & 11)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from skillporter import __version__
from skillporter.cli import main
from skillporter.environment import EnvironmentSnapshot, SkillEnvironmentEntry
from skillporter.state import ManagedSkillRecord, save_state

DX_SKILL = """---
name: dx-skill
description: >
  Developer experience test skill verifying dry-run, JSON output, and audit subcommand.
  Use when testing CLI developer experience.
license: MIT
metadata:
  version: "1.0.0"
---

# DX Skill

Step 1. Run check.
"""


def _write_skill(base: Path, name: str = "dx-skill", ver: str = "1.0.0") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    txt = DX_SKILL.replace("name: dx-skill", f"name: {name}").replace('version: "1.0.0"', f'version: "{ver}"')
    (sdir / "SKILL.md").write_text(txt, encoding="utf-8")
    return sdir


def test_commands_subpackage_modular_separation_and_slim_cli():
    for mod_name in (
        "skillporter.commands",
        "skillporter.commands.add",
        "skillporter.commands.remove",
        "skillporter.commands.sync",
        "skillporter.commands.scan",
        "skillporter.commands.audit",
        "skillporter.commands.registry",
        "skillporter.commands.doctor",
    ):
        mod = importlib.import_module(mod_name)
        assert mod is not None

    cli_path = Path(__file__).resolve().parents[1] / "skillporter" / "cli.py"
    line_count = len(cli_path.read_text(encoding="utf-8").splitlines())
    assert line_count < 500, f"cli.py should dispatch cleanly (<500 lines), got {line_count}"


def test_version_parity_across_python_root_npm_and_subdir_npm():
    repo = Path(__file__).resolve().parents[1]
    root_pkg = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    npm_pkg = json.loads((repo / "npm" / "package.json").read_text(encoding="utf-8"))
    pyproject_txt = (repo / "pyproject.toml").read_text(encoding="utf-8")

    assert __version__ == "3.2.0"
    assert root_pkg["version"] == __version__
    assert npm_pkg["version"] == __version__
    assert f'version = "{__version__}"' in pyproject_txt


def test_dry_run_and_json_across_install_sync_remove_update_rollback_and_audit(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_skill(tmp_path / "upstream", "dx-skill", ver="1.0.0")

    # 1. `install --json`
    assert main(["install", str(src), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    inst_json = json.loads(capsys.readouterr().out)
    assert inst_json["installed"][0]["harness"] == "claude-code"

    # 2. `sync --dry-run --json` does NOT write to codex yet
    assert main(["sync", str(ws), "--harness", "claude-code", "--harness", "codex", "--dry-run", "--json"]) == 0
    sync_dry = json.loads(capsys.readouterr().out)
    assert sync_dry["dry_run"] is True
    assert not (ws / ".agents" / "skills" / "dx-skill").exists()

    # Real `sync --json` writes to codex
    assert main(["sync", str(ws), "--harness", "claude-code", "--harness", "codex", "--json"]) == 0
    sync_real = json.loads(capsys.readouterr().out)
    assert sync_real["dry_run"] is False
    assert (ws / ".agents" / "skills" / "dx-skill" / "SKILL.md").is_file()

    # 3. `update --dry-run --json` previews update without mutating installed v1.0.0
    _write_skill(tmp_path / "upstream", "dx-skill", ver="2.0.0")
    assert main(["update", "dx-skill", "--path", str(ws), "--dry-run", "--json"]) == 0
    up_dry = json.loads(capsys.readouterr().out)
    assert up_dry["dry_run"] is True
    assert 'version: "1.0.0"' in (ws / ".claude" / "skills" / "dx-skill" / "SKILL.md").read_text(encoding="utf-8")

    # Real `update --json` updates to v2.0.0 and creates rollback snapshot
    assert main(["update", "dx-skill", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert 'version: "2.0.0"' in (ws / ".claude" / "skills" / "dx-skill" / "SKILL.md").read_text(encoding="utf-8")

    # 4. `rollback --dry-run --json` previews rollback without restoring v1.0.0 yet
    assert main(["rollback", "dx-skill", "--path", str(ws), "--dry-run", "--json"]) == 0
    rb_dry = json.loads(capsys.readouterr().out)
    assert rb_dry["dry_run"] is True
    assert 'version: "2.0.0"' in (ws / ".claude" / "skills" / "dx-skill" / "SKILL.md").read_text(encoding="utf-8")

    # 5. `remove --dry-run --json` previews removal without deleting files
    assert main(["remove", "dx-skill", "--harness", "claude-code", "--path", str(ws), "--dry-run", "--json"]) == 0
    rm_dry = json.loads(capsys.readouterr().out)
    assert rm_dry["dry_run"] is True
    assert (ws / ".claude" / "skills" / "dx-skill" / "SKILL.md").is_file()

    # 6. `audit --json` inspects installed skills, lockfile status, and `.skillporter/audit.jsonl` events
    assert main(["audit", str(ws), "--json"]) == 0
    audit_payload = json.loads(capsys.readouterr().out)
    assert audit_payload["healthy"] is True
    assert "dx-skill" in audit_payload["skills"]
    assert len(audit_payload["audit_events"]) >= 2


def test_ci_and_release_workflows_gated_attested_and_injection_safe():
    import re

    repo = Path(__file__).resolve().parents[1]
    action_yml = (repo / "action.yml").read_text(encoding="utf-8")
    publish_yml = (repo / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    ci_yml = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    # 1. action.yml must never interpolate ${{ inputs.* }} directly inside shell `run:` blocks
    run_blocks = action_yml.split("run: |")[1:]
    for block in run_blocks:
        # Stop at next step `- name:`
        script_part = block.split("    - name:", 1)[0]
        assert not re.search(r"\$\{\{\s*inputs\.", script_part), "Expression injection in action.yml run block!"

    # 2. publish.yml must run verify-gate (pytest + ruff), attest provenance, and upload SHA256SUMS.txt
    assert "verify-gate:" in publish_yml
    assert "pytest" in publish_yml
    assert "ruff check" in publish_yml
    assert "needs: [verify-gate]" in publish_yml
    assert "attest-build-provenance" in publish_yml
    assert "SHA256SUMS.txt" in publish_yml

    # 3. ci.yml must cover ubuntu, macos, windows, bandit, twine check, and secret scan
    for required_token in ("ubuntu-latest", "macos-latest", "windows-latest", "bandit", "twine check", "gitleaks"):
        assert required_token in ci_yml



def test_bare_invocation_on_a_pipe_starts_the_mcp_server(monkeypatch):
    """MCP clients and directory indexers spawn the console script with a pipe."""
    import os
    import sys

    from skillporter import cli

    read_fd, write_fd = os.pipe()
    started = []
    monkeypatch.setattr(cli, "run_mcp_stdio", lambda **kwargs: started.append(kwargs) or 0)
    fake_stdin = os.fdopen(read_fd, "r")
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    try:
        rc = cli.main([])
    finally:
        os.close(write_fd)
        fake_stdin.close()

    assert rc == 0
    assert len(started) == 1, "a piped stdin with no subcommand must start the MCP server"


def test_bare_invocation_on_a_terminal_shows_short_guidance(monkeypatch, capsys):
    import os
    import sys

    from skillporter import cli

    with open(os.devnull) as devnull:
        monkeypatch.setattr(sys, "stdin", devnull)
        rc = cli.main([])

    captured = capsys.readouterr()
    assert rc == 0
    assert "skillporter status" in captured.out
    assert "skillporter --help" in captured.out
    assert "Workflow command groups:" not in captured.out
    assert len(captured.out.splitlines()) < 10

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "usage: skillporter" in help_text
    assert "Workflow command groups:" in help_text


def test_list_filters_local_skills_in_text_quiet_and_json(tmp_path, capsys):
    _write_skill(tmp_path / ".claude" / "skills", "ops-notes")
    _write_skill(tmp_path / "unassigned", "design-notes")
    rec = ManagedSkillRecord(
        name="ops-check", source="./ops-check", harnesses=["claude-code", "codex", "cursor", "hermes", "zed"]
    )
    save_state(tmp_path, {rec.name: rec})
    args = ["list", str(tmp_path)]

    assert main([*args, "--json"]) == 0
    unfiltered = {r["name"]: r for r in json.loads(capsys.readouterr().out)}
    assert set(unfiltered) == {"ops-notes", "design-notes", "ops-check"}
    assert main([*args, "--search", " NOTES ", "--harness", "claude", "--unmanaged-only", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [unfiltered["ops-notes"]]
    assert main([*args, "--managed-only", "-q"]) == 0
    assert capsys.readouterr().out == "ops-check\n"
    assert main([*args, "--harness", "zed", "--managed-only"]) == 0
    row = capsys.readouterr().out.splitlines()[-1]
    assert "ops-check" in row and "zed" in row and "(+1)" in row
    assert main([*args, "--search", "missing"]) == 0
    assert "No local skills match" in capsys.readouterr().out
    assert main([*args, "--harness", "unknown-test-harness"]) == 2
    assert "unknown harness" in capsys.readouterr().err


def test_diagnose_summarizes_findings_and_verbose_restores_matrix(tmp_path, capsys):
    for n in range(7):
        _write_skill(tmp_path / ".claude" / "skills", f"notes-{n}")
    args = ["diagnose", str(tmp_path), "--harness", "codex"]
    assert main(args) == 1
    short = capsys.readouterr().out
    assert "7 skill(s) found · 7 finding(s)" in short
    assert "... and 2 more" in short
    assert "--verbose" in short and "notes-6" not in short

    assert main([*args, "--verbose"]) == 1
    detail = capsys.readouterr().out
    assert "SKILL" in detail and "MISSING" in detail and "notes-6" in detail
    assert "... and" not in detail
    assert main([*args, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["skills"]) == len(payload["findings"]) == 7
    assert list(payload["harnesses"]) == ["codex"]


def test_status_distinguishes_environment_findings_from_skill_states(tmp_path, monkeypatch, capsys):
    untracked = SkillEnvironmentEntry(name="notes", version="1.0.0", status="UNMANAGED", on_disk=True)
    snap = EnvironmentSnapshot(
        label="test",
        root=tmp_path,
        skills={"notes": untracked},
        healthy=False,
        findings=[f"diagnostic finding {i}" for i in range(7)],
    )
    monkeypatch.setattr("skillporter.commands.environment_cmd.capture_environment", lambda *a, **kw: snap)
    args = ["status", str(tmp_path)]
    assert main(args) == 1
    short = capsys.readouterr().out
    assert "NEEDS ATTENTION" in short and "1 unmanaged" in short and "0 needing attention" not in short
    assert "Findings:" in short and "... and 2 more" in short
    assert "diagnostic finding 6" not in short and "VERSION" not in short

    assert main([*args, "--verbose"]) == 1
    detail = capsys.readouterr().out
    assert "notes" in detail and "untracked" in detail and "1.0.0" not in detail
    assert "diagnostic finding 6" in detail and "... and" not in detail
    assert main([*args, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["attention_skills"] == [] and payload["findings"] == snap.findings
    assert payload["skills"]["notes"]["version"] == "1.0.0"


def test_corrupt_manifest_reports_a_clear_error_instead_of_a_traceback(tmp_path, capsys):
    (tmp_path / "skillporter.yaml").write_text("{\n", encoding="utf-8")
    for args in (["status"], ["list"], ["diagnose"], ["doctor"], ["status", "--json"]):
        capsys.readouterr()
        rc = main([*args, str(tmp_path)])
        cap = capsys.readouterr()
        assert rc == 2, (args, rc, cap.out, cap.err)
        assert cap.out == ""
        assert cap.err.startswith("error: corrupted skillporter.yaml"), (args, cap.err)
        assert "Traceback" not in cap.err
