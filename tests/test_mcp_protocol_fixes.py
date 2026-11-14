"""Regression tests for MCP protocol fixes: unknown-argument rejection (D9), stdio robustness (B17), ping and
tool annotations."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillporter.mcp_server import MCP_TOOLS, handle_mcp_request

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILL = "---\nname: srcskill\ndescription: Source skill. Use when testing MCP.\nlicense: MIT\n---\n\n# Skill\n"

EXPECTED_TOOLS = {
    "skillporter_diagnose",
    "skillporter_detect",
    "skillporter_scan",
    "skillporter_inspect",
    "skillporter_matrix",
    "skillporter_add",
    "skillporter_install",
    "skillporter_sync",
    "skillporter_remove",
    "skillporter_status",
    "skillporter_diff",
    "skillporter_export",
    "skillporter_import",
    "skillporter_consolidate_preview",
    "skillporter_suggest",
    "skillporter_insights",
    "skillporter_context",
    "skillporter_preview",
}
WRITE_TOOLS = {
    "skillporter_add",
    "skillporter_install",
    "skillporter_sync",
    "skillporter_remove",
    "skillporter_export",
    "skillporter_import",
}
DESTRUCTIVE = {"skillporter_remove", "skillporter_import"}


def _call(ws: Path, name: str, arguments: dict, *, allow_writes: bool = True) -> dict:
    resp = handle_mcp_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        workspace_root=ws,
        allow_writes=allow_writes,
    )
    assert resp is not None
    return resp


def _is_rejection(resp: dict) -> bool:
    if "error" in resp:
        return resp["error"]["code"] == -32602
    return bool(resp["result"]["isError"])


def _rejection_text(resp: dict) -> str:
    if "error" in resp:
        return resp["error"]["message"]
    return resp["result"]["content"][0]["text"]


# ----------------------------------------------------------------- D9


def test_add_with_unknown_dry_run_is_rejected_and_has_no_side_effects(tmp_path):
    src = tmp_path / "srcrepo" / "srcskill"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text(SKILL, encoding="utf-8")
    before = {p for p in tmp_path.rglob("*")}
    resp = _call(tmp_path, "skillporter_add", {"source": "srcrepo", "harnesses": ["windsurf"], "dry_run": True})
    assert _is_rejection(resp)
    assert "dry_run" in _rejection_text(resp)
    assert {p for p in tmp_path.rglob("*")} == before


def test_unknown_argument_rejected_before_write_permission_audit(tmp_path):
    resp = _call(tmp_path, "skillporter_remove", {"skill": "x", "bogus": 1}, allow_writes=False)
    assert _is_rejection(resp)
    assert "bogus" in _rejection_text(resp)
    assert "disabled by default" not in _rejection_text(resp)
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_every_tool_rejects_unknown_argument(tmp_path, tool):
    resp = _call(tmp_path, tool, {"definitely_not_a_param": 1})
    assert _is_rejection(resp)
    assert "definitely_not_a_param" in _rejection_text(resp)


def test_every_schema_closes_additional_properties():
    for tool in MCP_TOOLS:
        assert tool["inputSchema"]["additionalProperties"] is False, tool["name"]


def test_valid_calls_still_work(tmp_path):
    resp = _call(tmp_path, "skillporter_matrix", {})
    assert resp["result"]["isError"] is False
    resp = _call(tmp_path, "skillporter_detect", {"path": "."})
    assert resp["result"]["isError"] is False


# ----------------------------------------------------------------- ping / annotations


def test_ping_returns_empty_result(tmp_path):
    resp = handle_mcp_request({"jsonrpc": "2.0", "id": 7, "method": "ping"}, workspace_root=tmp_path)
    assert resp == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_tool_list_names_unchanged_and_annotated(tmp_path):
    resp = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, workspace_root=tmp_path)
    tools = resp["result"]["tools"]
    assert {t["name"] for t in tools} == EXPECTED_TOOLS
    assert len(tools) == 18
    for t in tools:
        ann = t["annotations"]
        if t["name"] in WRITE_TOOLS:
            assert ann["readOnlyHint"] is False, t["name"]
            assert ann["destructiveHint"] is (t["name"] in DESTRUCTIVE), t["name"]
        else:
            assert ann["readOnlyHint"] is True, t["name"]


# ----------------------------------------------------------------- B17 (real subprocess)


def _spawn(root: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "skillporter", "mcp", "--root", str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
        text=True,
    )


def _finish(proc: subprocess.Popen, payload: str) -> tuple[list[dict], str, int]:
    out, err = proc.communicate(payload, timeout=60)
    return [json.loads(x) for x in out.splitlines() if x.strip()], err, proc.returncode


PING = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "ping"}) + "\n"


def test_stdio_deeply_nested_json_gets_parse_error_and_server_survives(tmp_path):
    proc = _spawn(tmp_path)
    responses, err, rc = _finish(proc, "[" * 100000 + "\n" + PING)
    assert "Traceback" not in err and "RecursionError" not in err
    assert rc == 0
    assert responses[0]["error"]["code"] == -32700
    assert responses[1] == {"jsonrpc": "2.0", "id": 99, "result": {}}


def test_stdio_oversized_line_gets_invalid_request_and_server_survives(tmp_path):
    proc = _spawn(tmp_path)
    big = '{"jsonrpc":"2.0","id":1,"method":"x","params":{"p":"' + "a" * (8 * 1024 * 1024 + 10) + '"}}\n'
    responses, err, rc = _finish(proc, big + PING)
    assert "Traceback" not in err
    assert rc == 0
    assert responses[0]["error"]["code"] == -32600
    assert responses[1] == {"jsonrpc": "2.0", "id": 99, "result": {}}


def test_stdio_still_rejects_unknown_arg_over_real_server(tmp_path):
    proc = _spawn(tmp_path)
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "skillporter_detect", "arguments": {"nope": 1}},
    }
    responses, _, rc = _finish(proc, json.dumps(req) + "\n")
    assert rc == 0
    assert _is_rejection(responses[0])
