"""Zero-dependency Hardened Model Context Protocol (MCP) Server for Skillporter.

Exposes read and write skill-management operations over JSON-RPC 2.0 stdio with
strict defense-in-depth controls:
  1. Workspace boundary containment (``resolve_mcp_path``): caller-supplied paths
     and local sources can never redefine or escape the server workspace root.
  2. Read vs. write permission separation:
     - Read tools (``detect``, ``diagnose``, ``scan``, ``inspect``, ``matrix``)
       are enabled in read-only mode.
     - Write tools (``add``, ``install``, ``sync``, ``remove``) are DENIED BY
       DEFAULT unless the operator explicitly opts in via ``--allow-writes`` or
       ``SKILLPORTER_MCP_ALLOW_WRITES=1``.
  3. Strict runtime parameter validation (JSON booleans, string paths, validated
     harness IDs, safe source specifiers) independent of client schema checks.
  4. Separation of conflict override (``force``) from security risk acceptance
     (``accept_risk``); structural symlink/path escapes are never overridable.
  5. Structured, secret-scrubbed audit logging in ``.skillporter/audit.jsonl``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __version__, harnesses
from .audit import record_audit_event
from .diagnose import diagnose
from .formats import inspect_skill_dir
from .frontmatter import parse_skill, validate
from .install import install, install_many, plan_install, uninstall, validate_skill_name_segment
from .manifest import LOCKFILE_FILENAME, load_lockfile, load_manifest
from .security import compute_tree_hash, scan_skill
from .sources import resolve_source

MCP_READ_TOOLS = frozenset(
    {
        "skillporter_diagnose",
        "skillporter_detect",
        "skillporter_scan",
        "skillporter_inspect",
        "skillporter_matrix",
    }
)

MCP_WRITE_TOOLS = frozenset(
    {
        "skillporter_add",
        "skillporter_install",
        "skillporter_sync",
        "skillporter_remove",
    }
)


class MCPBoundaryError(PermissionError):
    """Raised when an MCP tool call attempts to access a path outside the workspace root."""


class MCPPermissionError(PermissionError):
    """Raised when a mutating MCP tool is invoked without explicit write permission."""


def _mcp_workspace_root(explicit_root: Path | None = None) -> Path:
    if explicit_root is not None:
        return explicit_root.resolve()
    env_root = os.environ.get("SKILLPORTER_MCP_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path.cwd().resolve()


def _is_mcp_user_scope_allowed(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get("SKILLPORTER_MCP_ALLOW_USER_SCOPE", "").strip().lower() in ("1", "true", "yes")


def _is_mcp_writes_allowed(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get("SKILLPORTER_MCP_ALLOW_WRITES", "").strip().lower() in ("1", "true", "yes")


def resolve_mcp_path(raw_path: str, *, workspace_root: Path | None = None) -> Path:
    """Resolve *raw_path* and verify it stays strictly within *workspace_root*."""
    if not isinstance(raw_path, str):
        raise MCPBoundaryError(f"MCP path must be a string, got {type(raw_path).__name__}")
    if "\x00" in raw_path:
        raise MCPBoundaryError("MCP path contains NUL byte")

    norm = raw_path.strip().replace("\\", "/")
    if raw_path.startswith("\\\\") or norm.startswith("//"):
        raise MCPBoundaryError(f"MCP UNC/network path {raw_path!r} is rejected")
    if len(norm) >= 2 and norm[0].isalpha() and norm[1] == ":" and os.name != "nt":
        raise MCPBoundaryError(f"MCP Windows drive-qualified path {raw_path!r} escapes workspace boundary")
    if norm.startswith("~"):
        raise MCPBoundaryError(f"MCP home-relative path {raw_path!r} escapes workspace boundary")

    base = _mcp_workspace_root(workspace_root)
    cand = Path(norm)
    resolved = (base / cand).resolve() if not cand.is_absolute() else cand.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise MCPBoundaryError(
            f"MCP path {raw_path!r} ({resolved}) escapes workspace boundary {base}"
        ) from exc
    return resolved


def _require_bool(args: dict[str, object], key: str, *, default: bool = False) -> bool:
    if key not in args:
        return default
    val = args[key]
    if not isinstance(val, bool):
        raise TypeError(f"MCP parameter {key!r} must be a JSON boolean, got {type(val).__name__}")
    return val


def _require_str(
    args: dict[str, object],
    key: str,
    *,
    default: str | None = None,
    allow_empty: bool = False,
) -> str:
    if key not in args:
        if default is not None:
            return default
        raise ValueError(f"missing required MCP parameter {key!r}")
    val = args[key]
    if not isinstance(val, str):
        raise TypeError(f"MCP parameter {key!r} must be a string, got {type(val).__name__}")
    if not allow_empty and not val.strip():
        raise ValueError(f"MCP parameter {key!r} must be a non-empty string")
    return val


def _require_enum(args: dict[str, object], key: str, allowed: tuple[str, ...], *, default: str) -> str:
    val = _require_str(args, key, default=default)
    if val not in allowed:
        raise ValueError(f"invalid {key!r} value {val!r}; expected one of {allowed}")
    return val


def _require_harnesses(
    args: dict[str, object],
    key: str = "harnesses",
    *,
    required: bool = True,
    root: Path | None = None,
    scope: str = "project",
) -> list[str]:
    if key not in args:
        if required:
            raise ValueError(f"missing required MCP parameter {key!r}")
        return ["claude-code", "codex", "cursor"]
    raw = args[key]
    if not isinstance(raw, list) or len(raw) == 0:
        raise TypeError(f"MCP parameter {key!r} must be a non-empty array of harness IDs")
    resolved: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise TypeError(f"every entry in {key!r} must be a non-empty string")
        tok = item.strip().lower()
        if tok == "all":
            scoped = [
                n
                for n in harnesses.names()
                if (harnesses.get(n).project_paths if scope == "project" else harnesses.get(n).user_paths)
            ]
            for s in scoped:
                if s not in resolved:
                    resolved.append(s)
        elif tok == "detected":
            det_root = root or Path.cwd().resolve()
            detected = [
                d.harness.name
                for d in harnesses.detect_harnesses(det_root)
                if d.installed and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
            ]
            for s in detected or ["claude-code", "codex", "cursor"]:
                if s not in resolved:
                    resolved.append(s)
        else:
            canonical = harnesses.get(tok).name
            if canonical not in resolved:
                resolved.append(canonical)
    return resolved


def _validate_mcp_source(source_spec: object, ws_root: Path) -> str:
    if not isinstance(source_spec, str) or not source_spec.strip():
        raise ValueError("MCP 'source' must be a non-empty string")
    spec = source_spec.strip()
    if any(ch in spec for ch in ("\x00", "\r", "\n")):
        raise MCPBoundaryError("MCP source contains control or NUL characters")
    if spec.startswith("-"):
        raise ValueError(f"invalid MCP source {spec!r}: leading '-' is forbidden")
    if any(bad in spec for bad in (";", "|", "`", "$(")):
        raise ValueError(f"invalid MCP source {spec!r}: shell metacharacters are forbidden")
    if spec.startswith("file://"):
        file_part = spec[len("file://") :]
        resolve_mcp_path(file_part, workspace_root=ws_root)
        return spec
    norm = spec.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    is_remote = spec.startswith(("https://", "http://", "git@", "github:", "registry:"))
    looks_local = (
        spec.startswith((".", "/", "\\", "~"))
        or (len(norm) >= 2 and norm[0].isalpha() and norm[1] == ":")
        or ".." in parts
        or "\\" in spec
        or (not is_remote and (ws_root / norm).exists())
    )
    if looks_local:
        resolve_mcp_path(spec, workspace_root=ws_root)
    return spec


def _enforce_write_permission(
    root: Path,
    operation: str,
    *,
    allow_writes: bool | None,
    source: str = "",
    harnesses_list: list[str] | None = None,
) -> None:
    if _is_mcp_writes_allowed(allow_writes):
        return
    record_audit_event(
        root,
        interface="mcp",
        operation=operation,
        status="denied",
        source=source,
        harnesses=harnesses_list,
        detail="MCP write operations disabled by default",
    )
    raise MCPPermissionError(
        f"MCP write operation {operation!r} is disabled by default; "
        "launch with `skillporter mcp --allow-writes` or set SKILLPORTER_MCP_ALLOW_WRITES=1 to authorize writes"
    )


def _evaluate_skills_security(
    root: Path,
    operation: str,
    skill_dirs: list[Path],
    *,
    source: str,
    resolved_commit: str,
    targets: list[str],
    force: bool,
    accept_risk: bool,
    max_risk_score: int | None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    all_findings: list[dict[str, object]] = []
    scan_summary: dict[str, object] = {}
    for sdir in skill_dirs:
        sec = scan_skill(sdir)
        scan_summary[sdir.name] = {
            "passed": sec.passed,
            "posture": sec.posture,
            "scan_complete": sec.scan_complete,
            "risk_score": sec.risk_score,
            "recommendation": sec.recommendation,
            "finding_codes": [f.code for f in sec.findings],
        }
        for f in sec.findings:
            fd = f.to_dict()
            fd["skill"] = sdir.name
            all_findings.append(fd)
        if sec.has_structural_escape:
            record_audit_event(
                root,
                interface="mcp",
                operation=operation,
                status="blocked",
                source=source,
                resolved_commit=resolved_commit,
                harnesses=targets,
                scan_results=scan_summary,
                force=force,
                risk_accepted=accept_risk,
                detail=f"structural filesystem escape in {sdir.name}",
            )
            raise RuntimeError(
                f"security scan blocked {sdir.name}: structural filesystem escape cannot be overridden"
            )
        exceeds = sec.exceeds_risk_threshold(max_risk_score)
        if (not sec.passed or exceeds) and not accept_risk:
            record_audit_event(
                root,
                interface="mcp",
                operation=operation,
                status="blocked",
                source=source,
                resolved_commit=resolved_commit,
                harnesses=targets,
                scan_results=scan_summary,
                force=force,
                risk_accepted=False,
                detail=f"security policy blocked {sdir.name} (risk {sec.risk_score}/100)",
            )
            msg = (
                f"security scan blocked {sdir.name} (risk {sec.risk_score}/100): "
                f"{sec.critical_count} critical, {sec.high_count} high findings "
                "(force does not bypass security; pass accept_risk=true only after reviewing findings)"
            )
            raise RuntimeError(msg)
    return scan_summary, all_findings


MCP_TOOLS = [
    {
        "name": "skillporter_diagnose",
        "description": (
            "[READ] Diagnose Agent Skill reachability, broken symlinks, SHA-256 content drift, "
            "and spec compliance across AI agent harnesses in the workspace."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path (default: '.')"},
                "scope": {"type": "string", "enum": ["project", "user"], "default": "project"},
            },
        },
    },
    {
        "name": "skillporter_detect",
        "description": "[READ] Detect which AI coding and autonomous agent harnesses are installed or active.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path (default: '.')"},
            },
        },
    },
    {
        "name": "skillporter_scan",
        "description": (
            "[READ] Run static security and supply-chain checks on a skill directory "
            "(secrets, prompt injection, AST/JS/encoded analysis, symlink escapes)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path to skill directory"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "skillporter_inspect",
        "description": "[READ] Inspect a workspace or remote skill package structure, metadata, and security posture.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Workspace-relative path or remote skill specifier"},
            },
            "required": ["source"],
        },
    },
    {
        "name": "skillporter_matrix",
        "description": "[READ] Return the compatibility matrix of all 19 supported AI agent harnesses.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "skillporter_add",
        "description": (
            "[WRITE] Install skills from a workspace directory, archive, or repository into target harnesses "
            "(requires SKILLPORTER_MCP_ALLOW_WRITES=1)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Workspace-relative path or GitHub owner/repo specifier"},
                "harnesses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target harness IDs (e.g. ['claude-code', 'codex', 'cursor'])",
                },
                "path": {"type": "string", "description": "Workspace-relative root path (default: '.')"},
                "strategy": {"type": "string", "enum": ["copy", "symlink"], "default": "copy"},
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Overwrite conflicting existing installations (never bypasses security findings)",
                },
                "accept_risk": {
                    "type": "boolean",
                    "default": False,
                    "description": "Explicitly accept non-structural security findings after inspection",
                },
            },
            "required": ["source", "harnesses"],
        },
    },
    {
        "name": "skillporter_install",
        "description": (
            "[WRITE] Install a local workspace skill directory into target harnesses "
            "(requires SKILLPORTER_MCP_ALLOW_WRITES=1)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "Workspace-relative path to skill directory"},
                "harnesses": {"type": "array", "items": {"type": "string"}},
                "path": {"type": "string", "default": "."},
                "strategy": {"type": "string", "enum": ["copy", "symlink"], "default": "copy"},
                "force": {"type": "boolean", "default": False},
                "accept_risk": {"type": "boolean", "default": False},
            },
            "required": ["skill", "harnesses"],
        },
    },
    {
        "name": "skillporter_sync",
        "description": (
            "[WRITE] Synchronize workspace skills across target harnesses "
            "(requires SKILLPORTER_MCP_ALLOW_WRITES=1)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "harnesses": {"type": "array", "items": {"type": "string"}},
                "strategy": {"type": "string", "enum": ["copy", "symlink"], "default": "copy"},
                "force": {"type": "boolean", "default": False},
                "accept_risk": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "skillporter_remove",
        "description": (
            "[WRITE] Remove an installed skill from target harnesses in the workspace "
            "(requires SKILLPORTER_MCP_ALLOW_WRITES=1)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "Single-segment skill name to remove"},
                "harnesses": {"type": "array", "items": {"type": "string"}},
                "path": {"type": "string", "default": "."},
            },
            "required": ["skill", "harnesses"],
        },
    },
]


def handle_mcp_request(
    req: object,
    *,
    workspace_root: Path | None = None,
    allow_writes: bool | None = None,
    allow_user_scope: bool | None = None,
) -> dict[str, object] | None:
    """Process one JSON-RPC 2.0 request and return a JSON-RPC 2.0 response dictionary."""
    if not isinstance(req, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: message must be a JSON object"},
        }

    req_id = req.get("id")
    if req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
        return {
            "jsonrpc": "2.0",
            "id": req_id if isinstance(req_id, (str, int)) else None,
            "error": {"code": -32600, "message": "Invalid Request: jsonrpc='2.0' and string 'method' required"},
        }

    method = str(req["method"])
    params = req.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": "Invalid params: 'params' must be an object"},
        }

    if method.startswith("notifications/") or req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "skillporter",
                    "version": __version__,
                    "writesEnabled": _is_mcp_writes_allowed(allow_writes),
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    if method == "tools/call":
        raw_tname = params.get("name")
        raw_args = params.get("arguments", {})
        try:
            if not isinstance(raw_tname, str) or not raw_tname.strip():
                raise ValueError("MCP tool 'name' must be a non-empty string")
            if raw_args is None:
                raw_args = {}
            if not isinstance(raw_args, dict):
                raise TypeError(f"MCP tool 'arguments' must be a JSON object, got {type(raw_args).__name__}")
            payload = _call_tool(
                raw_tname.strip(),
                raw_args,
                workspace_root=workspace_root,
                allow_writes=allow_writes,
                allow_user_scope=allow_user_scope,
            )
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


def _call_tool(
    name: str,
    args: dict[str, object],
    *,
    workspace_root: Path | None = None,
    allow_writes: bool | None = None,
    allow_user_scope: bool | None = None,
) -> dict[str, object]:
    ws_root = _mcp_workspace_root(workspace_root)

    # ------------------------- READ OPERATIONS -------------------------
    if name == "skillporter_diagnose":
        raw_p = _require_str(args, "path", default=".")
        root = resolve_mcp_path(raw_p, workspace_root=ws_root)
        scope = _require_enum(args, "scope", ("project", "user"), default="project")
        if scope == "user" and not _is_mcp_user_scope_allowed(allow_user_scope):
            raise MCPBoundaryError(
                "MCP user scope access is disabled by default; set SKILLPORTER_MCP_ALLOW_USER_SCOPE=1 to enable"
            )
        diag = diagnose(root, scope=scope)
        return {
            "operation": name,
            "root": str(diag.root),
            "skills": diag.skill_names,
            "findings": diag.findings,
            "drifted": diag.drifted,
            "reachable": {h: sorted(r.reachable_skills) for h, r in diag.reports.items()},
        }

    if name == "skillporter_detect":
        raw_p = _require_str(args, "path", default=".")
        root = resolve_mcp_path(raw_p, workspace_root=ws_root)
        detected = harnesses.detect_harnesses(root)
        return {
            "operation": name,
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
        raw_p = _require_str(args, "path")
        target = resolve_mcp_path(raw_p, workspace_root=ws_root)
        sec = scan_skill(target)
        issues = []
        if (target / "SKILL.md").is_file():
            issues = [str(i) for i in validate(parse_skill(target / "SKILL.md"))]
        res = sec.to_dict()
        res["operation"] = name
        res["spec_issues"] = issues
        return res

    if name == "skillporter_inspect":
        if "source" not in args:
            raise ValueError("missing required MCP parameter 'source'")
        source_spec = _validate_mcp_source(args["source"], ws_root)
        resolved = resolve_source(source_spec, base_dir=ws_root)
        try:
            items = []
            for sdir in resolved.skill_dirs:
                pkg = inspect_skill_dir(sdir)
                doc = pkg.skill_doc or parse_skill(sdir / "SKILL.md")
                sec = scan_skill(sdir)
                items.append(
                    {
                        "name": doc.name or sdir.name,
                        "description": doc.description,
                        "formats": pkg.detected_formats,
                        "scripts": pkg.scripts,
                        "references": pkg.references,
                        "risk_score": sec.risk_score,
                        "posture": sec.posture,
                        "recommendation": sec.recommendation,
                        "tree_hash": sec.tree_hash,
                    }
                )
            return {
                "operation": name,
                "source": resolved.canonical_source,
                "kind": resolved.kind,
                "resolved_commit": resolved.resolved_commit,
                "skills": items,
            }
        finally:
            resolved.cleanup()

    if name == "skillporter_matrix":
        return {
            "operation": name,
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
            ],
        }

    # ------------------------- WRITE OPERATIONS -------------------------
    if name == "skillporter_add":
        raw_p = _require_str(args, "path", default=".")
        root = resolve_mcp_path(raw_p, workspace_root=ws_root)
        if "source" not in args:
            raise ValueError("missing required MCP parameter 'source'")
        source_spec = _validate_mcp_source(args["source"], ws_root)
        targets = _require_harnesses(args, "harnesses", required=True, root=root, scope="project")
        strategy = _require_enum(args, "strategy", ("copy", "symlink"), default="copy")
        force = _require_bool(args, "force", default=False)
        accept_risk = _require_bool(args, "accept_risk", default=False)
        _enforce_write_permission(
            root, name, allow_writes=allow_writes, source=source_spec, harnesses_list=targets
        )

        manifest = load_manifest(root)
        max_risk_score = manifest.max_risk_score if manifest is not None else None

        try:
            resolved = resolve_source(source_spec, base_dir=root)
        except Exception as exc:
            record_audit_event(
                root,
                interface="mcp",
                operation=name,
                status="failed",
                source=source_spec,
                harnesses=targets,
                force=force,
                risk_accepted=accept_risk,
                detail=str(exc),
            )
            raise

        try:
            scan_summary, all_findings = _evaluate_skills_security(
                root,
                name,
                resolved.skill_dirs,
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                targets=targets,
                force=force,
                accept_risk=accept_risk,
                max_risk_score=max_risk_score,
            )
            plan = plan_install(root, resolved.skill_dirs, targets, strategy=strategy, force=force)
            try:
                inst = install_many(
                    root,
                    resolved.skill_dirs,
                    targets,
                    strategy=strategy,
                    force=force,
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    record_state=True,
                )
            except Exception as exc:
                record_audit_event(
                    root,
                    interface="mcp",
                    operation=name,
                    status="failed",
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    harnesses=targets,
                    scan_results=scan_summary,
                    overwrite=force,
                    force=force,
                    risk_accepted=accept_risk,
                    detail=str(exc),
                )
                raise
            out_results = [
                {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                for r in inst
            ]
            record_audit_event(
                root,
                interface="mcp",
                operation=name,
                status="succeeded",
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                destinations=[str(r.dest) for r in inst],
                harnesses=targets,
                scan_results=scan_summary,
                overwrite=force,
                force=force,
                risk_accepted=accept_risk,
            )
            return {
                "operation": name,
                "source": resolved.canonical_source,
                "resolved_commit": resolved.resolved_commit,
                "harnesses": targets,
                "planned_destinations": len(plan.destinations),
                "installed": out_results,
                "conflict_override": force,
                "risk_accepted": accept_risk,
                "security_findings": all_findings,
            }
        finally:
            resolved.cleanup()

    if name == "skillporter_install":
        raw_p = _require_str(args, "path", default=".")
        root = resolve_mcp_path(raw_p, workspace_root=ws_root)
        raw_skill = _require_str(args, "skill")
        skill_dir = resolve_mcp_path(raw_skill, workspace_root=ws_root)
        targets = _require_harnesses(args, "harnesses", required=True, root=root, scope="project")
        strategy = _require_enum(args, "strategy", ("copy", "symlink"), default="copy")
        force = _require_bool(args, "force", default=False)
        accept_risk = _require_bool(args, "accept_risk", default=False)
        _enforce_write_permission(
            root, name, allow_writes=allow_writes, source=str(skill_dir), harnesses_list=targets
        )

        manifest = load_manifest(root)
        max_risk_score = manifest.max_risk_score if manifest is not None else None
        scan_summary, all_findings = _evaluate_skills_security(
            root,
            name,
            [skill_dir],
            source=str(skill_dir),
            resolved_commit="",
            targets=targets,
            force=force,
            accept_risk=accept_risk,
            max_risk_score=max_risk_score,
        )
        try:
            inst = install(
                root,
                skill_dir,
                targets,
                strategy=strategy,
                force=force,
                source=str(skill_dir),
                record_state=True,
            )
        except Exception as exc:
            record_audit_event(
                root,
                interface="mcp",
                operation=name,
                status="failed",
                source=str(skill_dir),
                harnesses=targets,
                scan_results=scan_summary,
                overwrite=force,
                force=force,
                risk_accepted=accept_risk,
                detail=str(exc),
            )
            raise
        record_audit_event(
            root,
            interface="mcp",
            operation=name,
            status="succeeded",
            source=str(skill_dir),
            destinations=[str(r.dest) for r in inst],
            harnesses=targets,
            scan_results=scan_summary,
            overwrite=force,
            force=force,
            risk_accepted=accept_risk,
        )
        return {
            "operation": name,
            "source": str(skill_dir),
            "harnesses": targets,
            "installed": [
                {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                for r in inst
            ],
            "conflict_override": force,
            "risk_accepted": accept_risk,
            "security_findings": all_findings,
        }

    if name == "skillporter_sync":
        raw_p = _require_str(args, "path", default=".")
        root = resolve_mcp_path(raw_p, workspace_root=ws_root)
        targets = _require_harnesses(args, "harnesses", required=False, root=root, scope="project")
        strategy = _require_enum(args, "strategy", ("copy", "symlink"), default="copy")
        force = _require_bool(args, "force", default=False)
        accept_risk = _require_bool(args, "accept_risk", default=False)
        _enforce_write_permission(root, name, allow_writes=allow_writes, source=str(root), harnesses_list=targets)

        diag = diagnose(root, scope="project")
        if diag.drifted and not force:
            raise RuntimeError("content drift detected across copies; pass force=true to synchronize")
        if (root / LOCKFILE_FILENAME).is_file() and not force:
            lock = load_lockfile(root, warn_migration=False)
            for sname, locked in lock.skills.items():
                for cdir in diag.skill_copies.get(sname, []):
                    actual_hash, _ = compute_tree_hash(cdir)
                    if locked.tree_hash and actual_hash != locked.tree_hash:
                        raise RuntimeError(f"on-disk {sname!r} differs from skillporter.lock; pass force=true")

        manifest = load_manifest(root)
        max_risk_score = manifest.max_risk_score if manifest is not None else None
        canonical_dirs = [copies[0] for _s, copies in sorted(diag.skill_copies.items()) if copies]
        scan_summary, all_findings = _evaluate_skills_security(
            root,
            name,
            canonical_dirs,
            source=str(root),
            resolved_commit="",
            targets=targets,
            force=force,
            accept_risk=accept_risk,
            max_risk_score=max_risk_score,
        )
        synced = []
        for sdir in canonical_dirs:
            synced.extend(
                install(root, sdir, targets, strategy=strategy, force=True, source=str(sdir), record_state=True)
            )
        record_audit_event(
            root,
            interface="mcp",
            operation=name,
            status="succeeded",
            source=str(root),
            destinations=[str(r.dest) for r in synced],
            harnesses=targets,
            scan_results=scan_summary,
            overwrite=True,
            force=force,
            risk_accepted=accept_risk,
        )
        return {
            "operation": name,
            "root": str(root),
            "harnesses": targets,
            "synchronized": [
                {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                for r in synced
            ],
            "conflict_override": force,
            "risk_accepted": accept_risk,
            "security_findings": all_findings,
        }

    if name == "skillporter_remove":
        raw_p = _require_str(args, "path", default=".")
        root = resolve_mcp_path(raw_p, workspace_root=ws_root)
        raw_skill_name = _require_str(args, "skill")
        skill_name = validate_skill_name_segment(raw_skill_name)
        targets = _require_harnesses(args, "harnesses", required=True, root=root, scope="project")
        _enforce_write_permission(root, name, allow_writes=allow_writes, source=skill_name, harnesses_list=targets)

        removed = uninstall(root, skill_name, targets, scope="project", record_state=True)
        record_audit_event(
            root,
            interface="mcp",
            operation=name,
            status="succeeded",
            source=skill_name,
            destinations=[str(r.dest) for r in removed if r.action == "removed"],
            harnesses=targets,
        )
        return {
            "operation": name,
            "skill": skill_name,
            "harnesses": targets,
            "results": [
                {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                for r in removed
            ],
        }

    raise ValueError(f"unknown tool: {name}")


def run_mcp_stdio(
    *,
    workspace_root: Path | None = None,
    allow_writes: bool | None = None,
    allow_user_scope: bool | None = None,
) -> int:
    """Run the JSON-RPC 2.0 MCP server loop over stdin/stdout."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc.msg}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_mcp_request(
            req,
            workspace_root=workspace_root,
            allow_writes=allow_writes,
            allow_user_scope=allow_user_scope,
        )
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0
