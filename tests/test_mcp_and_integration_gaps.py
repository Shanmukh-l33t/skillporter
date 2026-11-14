"""Comprehensive integration suite for MCP server evolution, official self-skill parity,
HTTP registry publishing, sandbox boundaries, GitHub Action execution, live agent CLIs,
and clean installation channels (Part 5 Sections 8.1-8.7 & Part 10 Section 26).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from skillporter.cli import main
from skillporter.frontmatter import parse_skill, validate
from skillporter.security import scan_skill

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_clean_skill(base: Path, name: str = "int-skill", version: str = "1.0.0") -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Integration verification skill {name}. Use when testing {name} workflows.\n"
        "license: MIT\n"
        "metadata:\n"
        f'  author: "qa-suite"\n'
        f'  version: "{version}"\n'
        "---\n\n"
        f"# {name}\n\n"
        "Execute deterministic integration steps.\n",
        encoding="utf-8",
    )
    return sdir


def test_mcp_stdio_subprocess_read_write_policy_and_new_intelligence_tools(tmp_path):
    ws = tmp_path / "mcp_ws"
    ws.mkdir()
    src = _make_clean_skill(ws / "src_skills", "alpha-mcp")
    (ws / "CLAUDE.md").write_text("# Rules\n\n- Run pytest before commits.\n", encoding="utf-8")
    (ws / "AGENTS.md").write_text("# Rules\n\n- Run pytest before commits.\n", encoding="utf-8")
    (ws / "package.json").write_text(json.dumps({"dependencies": {"next": "15.0.0"}}), encoding="utf-8")

    # 1. Start REAL `skillporter mcp` stdio subprocess in default READ-ONLY mode
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "skillporter_consolidate_preview", "arguments": {"path": "."}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "skillporter_suggest", "arguments": {"path": "."}},
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "skillporter_insights", "arguments": {"path": "."}},
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "skillporter_context", "arguments": {"harness": "codex", "path": "."}},
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "skillporter_preview",
                "arguments": {"target": "src_skills/alpha-mcp", "harness": "cursor"},
            },
        },
        # Write tool must fail closed in read-only mode
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "skillporter_install",
                "arguments": {"skill": "src_skills/alpha-mcp", "harnesses": ["claude-code"]},
            },
        },
    ]
    stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\nnot-valid-json\n"

    proc = subprocess.run(
        [sys.executable, "-m", "skillporter", "mcp", "--root", str(ws)],
        input=stdin_payload,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
    by_id = {r.get("id"): r for r in responses if r.get("id") is not None}

    tool_names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert {
        "skillporter_consolidate_preview",
        "skillporter_suggest",
        "skillporter_insights",
        "skillporter_context",
        "skillporter_preview",
    } <= tool_names

    for rid in (3, 4, 5, 6, 7):
        assert by_id[rid]["result"]["isError"] is False, by_id[rid]

    # Write denied in read-only mode
    assert by_id[8]["result"]["isError"] is True
    # Parse error returned for malformed line without crashing server
    assert any(r.get("error", {}).get("code") == -32700 for r in responses)

    # 2. Spawn `--allow-writes` MCP server and verify policy enforcement + optional-harnesses remove
    (ws / "skillporter.policy.yaml").write_text("allowed_harnesses:\n  - claude-code\n", encoding="utf-8")
    write_reqs = [
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "skillporter_install",
                "arguments": {"skill": "src_skills/alpha-mcp", "harnesses": ["windsurf"]},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "skillporter_install",
                "arguments": {"skill": "src_skills/alpha-mcp", "harnesses": ["claude-code"]},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "skillporter_remove", "arguments": {"skill": "alpha-mcp"}},
        },
    ]
    proc_w = subprocess.run(
        [sys.executable, "-m", "skillporter", "mcp", "--root", str(ws), "--allow-writes"],
        input="\n".join(json.dumps(r) for r in write_reqs) + "\n",
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc_w.returncode == 0
    w_by_id = {json.loads(ln)["id"]: json.loads(ln) for ln in proc_w.stdout.strip().splitlines() if ln.strip()}
    assert w_by_id[10]["result"]["isError"] is True  # blocked by policy allowed_harnesses!
    assert w_by_id[11]["result"]["isError"] is False
    assert w_by_id[12]["result"]["isError"] is False
    assert not (ws / ".claude" / "skills" / "alpha-mcp").exists()
    assert (src / "SKILL.md").is_file()


def test_official_self_skill_parity_and_strict_lint():
    repo_skill = REPO_ROOT / "skills" / "skillporter" / "SKILL.md"
    bundled_template = REPO_ROOT / "skillporter" / "bundled_skill" / "SKILL_TEMPLATE.md"
    assert repo_skill.read_text(encoding="utf-8") == bundled_template.read_text(encoding="utf-8")

    text = repo_skill.read_text(encoding="utf-8")
    for cmd_tok in ("consolidate", "suggest", "insights", "preview", "policy", "update --check"):
        assert cmd_tok in text, f"Official self-skill missing guidance for {cmd_tok}"

    issues = validate(parse_skill(repo_skill))
    assert issues == [], f"Official SKILL.md has spec/recommendation issues: {issues}"
    srep = scan_skill(repo_skill.parent, offline=True)
    assert srep.risk_score == 0 and srep.passed


def test_http_registry_publishing_auth_success_and_error_handling(tmp_path, monkeypatch, capsys):
    received: list[dict[str, object]] = []

    class RegistryHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            auth = self.headers.get("Authorization", "")
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if auth != "Bearer valid-reg-token":
                self.send_response(401)
                self.end_headers()
                return
            received.append(body)
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, format, *args):  # noqa: A002
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RegistryHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sdir = _make_clean_skill(tmp_path, "http-pub-skill", version="1.2.0")
        reg_url = f"http://127.0.0.1:{port}/v1/publish"

        # 1. Missing/invalid token -> 401 authentication failure (exit 1)
        monkeypatch.setenv("SKILLPORTER_REGISTRY_TOKEN", "wrong-token")
        assert main(["publish", str(sdir), "--registry", reg_url]) == 1
        assert "authentication failed" in capsys.readouterr().err.lower()

        # 2. Valid token -> 201 success and payload verified
        monkeypatch.setenv("SKILLPORTER_REGISTRY_TOKEN", "valid-reg-token")
        assert main(["publish", str(sdir), "--registry", reg_url, "--json"]) == 0
        pub_out = json.loads(capsys.readouterr().out)
        assert pub_out["published_to"] == reg_url
        assert len(received) == 1
        assert received[0]["package"]["name"] == "http-pub-skill"  # type: ignore[index]

        # 3. Unreachable port -> network failure handled cleanly
        assert main(["publish", str(sdir), "--registry", "http://127.0.0.1:1/unreachable"]) == 1
        assert "network failure" in capsys.readouterr().err.lower()
    finally:
        server.shutdown()
        server.server_close()


def test_github_action_shell_workflow_and_live_agent_binary_detection(tmp_path, capsys):
    # 1. Verify live host binary detection with `--versions` succeeds cleanly without hanging
    assert main(["detect", str(tmp_path), "--versions", "--json"]) == 0
    det_rows = json.loads(capsys.readouterr().out)
    assert isinstance(det_rows, list) and len(det_rows) == 19

    # 2. Execute GitHub Action check steps (validate + scan SARIF + lock --check + ci-report)
    ws = tmp_path / "ci_repo"
    ws.mkdir()
    src = _make_clean_skill(tmp_path / "src", "ci-verified")
    assert main(["init", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert main(["add", str(src), "--harness", "claude-code,codex,cursor", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert main(["lock", str(ws), "--json"]) == 0
    capsys.readouterr()

    sarif_file = ws / "skillporter.sarif"
    assert main(["validate", str(ws)]) == 0
    capsys.readouterr()
    assert main(["scan", str(ws), "--format", "sarif"]) == 0
    sarif_txt = capsys.readouterr().out
    sarif_file.write_text(sarif_txt, encoding="utf-8")
    sarif_obj = json.loads(sarif_txt)
    assert sarif_obj["version"] == "2.1.0"
    assert main(["lock", str(ws), "--check"]) == 0
    capsys.readouterr()
    md_report = ws / "pr-report.md"
    assert main(["ci-report", str(ws), "--output", str(md_report)]) == 0
    capsys.readouterr()
    assert "PASSED" in md_report.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="POSIX sh installer test")
def test_standalone_installer_fresh_install_upgrade_and_tamper_rejection(tmp_path):
    # Build current standalone artifacts into a temp release directory and serve over local HTTP
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_standalone.py")],
        check=True,
        capture_output=True,
    )
    pyz_src = REPO_ROOT / "dist" / "skillporter.pyz"
    sums_src = REPO_ROOT / "dist" / "SHA256SUMS.txt"
    expected_sha = hashlib.sha256(pyz_src.read_bytes()).hexdigest()

    rel_dir = tmp_path / "releases" / "v3.1.0"
    rel_dir.mkdir(parents=True)
    shutil.copy2(pyz_src, rel_dir / "skillporter.pyz")
    shutil.copy2(sums_src, rel_dir / "SHA256SUMS.txt")

    class StaticHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(tmp_path / "releases"), **kw)

        def log_message(self, format, *args):  # noqa: A002
            return

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        env_install = {
            **os.environ,
            "SKILLPORTER_RELEASE_BASE_URL": f"http://127.0.0.1:{port}",
            "SKILLPORTER_VERSION": "v3.1.0",
            "SKILLPORTER_INSTALL_DIR": str(bin_dir),
            "SKILLPORTER_SHA256": expected_sha,
        }
        p_ok = subprocess.run(
            ["sh", str(REPO_ROOT / "install.sh")],
            env=env_install,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert p_ok.returncode == 0, p_ok.stderr
        installed_bin = bin_dir / "skillporter"
        assert installed_bin.is_file()

        # Bad pinned SHA-256 fails closed without corrupting installed binary
        env_bad = {**env_install, "SKILLPORTER_SHA256": "0" * 64}
        p_bad = subprocess.run(
            ["sh", str(REPO_ROOT / "install.sh")],
            env=env_bad,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert p_bad.returncode != 0
        p_ver = subprocess.run([str(installed_bin), "--version"], capture_output=True, text=True, check=True)
        assert "3.1.0" in p_ver.stdout
    finally:
        srv.shutdown()
        srv.server_close()
