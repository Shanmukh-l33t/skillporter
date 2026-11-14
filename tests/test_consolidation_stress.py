"""Real-world stress suite for `skillporter consolidate` (Section 3 Production Readiness).

Exercises complex multi-agent configurations containing:
  * Long narrative architectural prose & headings
  * Short non-bullet constraints (<15 chars, e.g. `Node >= 24`) and blockquotes (`> SECURITY: ...`)
  * Multi-level nested lists where flattening would destroy meaning (`Allowed exceptions:` under a rule)
  * Markdown tables and both backtick (```) and tilde (~~~) fenced code blocks
  * Agent-specific instructions, path-scoped `.mdc` and `.instructions.md` rules, and precedence ordering
  * Referenced config files (existing vs missing)
  * Conflict blocking during BOTH `--apply` AND `--reconcile`
  * Idempotency across repeated `--reconcile` runs and byte-exact `--rollback`.
"""

from __future__ import annotations

import json

from skillporter.cli import main


def test_consolidation_preserves_unclassified_prose_short_lines_nested_lists_tables_and_tildes(tmp_path, capsys):
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {"strict": true}}\n', encoding="utf-8")
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".github" / "instructions").mkdir(parents=True)

    claude_orig = (
        "# Billing Service Engineering Guide\n\n"
        "## Architecture Narrative\n\n"
        "The billing service processes asynchronous Stripe webhook events over SQS.\n"
        "All idempotency keys are persisted in PostgreSQL before any ledger mutation occurs.\n\n"
        "Node >= 24\n\n"
        "> SECURITY: Never log raw Stripe webhook signatures, JWTs, or cardholder PII.\n\n"
        "## Core Standards\n\n"
        "- Follow compiler settings in `tsconfig.json` and check legacy `src/config/removed_flags.ts`.\n"
        "- Database migration rules:\n"
        "  - Always include a reversible `down` migration.\n"
        "  - Allowed exceptions:\n"
        "    - Ephemeral fixtures inside `tests/fixtures/`.\n"
        "- Delegate deep security reviews to a Claude subagent before release.\n\n"
        "| Environment | Region | KMS Required |\n"
        "|---|---|---|\n"
        "| staging | us-east-1 | yes |\n"
        "| prod | us-west-2 | yes |\n\n"
        "~~~bash\n"
        "pnpm --filter billing test:integration\n"
        "~~~\n"
    )

    agents_orig = (
        "# Agent Instructions\n\n"
        "- Database migration rules:\n"
        "  - Always include a reversible `down` migration.\n"
        "  - Allowed exceptions:\n"
        "    - Ephemeral fixtures inside `tests/fixtures/`.\n"
        "- Require explicit Zod validation on every external webhook payload.\n"
    )

    scoped_cursor = (
        "---\n"
        "description: API controller rules\n"
        "globs: src/api/**/*.ts\n"
        "alwaysApply: false\n"
        "---\n\n"
        "- Return RFC 7807 problem-details JSON from every controller error handler.\n"
    )

    scoped_copilot = (
        "---\n"
        'description: "Prisma schema rules"\n'
        'applyTo: "prisma/**"\n'
        "---\n\n"
        "- Every foreign key in Prisma must declare an explicit `@@index`.\n"
    )

    (tmp_path / "CLAUDE.md").write_text(claude_orig, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(agents_orig, encoding="utf-8")
    (tmp_path / ".cursor" / "rules" / "api.mdc").write_text(scoped_cursor, encoding="utf-8")
    (tmp_path / ".github" / "instructions" / "db.instructions.md").write_text(scoped_copilot, encoding="utf-8")

    # 1. Preview first (read-only): must report unclassified_sections, outdated ref, and preserved scoped files
    assert main(["consolidate", str(tmp_path), "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert len(preview["unclassified_sections"]) >= 1
    assert set(preview["preserved_scoped_files"]) == {
        ".cursor/rules/api.mdc",
        ".github/instructions/db.instructions.md",
    }
    assert any("src/config/removed_flags.ts" in o["reference"] for o in preview["outdated_instructions"])
    # Existing tsconfig.json must NOT be flagged as outdated
    assert not any("tsconfig.json" in o["reference"] for o in preview["outdated_instructions"])

    # Verify nested list was NOT flattened into orphan top-level "Allowed exceptions:" directive!
    shared_dirs = preview["shared_instructions"]
    assert not any(d.strip().startswith("Allowed exceptions") for d in shared_dirs)
    assert any("Database migration rules:" in d and "Allowed exceptions:" in d for d in shared_dirs)

    # 2. Apply consolidation: 0 silent content drops!
    assert main(["consolidate", str(tmp_path), "--apply", "--json"]) == 0
    capsys.readouterr()

    claude_merged = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    agents_merged = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    for target_txt in (claude_merged, agents_merged):
        # Narrative prose, short `<15 char` line, blockquote, nested hierarchy, table, and tilde block all survive!
        assert "asynchronous Stripe webhook events over SQS" in target_txt
        assert "Node >= 24" in target_txt
        assert "SECURITY: Never log raw Stripe webhook signatures" in target_txt
        assert "  - Allowed exceptions:\n    - Ephemeral fixtures inside `tests/fixtures/`." in target_txt
        assert "| prod | us-west-2 | yes |" in target_txt
        assert "pnpm --filter billing test:integration" in target_txt
        assert "Require explicit Zod validation" in target_txt

    # Agent-specific Claude subagent rule stays in CLAUDE.md and does NOT leak into AGENTS.md
    assert "Claude subagent" in claude_merged
    assert "Claude subagent" not in agents_merged

    # Scoped rules remain 100% untouched byte-for-byte
    assert (tmp_path / ".cursor" / "rules" / "api.mdc").read_text(encoding="utf-8") == scoped_cursor
    assert (tmp_path / ".github" / "instructions" / "db.instructions.md").read_text(encoding="utf-8") == scoped_copilot

    # 3. Reconciliation conflict guard: manual edit adding conflicting package manager must fail closed!
    (tmp_path / "CLAUDE.md").write_text(
        claude_merged + "\n- Always use pnpm for workspace dependency installs.\n",
        encoding="utf-8",
    )
    assert main(["consolidate", str(tmp_path), "--reconcile", "--json"]) == 0
    capsys.readouterr()

    # Ensure idempotency: re-reconciling did NOT duplicate narrative prose or tables!
    claude_after_rec1 = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_after_rec1.count("asynchronous Stripe webhook events over SQS") == 1
    assert claude_after_rec1.count("| prod | us-west-2 | yes |") == 1

    # Now add a CONTRADICTORY manual edit (`Always use yarn`) in AGENTS.md -> `--reconcile` must block!
    (tmp_path / "AGENTS.md").write_text(
        (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        + "\n- Always use yarn for workspace dependency installs.\n",
        encoding="utf-8",
    )
    assert main(["consolidate", str(tmp_path), "--reconcile"]) == 1
    assert "conflict" in capsys.readouterr().err.lower()

    # 4. Rollback restores exact original files byte-for-byte
    assert main(["consolidate", str(tmp_path), "--rollback", "--json"]) == 0
    capsys.readouterr()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == claude_orig
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == agents_orig


def test_instruction_precedence_ordering_in_context_inspector(tmp_path, capsys):
    (tmp_path / ".claude").mkdir()
    (tmp_path / "CLAUDE.md").write_text("# Root Claude (precedence 10)\n- Root rule.\n", encoding="utf-8")
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# Subdir Claude (precedence 20)\n- Sub rule.\n", encoding="utf-8")
    (tmp_path / ".cursorrules").write_text("# Legacy Cursor (precedence 30)\n- Legacy rule.\n", encoding="utf-8")
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".cursor" / "rules" / "modern.mdc").write_text(
        "---\ndescription: Modern\nglobs: src/**\nalwaysApply: false\n---\n- Scoped rule.\n",
        encoding="utf-8",
    )

    assert main(["context", str(tmp_path), "--harness", "claude-code", "--json"]) == 0
    c_ctx = json.loads(capsys.readouterr().out)
    assert [x["path"] for x in c_ctx["active_instructions"]] == ["CLAUDE.md", ".claude/CLAUDE.md"]

    assert main(["context", str(tmp_path), "--harness", "cursor", "--json"]) == 0
    cur_ctx = json.loads(capsys.readouterr().out)
    assert [x["path"] for x in cur_ctx["active_instructions"]] == [".cursor/rules/modern.mdc", ".cursorrules"]
