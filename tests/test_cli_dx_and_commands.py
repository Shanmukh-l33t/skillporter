"""CLI Modularization, Dry-Run, JSON Contracts & Developer Experience Tests (P2 Sections 10 & 11)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from skillporter import __version__
from skillporter.cli import main

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

    assert __version__ == "3.0.0"
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

