"""Zero-dependency Model Context Protocol (MCP) stdio server for Skillporter.

Allows AI agents (Claude Code, Cursor, Codex, Windsurf, Cline, Goose, Hermes, Zed)
to natively invoke Skillporter diagnostics, security scans, and synchronization
over JSON-RPC 2.0 stdio without shelling out manually.

Usage:
  skillporter mcp
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__, harnesses
from .diagnose import diagnose
from .frontmatter import parse_skill, validate
from .install import install
from .security import scan_skill
from .sources import resolve_source

MCP_TOOLS = [
    {
        "name": "skillporter_diagnose",
        "description": (
            "Diagnose Agent Skill reachability, broken symlinks, SHA-256 content drift, "
            "and spec compliance across AI agent harnesses in a repository."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository root path (default: '.')"},
                "scope": {"type": "string", "enum": ["project", "user"], "default": "project"},
            },
        },
    },
    {
        "name": "skillporter_detect",
        "description": "Detect which AI coding and autonomous agent harnesses are installed or active.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace root path (default: '.')"},
            },
        },
    },
    {
        "name": "skillporter_scan",
        "description": (
            "Run static security and supply-chain checks on a skill directory "
            "(secrets, prompt injection, dangerous shell commands, symlink escapes)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to skill directory"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "skillporter_add",
        "description": "Install a skill from a local directory, archive, or GitHub repository into target harnesses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Local path or GitHub owner/repo specifier"},
                "harnesses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target harness IDs (e.g. ['claude-code', 'codex', 'cursor'])",
                },
                "path": {"type": "string", "description": "Repository root path (default: '.')"},
                "strategy": {"type": "string", "enum": ["copy", "symlink"], "default": "copy"},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["source", "harnesses"],
        },
    },
    {
        "name": "skillporter_matrix",
        "description": "Return the full compatibility matrix of all 19 supported AI agent harnesses.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_mcp_request(req: dict[str, object]) -> dict[str, object] | None:
    """Process one JSON-RPC 2.0 request dictionary and return a response dictionary."""
    method = str(req.get("method", ""))
    req_id = req.get("id")
    params = req.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if method == "notifications/initialized" or req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "skillporter", "version": __version__},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    if method == "tools/call":
        tname = str(params.get("name", ""))
        args = params.get("arguments", {})
        if not isinstance(args, dict):
            args = {}
        try:
            payload = _call_tool(tname, args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _call_tool(name: str, args: dict[str, object]) -> dict[str, object]:
    if name == "skillporter_diagnose":
        root = Path(str(args.get("path", "."))).expanduser().resolve()
        scope = str(args.get("scope", "project"))
        diag = diagnose(root, scope=scope)
        return {
            "root": str(diag.root),
            "skills": diag.skill_names,
            "findings": diag.findings,
            "drifted": diag.drifted,
            "reachable": {h: sorted(r.reachable_skills) for h, r in diag.reports.items()},
        }

    if name == "skillporter_detect":
        root = Path(str(args.get("path", "."))).expanduser().resolve()
        detected = harnesses.detect_harnesses(root)
        return {
            "root": str(root),
            "detected": [
                {
                    "harness": d.harness.name,
                    "display_name": d.harness.label,
                    "installed": d.installed,
                    "project_active": d.project_active,
                    "user_present": d.user_present,
                    "support_status": d.harness.support_status,
                    "reasons": d.reasons,
                }
                for d in detected
                if d.installed
            ],
        }

    if name == "skillporter_scan":
        target = Path(str(args["path"])).expanduser().resolve()
        sec = scan_skill(target)
        issues = []
        if (target / "SKILL.md").is_file():
            issues = [str(i) for i in validate(parse_skill(target / "SKILL.md"))]
        res = sec.to_dict()
        res["spec_issues"] = issues
        return res

    if name == "skillporter_add":
        root = Path(str(args.get("path", "."))).expanduser().resolve()
        source_spec = str(args["source"])
        raw_targets = args.get("harnesses", ["claude-code", "codex", "cursor"])
        targets = [str(t) for t in raw_targets] if isinstance(raw_targets, list) else ["claude-code", "codex"]
        strategy = str(args.get("strategy", "copy"))
        force = bool(args.get("force", False))

        resolved = resolve_source(source_spec, base_dir=root)
        try:
            out_results = []
            for sdir in resolved.skill_dirs:
                sec = scan_skill(sdir)
                if not sec.passed and not force:
                    msg = (
                        f"security scan blocked {sdir.name}: "
                        f"{sec.critical_count} critical, {sec.high_count} high findings"
                    )
                    raise RuntimeError(msg)
                inst = install(
                    root,
                    sdir,
                    targets,
                    strategy=strategy,
                    force=force,
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    record_state=True,
                )
                for r in inst:
                    out_results.append(
                        {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                    )
            return {"installed": out_results, "resolved_commit": resolved.resolved_commit}
        finally:
            resolved.cleanup()

    if name == "skillporter_matrix":
        return {
            "harnesses": [
                {
                    "id": h.name,
                    "display_name": h.label,
                    "category": h.category,
                    "support_status": h.support_status,
                    "verification_level": h.verification_level,
                    "project_paths": [p.path for p in h.project_paths],
                    "user_paths": [p.path for p in h.user_paths],
                    "docs": h.docs,
                }
                for h in (harnesses.get(n) for n in harnesses.names())
            ]
        }

    raise ValueError(f"unknown tool: {name}")


def run_mcp_stdio() -> int:
    """Run the JSON-RPC 2.0 MCP server loop over stdin/stdout."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(req, dict):
            continue
        resp = handle_mcp_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0
