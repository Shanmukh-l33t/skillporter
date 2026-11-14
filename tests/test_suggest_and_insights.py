"""TDD suite for smart local-first project recommendations (`suggest`) and context insights (`insights`)."""

from __future__ import annotations

import json

from skillporter.cli import main


def test_suggest_analyzes_local_stack_and_explains_relevance_without_network(tmp_path, capsys):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "web-app",
                "dependencies": {"next": "15.0.0", "react": "19.0.0", "@prisma/client": "6.0.0"},
                "devDependencies": {"@playwright/test": "1.49.0", "typescript": "5.7.0"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "prisma").mkdir()
    (tmp_path / "prisma" / "schema.prisma").write_text(
        'datasource db {\n  provider = "postgresql"\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text("FROM node:20-alpine\n", encoding="utf-8")

    assert main(["suggest", str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["local_only"] is True
    detected_ids = {s["signal"] for s in out["detected_stack"]}
    assert {"nextjs", "prisma", "playwright", "postgresql", "docker"} <= detected_ids

    recs = out["recommendations"]
    assert len(recs) >= 3
    for rec in recs:
        assert rec["why_relevant"]
        assert rec["problem_solved"]
        assert rec["compatible_harnesses"]
        assert "risk_score" in rec
        assert "limitations" in rec

    # Unrelated empty directory produces zero noisy keyword-spam recommendations
    empty_dir = tmp_path / "empty_proj"
    empty_dir.mkdir()
    assert main(["suggest", str(empty_dir), "--json"]) == 0
    empty_out = json.loads(capsys.readouterr().out)
    assert empty_out["detected_stack"] == []
    assert empty_out["recommendations"] == []


def test_insights_measures_token_overhead_duplicates_and_opt_in_usage_honestly(tmp_path, capsys):
    # Create an oversized skill and a compact skill + overlapping instruction files
    s_small = tmp_path / ".claude" / "skills" / "pdf-compact"
    s_small.mkdir(parents=True)
    (s_small / "SKILL.md").write_text(
        "---\n"
        "name: pdf-compact\n"
        "description: Extract tables from PDF files. Use when parsing PDFs.\n"
        "---\n\n"
        "# PDF Compact\n\nConcise workflow.\n",
        encoding="utf-8",
    )

    s_large = tmp_path / ".claude" / "skills" / "legacy-giant"
    s_large.mkdir(parents=True)
    giant_body = "# Legacy Giant\n\n" + ("Detailed reference line for legacy system.\n" * 600)
    (s_large / "SKILL.md").write_text(
        "---\n"
        "name: legacy-giant\n"
        "description: Handle legacy monolith migrations. Use when migrating legacy monoliths.\n"
        "---\n\n"
        + giant_body,
        encoding="utf-8",
    )

    (tmp_path / "CLAUDE.md").write_text("# Rules\n\n- Always run pytest before commits.\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Rules\n\n- Always run pytest before commits.\n", encoding="utf-8")

    # 1. Default insights without opt-in usage logs: reports estimated tokens honestly without inventing usage!
    assert main(["insights", str(tmp_path), "--json"]) == 0
    ins1 = json.loads(capsys.readouterr().out)
    assert ins1["usage_tracking_active"] is False
    assert ins1["total_estimated_skill_tokens"] > 5000
    assert "legacy-giant" in ins1["large_skills"]
    assert len(ins1["optimization_opportunities"]) >= 1

    # 2. Record an explicit opt-in local usage event for pdf-compact -> legacy-giant is flagged as unused
    assert main(["insights", str(tmp_path), "--record-usage", "pdf-compact", "--json"]) == 0
    capsys.readouterr()

    assert main(["insights", str(tmp_path), "--json"]) == 0
    ins2 = json.loads(capsys.readouterr().out)
    assert ins2["usage_tracking_active"] is True
    assert ins2["skills"]["pdf-compact"]["usage_count"] == 1
    assert "legacy-giant" in ins2["unused_skills"]
