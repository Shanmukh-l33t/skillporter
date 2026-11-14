"""TDD suite for rules consolidation (`consolidate`) and active context stack (`context`)."""

from __future__ import annotations

import json

from skillporter.cli import main


def test_consolidate_discovers_overlap_conflicts_outdated_and_preserves_originals_by_default(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const ok = true;\n", encoding="utf-8")

    claude_text = (
        "# Project Instructions\n\n"
        "- Run `pytest` before committing any backend change.\n"
        "- Follow strict TypeScript typing with zero `any` casts.\n"
        "- Always use pnpm for package installation.\n"
        "- Delegate deep audits to a Claude subagent when context grows.\n"
        "- Legacy auth flow lives in `src/legacy/missing_auth.ts`.\n"
    )
    agents_text = (
        "# Agent Guidelines\n\n"
        "- Run `pytest` before committing any backend change.\n"
        "- Follow strict TypeScript typing with zero `any` casts.\n"
        "- Always use npm for package installation.\n"
    )
    copilot_dir = tmp_path / ".github"
    copilot_dir.mkdir()
    copilot_text = (
        "# Copilot Rules\n\n"
        "- Run `pytest` before committing any backend change.\n"
        "- Follow strict TypeScript typing with zero `any` casts.\n"
    )

    (tmp_path / "CLAUDE.md").write_text(claude_text, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(agents_text, encoding="utf-8")
    (copilot_dir / "copilot-instructions.md").write_text(copilot_text, encoding="utf-8")

    # 1. Read-only default discovery: reports overlap, pnpm vs npm conflict, outdated path, agent-specific rule
    assert main(["consolidate", str(tmp_path), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert len(rep["discovered_files"]) == 3
    assert rep["overlap_percentage"] > 30
    assert len(rep["conflicts"]) >= 1
    assert any("pnpm" in c["summary"].lower() and "npm" in c["summary"].lower() for c in rep["conflicts"])
    assert any("src/legacy/missing_auth.ts" in o["reference"] for o in rep["outdated_instructions"])
    assert "claude-code" in rep["agent_specific_instructions"]

    # Originals MUST remain untouched in read-only mode
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == claude_text
    assert not (tmp_path / ".skillporter" / "instructions" / "canonical.md").exists()


def test_consolidate_apply_backup_bidirectional_drift_reconcile_and_rollback(tmp_path, capsys):
    orig_claude = "# Rules\n\n- Keep functions under 40 lines.\n- Write unit tests first.\n"
    orig_agents = "# Rules\n\n- Keep functions under 40 lines.\n- Validate inputs at system boundaries.\n"
    (tmp_path / "CLAUDE.md").write_text(orig_claude, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(orig_agents, encoding="utf-8")

    # 1. Apply consolidation -> creates backups, writes canonical.md, and synchronizes native files
    assert main(["consolidate", str(tmp_path), "--apply", "--json"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] is True
    canonical_file = tmp_path / ".skillporter" / "instructions" / "canonical.md"
    assert canonical_file.is_file()
    assert "Validate inputs at system boundaries" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Write unit tests first" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    # 2. Simulate manual edit to generated AGENTS.md
    (tmp_path / "AGENTS.md").write_text(
        (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        + "\n- Never commit plaintext credentials or .env files.\n",
        encoding="utf-8",
    )

    # `consolidate --status` detects manual modification and exits 1
    assert main(["consolidate", str(tmp_path), "--status", "--json"]) == 1
    st = json.loads(capsys.readouterr().out)
    assert len(st["manual_modifications"]) == 1
    assert st["manual_modifications"][0]["file"] == "AGENTS.md"
    assert any("credentials" in line for line in st["manual_modifications"][0]["added_directives"])

    # `consolidate --apply` without --force or --reconcile refuses to clobber manual edits!
    assert main(["consolidate", str(tmp_path), "--apply"]) == 1
    capsys.readouterr()

    # 3. `consolidate --reconcile` imports the manual edit into canonical.md and propagates to CLAUDE.md!
    assert main(["consolidate", str(tmp_path), "--reconcile", "--json"]) == 0
    capsys.readouterr()
    assert "Never commit plaintext credentials" in canonical_file.read_text(encoding="utf-8")
    assert "Never commit plaintext credentials" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    # 4. `consolidate --rollback` restores exact pre-consolidation original files from backup
    assert main(["consolidate", str(tmp_path), "--rollback", "--json"]) == 0
    capsys.readouterr()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == orig_claude
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == orig_agents


def test_context_inspector_reports_active_and_ignored_instructions_per_harness(tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("# Claude Only\n\n- Follow Claude conventions.\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Shared Agents\n\n- Follow Codex conventions.\n", encoding="utf-8")

    # Inspect what Codex actually receives vs ignores
    assert main(["context", str(tmp_path), "--harness", "codex", "--json"]) == 0
    ctx_codex = json.loads(capsys.readouterr().out)
    active_files = [f["path"] for f in ctx_codex["active_instructions"]]
    ignored_files = [f["path"] for f in ctx_codex["ignored_instructions"]]
    assert "AGENTS.md" in active_files
    assert "CLAUDE.md" in ignored_files
