"""MCP Server Hardening & Adversarial Regression Suite (P1 Section 6).

Tests:
  1. Read vs. write permission separation (default-deny for add, install, sync, remove)
  2. Read operations (detect, diagnose, scan, inspect, matrix) allowed in read-only mode
  3. Explicit write opt-in via allow_writes=True or SKILLPORTER_MCP_ALLOW_WRITES=1
  4. Prompt-injected tool arguments rejected safely
  5. Failed security scan, failed multi-skill installation, and transactional rollback via MCP
  6. Structured audit logging without leaking tokens, URL credentials, or private keys
  7. Repeated calls & conflict detection
  8. Malformed JSON-RPC messages over stdio (-32700 Parse error, -32600 Invalid Request)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from skillporter.install import InstallError
from skillporter.mcp_server import handle_mcp_request, run_mcp_stdio

CLEAN_SKILL = """---
name: mcp-clean
description: >
  Clean skill package for MCP hardening tests.
  Use when testing MCP server operations.
license: MIT
---

# MCP Clean Skill

Step 1. Verify workspace.
"""


def _write_skill(base: Path, name: str = "mcp-clean", text: str = CLEAN_SKILL) -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(text.replace("name: mcp-clean", f"name: {name}"), encoding="utf-8")
    return sdir


def test_mcp_default_deny_blocks_all_write_tools_while_allowing_read_tools(tmp_path, monkeypatch):
    monkeypatch.delenv("SKILLPORTER_MCP_ALLOW_WRITES", raising=False)
    ws = tmp_path / "ws"
    _write_skill(ws / "authoring", "mcp-clean")

    # 1. Read operations succeed in default read-only mode
    for idx, (tool_name, args) in enumerate(
        [
            ("skillporter_detect", {"path": "."}),
            ("skillporter_diagnose", {"path": "."}),
            ("skillporter_scan", {"path": "authoring/mcp-clean"}),
            ("skillporter_inspect", {"source": "authoring/mcp-clean"}),
            ("skillporter_matrix", {}),
        ],
        start=1,
    ):
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": idx,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": args},
            },
            workspace_root=ws,
        )
        assert resp is not None
        assert resp["result"]["isError"] is False, f"Read tool {tool_name} failed: {resp}"

    # 2. Write operations are DENIED by default and recorded as denied in audit.jsonl
    for idx, (write_tool, args) in enumerate(
        [
            ("skillporter_add", {"source": "authoring/mcp-clean", "harnesses": ["claude-code"]}),
            ("skillporter_install", {"skill": "authoring/mcp-clean", "harnesses": ["claude-code"]}),
            ("skillporter_sync", {"path": ".", "harnesses": ["claude-code"]}),
            ("skillporter_remove", {"skill": "mcp-clean", "harnesses": ["claude-code"]}),
        ],
        start=10,
    ):
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": idx,
                "method": "tools/call",
                "params": {"name": write_tool, "arguments": args},
            },
            workspace_root=ws,
        )
        assert resp is not None
        assert resp["result"]["isError"] is True, f"Write tool {write_tool} should be denied by default"
        err_msg = resp["result"]["content"][0]["text"]
        assert "SKILLPORTER_MCP_ALLOW_WRITES" in err_msg or "write" in err_msg.lower()

    assert not (ws / ".claude" / "skills" / "mcp-clean").exists()
    audit_path = ws / ".skillporter" / "audit.jsonl"
    assert audit_path.is_file()
    events = [json.loads(ln) for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert any(ev["status"] == "denied" and ev["operation"] == "skillporter_add" for ev in events)


def test_mcp_write_lifecycle_opt_in_install_sync_remove_and_repeated_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLPORTER_MCP_ALLOW_WRITES", "1")
    ws = tmp_path / "ws"
    _write_skill(ws / "authoring", "mcp-clean")

    # 1. Install into claude-code
    r_inst = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "skillporter_install",
                "arguments": {"skill": "authoring/mcp-clean", "harnesses": ["claude-code"]},
            },
        },
        workspace_root=ws,
    )
    assert r_inst is not None
    assert r_inst["result"]["isError"] is False
    inst_data = json.loads(r_inst["result"]["content"][0]["text"])
    assert inst_data["operation"] == "skillporter_install"
    assert (ws / ".claude" / "skills" / "mcp-clean" / "SKILL.md").is_file()

    # 2. Repeated call without force=True fails cleanly on conflict
    r_dup = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "skillporter_install",
                "arguments": {"skill": "authoring/mcp-clean", "harnesses": ["claude-code"]},
            },
        },
        workspace_root=ws,
    )
    assert r_dup is not None
    assert r_dup["result"]["isError"] is True

    # 3. Sync across codex as well
    r_sync = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "skillporter_sync",
                "arguments": {"path": ".", "harnesses": ["claude-code", "codex"]},
            },
        },
        workspace_root=ws,
    )
    assert r_sync is not None
    assert r_sync["result"]["isError"] is False
    assert (ws / ".agents" / "skills" / "mcp-clean" / "SKILL.md").is_file()

    # 4. Remove from claude-code
    r_rem = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "skillporter_remove",
                "arguments": {"skill": "mcp-clean", "harnesses": ["claude-code"]},
            },
        },
        workspace_root=ws,
    )
    assert r_rem is not None
    assert r_rem["result"]["isError"] is False
    assert not (ws / ".claude" / "skills" / "mcp-clean").exists()


def test_mcp_prompt_injected_arguments_and_rollback_on_failed_install(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _write_skill(ws / "authoring", "alpha-skill")
    _write_skill(ws / "authoring", "beta-skill")

    # 1. Prompt-injected arguments (shell metacharacters, traversal in skill name, newline injection)
    injected_calls = [
        ("skillporter_remove", {"skill": "../../authoring", "harnesses": ["codex"]}),
        ("skillporter_add", {"source": "owner/repo\n--upload-pack=id", "harnesses": ["codex"]}),
        ("skillporter_add", {"source": "-oProxyCommand=id", "harnesses": ["codex"]}),
    ]
    for tool_name, bad_args in injected_calls:
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 50,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": bad_args},
            },
            workspace_root=ws,
            allow_writes=True,
        )
        assert resp is not None
        assert resp["result"]["isError"] is True
    assert (ws / "authoring" / "alpha-skill" / "SKILL.md").is_file()

    # 2. Failed multi-skill installation rolls back cleanly via MCP and logs failure
    import skillporter.install as inst_mod

    real_install = inst_mod.install
    count = [0]

    def fail_second(root, skill_dir, targets, **kw):
        count[0] += 1
        if count[0] == 2:
            raise InstallError("simulated disk write failure mid-MCP-install")
        return real_install(root, skill_dir, targets, **kw)

    monkeypatch.setattr(inst_mod, "install", fail_second)
    resp_fail = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "skillporter_add",
                "arguments": {"source": "authoring", "harnesses": ["claude-code"]},
            },
        },
        workspace_root=ws,
        allow_writes=True,
    )
    assert resp_fail is not None
    assert resp_fail["result"]["isError"] is True
    assert not (ws / ".claude" / "skills" / "alpha-skill").exists()


def test_mcp_audit_log_never_records_tokens_or_private_key_material(tmp_path):
    ws = tmp_path / "ws"
    pem_header = "-----BEGIN " + "RSA PRIVATE KEY-----"
    pem_footer = "-----END " + "RSA PRIVATE KEY-----"
    pem_body = "SYNTHETIC_PEM_FIXTURE_" + ("Q" * 32)
    _write_skill(
        ws / "authoring",
        "key-skill",
        text=CLEAN_SKILL + f"\n{pem_header}\n{pem_body}\n{pem_footer}\n",
    )

    # Blocked key-skill install AND failed credentialed git URL
    handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 60,
            "method": "tools/call",
            "params": {
                "name": "skillporter_add",
                "arguments": {"source": "authoring/key-skill", "harnesses": ["codex"]},
            },
        },
        workspace_root=ws,
        allow_writes=True,
    )
    fake_pat = "ghp_" + ("A" * 36)
    handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 61,
            "method": "tools/call",
            "params": {
                "name": "skillporter_add",
                "arguments": {
                    "source": f"https://{fake_pat}@127.0.0.1:1/nonexistent/repo.git",
                    "harnesses": ["codex"],
                },
            },
        },
        workspace_root=ws,
        allow_writes=True,
    )

    audit_raw = (ws / ".skillporter" / "audit.jsonl").read_text(encoding="utf-8")
    assert pem_body not in audit_raw
    assert fake_pat not in audit_raw


def test_mcp_stdio_handles_malformed_jsonrpc_messages_cleanly(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    lines = [
        "{not valid json",
        "[]",
        json.dumps({"jsonrpc": "1.0", "id": 7, "method": "initialize"}),
        json.dumps({"jsonrpc": "2.0", "id": 8, "method": "initialize"}),
    ]
    fake_in = io.StringIO("\n".join(lines) + "\n")
    fake_out = io.StringIO()
    monkeypatch.setattr("sys.stdin", fake_in)
    monkeypatch.setattr("sys.stdout", fake_out)

    rc = run_mcp_stdio(workspace_root=ws)
    assert rc == 0
    responses = [json.loads(ln) for ln in fake_out.getvalue().splitlines() if ln.strip()]
    codes = [r.get("error", {}).get("code") for r in responses if "error" in r]
    assert -32700 in codes  # Parse error on malformed JSON
    assert -32600 in codes  # Invalid Request on non-object or wrong jsonrpc version
    assert any(r.get("id") == 8 and "result" in r for r in responses)
