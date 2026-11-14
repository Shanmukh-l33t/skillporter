"""Copy-paste runnable MCP integration recipes for LangChain, CrewAI, and AutoGen.

Allows multi-agent Python frameworks to autonomously query, diagnose, scan, and
install Agent Skills from the Skillporter registry via `skillporter mcp` (JSON-RPC 2.0).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skillporter.mcp_server import handle_mcp_request


class SkillporterMCPClient:
    """In-process or stdio MCP client bridge for LangChain, CrewAI, and AutoGen agents."""

    def __init__(self, workspace_root: str | Path = ".", *, allow_writes: bool = False) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.allow_writes = allow_writes
        self._req_id = 0

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._req_id += 1
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": self._req_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments or {}},
            },
            workspace_root=self.workspace_root,
            allow_writes=True if self.allow_writes else None,
        )
        if not resp or "result" not in resp:
            raise RuntimeError(f"MCP call failed: {resp}")
        result = resp["result"]  # type: ignore[index]
        content = result.get("content", [])  # type: ignore[union-attr]
        text = content[0].get("text", "{}") if content else "{}"
        if result.get("isError"):  # type: ignore[union-attr]
            raise RuntimeError(text)
        import json

        return json.loads(text)

    def as_langchain_tools(self) -> list[dict[str, Any]]:
        """Return LangChain StructuredTool-compatible descriptors bound to this workspace."""
        return [
            {
                "name": "skillporter_diagnose",
                "description": "Diagnose skill reachability, broken symlinks, and SHA-256 content drift.",
                "func": lambda path=".": self.call_tool("skillporter_diagnose", {"path": path}),
            },
            {
                "name": "skillporter_scan",
                "description": "Scan a skill directory and return its 0-100 security risk score.",
                "func": lambda path=".": self.call_tool("skillporter_scan", {"path": path}),
            },
            {
                "name": "skillporter_add",
                "description": "Install a skill from the registry or local path across agent harnesses.",
                "func": lambda source, harnesses=None: self.call_tool(
                    "skillporter_add",
                    {"source": source, "harnesses": harnesses or ["claude-code", "codex", "cursor"]},
                ),
            },
        ]

    def as_crewai_tools(self) -> list[dict[str, Any]]:
        """Return CrewAI tool definitions for autonomous skill discovery and installation."""
        return self.as_langchain_tools()

    def as_autogen_function_map(self) -> dict[str, Any]:
        """Return an AutoGen `function_map` dictionary for ConversableAgent / AssistantAgent."""
        return {
            "skillporter_diagnose": lambda path=".": self.call_tool("skillporter_diagnose", {"path": path}),
            "skillporter_scan": lambda path=".": self.call_tool("skillporter_scan", {"path": path}),
            "skillporter_add": lambda source, harnesses=None: self.call_tool(
                "skillporter_add",
                {"source": source, "harnesses": harnesses or ["claude-code", "codex", "cursor"]},
            ),
            "skillporter_matrix": lambda: self.call_tool("skillporter_matrix", {}),
        }
