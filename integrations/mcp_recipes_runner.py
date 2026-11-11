"""Smoke test runner for LangChain, CrewAI, and AutoGen MCP integration recipes."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def run_recipe_smoke_test(tmp_path: Path) -> None:
    recipe_file = Path(__file__).resolve().parent / "mcp-recipes" / "agent_frameworks.py"
    spec = importlib.util.spec_from_file_location("agent_frameworks", recipe_file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sdir = tmp_path / ".claude" / "skills" / "mcp-demo"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(
        "---\nname: mcp-demo\ndescription: >\n  Test MCP recipe integration. Use when testing MCP.\n---\n\n# Demo\n",
        encoding="utf-8",
    )

    client = mod.SkillporterMCPClient(tmp_path)
    lc_tools = client.as_langchain_tools()
    crew_tools = client.as_crewai_tools()
    ag_map = client.as_autogen_function_map()

    assert len(lc_tools) == 3
    assert len(crew_tools) == 3
    diag_res = ag_map["skillporter_diagnose"](".")
    assert "mcp-demo" in diag_res["skills"]
    scan_res = ag_map["skillporter_scan"](".claude/skills/mcp-demo")
    assert scan_res["passed"] is True
    assert scan_res["risk_score"] == 0
