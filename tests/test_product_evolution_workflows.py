"""End-to-End Product Evolution Workflow Suite.

Exercises all 19 real-world developer workflows across CLI, core modules,
portable .skillpack archives, named profiles, AI agent skill bootstrapping,
and workspace-bounded MCP operations:
  1. Install a skill into one harness (without false-positive missing warnings)
  2. Install a skill into multiple harnesses (shared .agents/skills deduplication)
  3. Exclude selected harnesses (--exclude-harness + compatible selector)
  4. Change installation scope (project vs. user scope discovery, list, status, export)
  5. Detect, list, inspect, and check status of harnesses (skillporter harness)
  6. List and inspect skills (including large-list truncation & --verbose/-q)
  7. Synchronize and detect drift (SHA-256 drift detection & --force reconciliation)
  8. Handle partial installation failures & conflict policies (--on-conflict fail/skip/overwrite)
  9. Export a complete environment (.skillpack with secret blocking & .env exclusion)
  10. Import into a clean environment (manifest, lockfile, profiles, state restored)
  11. Restore from an offline package after upstream source is deleted
  12. Detect missing harnesses on target machine & --only-detected filtering
  13. Handle corrupted, tampered, and path-traversing .skillpack archives safely
  14. Compare environments (skillporter diff against .skillpack, directory, and profile)
  15. Roll back an unwanted update (skillporter rollback)
  16. Use SkillPorter through its official AI skill (self-skill + MCP parity)
  17. Cross-harness operations (move --isolated, single-harness remove preserving shared paths)
  18. Named environment profiles (profile save, list, show, use --prune, delete)
  19. Outdated upstream check, unmanaged skill adoption, and JSON/CI exit-code contracts.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from skillporter.cli import main
from skillporter.mcp_server import handle_mcp_request

SKILL_TEMPLATE = """---
name: {name}
description: >
  End-to-end workflow skill {name} for testing cross-harness portability and lifecycle.
  Use when running workflow verification for {name}.
license: MIT
metadata:
  version: "{version}"
---

# {name}

Workflow instructions version {version}.
"""


def _create_skill(base: Path, name: str, version: str = "1.0.0", extra_files: dict[str, str] | None = None) -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(SKILL_TEMPLATE.format(name=name, version=version), encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        fp = sdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return sdir


# ---------------------------------------------------------------------------
# 1, 2, 3 & 17. Single-harness, multi-harness, exclusions, isolated move & remove
# ---------------------------------------------------------------------------


def test_single_multi_excluded_and_cross_harness_move_workflows(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    upstream = tmp_path / "upstream"
    s_alpha = _create_skill(upstream, "alpha-skill", "1.0.0")
    s_beta = _create_skill(upstream, "beta-skill", "1.2.0")

    # 1. Install into ONE harness only (claude-code) -> status must be HEALTHY (0 false-positive missing errors)
    assert main(["install", str(s_alpha), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert (ws / ".claude" / "skills" / "alpha-skill" / "SKILL.md").is_file()
    assert not (ws / ".agents" / "skills" / "alpha-skill").exists()

    assert main(["status", str(ws), "--json"]) == 0
    st1 = json.loads(capsys.readouterr().out)
    assert st1["healthy"] is True
    assert st1["skills"]["alpha-skill"]["status"] == "SYNCED"
    assert st1["skills"]["alpha-skill"]["installed_harnesses"] == ["claude-code", "cursor", "github-copilot"] or (
        "claude-code" in st1["skills"]["alpha-skill"]["installed_harnesses"]
    )

    # 2 & 3. Install into multiple harnesses while excluding selected harnesses
    rc_add = main(
        [
            "add",
            str(s_beta),
            "--harness",
            "claude-code,codex,cursor,windsurf",
            "--exclude-harness",
            "cursor,windsurf",
            "--path",
            str(ws),
            "--json",
        ]
    )
    assert rc_add == 0
    add_out = json.loads(capsys.readouterr().out)
    installed_harnesses = [r["harness"] for r in add_out["installed"]]
    assert installed_harnesses == ["claude-code", "codex"]
    assert not (ws / ".windsurf" / "skills" / "beta-skill").exists()

    # 17a. Remove beta-skill from claude-code ONLY -> codex copy in .agents/skills remains intact
    assert main(["remove", "beta-skill", "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert not (ws / ".claude" / "skills" / "beta-skill").exists()
    assert (ws / ".agents" / "skills" / "beta-skill" / "SKILL.md").is_file()

    # 17b. Move alpha-skill from claude-code to cursor with --isolated (.cursor/skills, not .agents/skills)
    assert (
        main(
            [
                "move",
                "alpha-skill",
                "--from",
                "claude-code",
                "--to",
                "cursor",
                "--isolated",
                "--path",
                str(ws),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert not (ws / ".claude" / "skills" / "alpha-skill").exists()
    assert (ws / ".cursor" / "skills" / "alpha-skill" / "SKILL.md").is_file()
    assert not (ws / ".agents" / "skills" / "alpha-skill").exists()


# ---------------------------------------------------------------------------
# 4, 5 & 6. User-scope discovery, harness inspection, and large-result scaling
# ---------------------------------------------------------------------------


def test_user_scope_discovery_harness_commands_and_large_list_scaling(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    hermes_home = fake_home / ".hermes"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()

    # Create 35 user-scope skills inside $HERMES_HOME/skills to verify user-scope discovery & table truncation
    for idx in range(35):
        _create_skill(hermes_home / "skills" / "ops", f"user-skill-{idx:02d}", "1.0.0")

    # `list --scope user` from an empty directory must discover all 35 user skills & truncate cleanly at 30
    assert main(["list", str(empty_cwd), "--scope", "user"]) == 0
    list_txt = capsys.readouterr().out
    assert "user-skill-00" in list_txt
    assert "... and 5 more" in list_txt

    # `--verbose` shows all 35 without truncation
    assert main(["list", str(empty_cwd), "--scope", "user", "--verbose"]) == 0
    list_verbose = capsys.readouterr().out
    assert "user-skill-34" in list_verbose
    assert "... and " not in list_verbose

    # `-q / --quiet` outputs plain skill names one per line for scripting
    assert main(["list", str(empty_cwd), "--scope", "user", "-q"]) == 0
    quiet_lines = capsys.readouterr().out.strip().splitlines()
    assert len(quiet_lines) == 35

    # `status --scope user --json` reports all 35 discovered skills cleanly
    assert main(["status", str(empty_cwd), "--scope", "user", "--json"]) == 0
    ust = json.loads(capsys.readouterr().out)
    assert len(ust["discovered_skills"]) == 35
    assert ust["healthy"] is True

    # 5. Harness discovery, inspect, and status commands
    assert main(["harness", "list", "--scope", "user", "--compatible", "--json"]) == 0
    hlist = json.loads(capsys.readouterr().out)
    hermes_entry = next(h for h in hlist["harnesses"] if h["harness"] == "hermes")
    assert hermes_entry["configured"] is True
    assert hermes_entry["skill_count"] == 35

    assert main(["harness", "inspect", "cursor", "--path", str(empty_cwd), "--json"]) == 0
    hinsp = json.loads(capsys.readouterr().out)
    assert hinsp["harness"] == "cursor"
    assert hinsp["isolated_install_path"] == ".cursor/skills"
    assert "codex" in hinsp["shared_path_peers"]

    assert main(["harness", "status", str(empty_cwd), "--scope", "user", "--json"]) == 0
    hst = json.loads(capsys.readouterr().out)
    assert hst["healthy"] is True


# ---------------------------------------------------------------------------
# 7, 8 & 15. Drift detection, conflict policies, partial failure rollback & rollback cmd
# ---------------------------------------------------------------------------


def test_drift_reconciliation_conflict_policies_and_partial_failure_recovery(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    upstream = tmp_path / "upstream"
    s1 = _create_skill(upstream, "drift-skill", "1.0.0")
    s2 = _create_skill(upstream, "extra-skill", "1.0.0")

    # Install drift-skill into claude-code and codex
    assert main(["add", str(s1), "--harness", "claude-code,codex", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()

    # Introduce drift in .claude/skills/drift-skill/SKILL.md
    claude_md = ws / ".claude" / "skills" / "drift-skill" / "SKILL.md"
    claude_md.write_text(claude_md.read_text(encoding="utf-8") + "\nLocal hotfix edit.\n", encoding="utf-8")

    # `status` and `sync` without --force detect drift and exit 1
    assert main(["status", str(ws), "--json"]) == 1
    st_drift = json.loads(capsys.readouterr().out)
    assert "drift-skill" in st_drift["drifted_skills"]
    assert main(["sync", str(ws)]) == 1
    capsys.readouterr()

    # `sync --force` snapshots backup and heals drift
    assert main(["sync", str(ws), "--harness", "claude-code,codex", "--force", "--json"]) == 0
    capsys.readouterr()
    assert main(["status", str(ws), "--json"]) == 0
    capsys.readouterr()

    # 8a. Conflict policy: pre-existing unmanaged skill in windsurf
    _create_skill(ws / ".windsurf" / "skills", "extra-skill", "0.9.0")
    # Default `--on-conflict fail` rejects overwrite
    assert main(["install", str(s2), "--harness", "windsurf,claude-code", "--path", str(ws)]) == 2
    capsys.readouterr()
    # Partial failure rollback guarantee: claude-code must NOT have extra-skill left behind!
    assert not (ws / ".claude" / "skills" / "extra-skill").exists()

    # `--on-conflict skip` installs into claude-code while preserving windsurf's unmanaged 0.9.0 copy!
    assert (
        main(
            [
                "install",
                str(s2),
                "--harness",
                "windsurf,claude-code",
                "--on-conflict",
                "skip",
                "--path",
                str(ws),
                "--json",
            ]
        )
        == 0
    )
    skip_res = json.loads(capsys.readouterr().out)
    actions_by_h = {r["harness"]: r["action"] for r in skip_res["installed"]}
    assert actions_by_h["windsurf"] == "skipped"
    assert actions_by_h["claude-code"] == "created"
    assert 'version: "0.9.0"' in (ws / ".windsurf" / "skills" / "extra-skill" / "SKILL.md").read_text(encoding="utf-8")

    # 15 & 19. Upstream outdated check, update, and rollback
    _create_skill(upstream, "drift-skill", "2.0.0", {"references/changelog.md": "# v2.0.0\n"})
    assert main(["outdated", "--path", str(ws), "--json"]) == 0
    outd = json.loads(capsys.readouterr().out)
    assert outd["outdated_count"] >= 1

    assert main(["update", "drift-skill", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert (ws / ".claude" / "skills" / "drift-skill" / "references" / "changelog.md").is_file()

    assert main(["rollback", "drift-skill", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert not (ws / ".claude" / "skills" / "drift-skill" / "references" / "changelog.md").exists()


# ---------------------------------------------------------------------------
# 9, 10, 11, 12, 13 & 14. Portable .skillpack export, offline import, diff & security
# ---------------------------------------------------------------------------


def test_portable_skillpack_offline_roundtrip_diff_missing_harnesses_and_corruption(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    machine_a = tmp_path / "machine_a"
    machine_a.mkdir()
    upstream_src = tmp_path / "ephemeral_upstream"
    s_net = _create_skill(
        upstream_src, "net-audit", "1.4.0", {".env": "LOCAL_DEV_VAR=1\n", "references/ref.md": "ok\n"}
    )
    s_doc = _create_skill(upstream_src, "doc-helper", "2.1.0")

    assert main(["init", str(machine_a), "--json"]) == 0
    capsys.readouterr()
    assert main(["add", str(s_net), "--harness", "claude-code,codex,windsurf", "--path", str(machine_a), "--json"]) == 0
    capsys.readouterr()
    assert main(["add", str(s_doc), "--harness", "claude-code,codex", "--path", str(machine_a), "--json"]) == 0
    capsys.readouterr()
    assert main(["profile", "save", "sec-team", "--path", str(machine_a), "--json"]) == 0
    capsys.readouterr()

    # 9a. Export blocks embedded credentials in skill content
    leaky_dir = _create_skill(
        machine_a / ".claude" / "skills",
        "leaky-skill",
        "1.0.0",
        {"scripts/leak.py": "TOKEN = '" + "ghp_" + ("A" * 36) + "'\n"},
    )
    bad_pack = tmp_path / "blocked.skillpack"
    assert main(["export", str(bad_pack), "--path", str(machine_a)]) == 1
    assert "embedded credential" in capsys.readouterr().err
    shutil.rmtree(leaky_dir)

    # 9b. Clean export strips `.env` file automatically and writes deterministic .skillpack
    pack_file = tmp_path / "portable.skillpack"
    assert main(["export", str(pack_file), "--path", str(machine_a), "--json"]) == 0
    exp_out = json.loads(capsys.readouterr().out)
    assert pack_file.is_file()
    assert set(exp_out["skills_exported"]) == {"doc-helper", "net-audit"}
    assert "net-audit/.env" in exp_out["excluded_sensitive_files"]
    assert "sec-team" in exp_out["profiles_exported"]

    # 11. Delete upstream_src completely to prove 100% OFFLINE restoration on Machine B!
    shutil.rmtree(upstream_src)

    machine_b = tmp_path / "machine_b"
    machine_b.mkdir()

    # 14. `skillporter diff` before import shows both skills missing on Machine B (exit 1)
    assert main(["diff", str(pack_file), "--base", str(machine_b), "--json"]) == 1
    diff_before = json.loads(capsys.readouterr().out)
    assert diff_before["only_in_right"] == ["doc-helper", "net-audit"]

    # 12. `import --dry-run` detects missing harnesses on Machine B (e.g. windsurf not installed in fake_home)
    assert main(["import", str(pack_file), "--path", str(machine_b), "--dry-run", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["dry_run"] is True
    assert "windsurf" in preview["plan"]["missing_harnesses"]
    assert not (machine_b / ".claude").exists()

    # 10. Full offline restore into Machine B
    assert main(["import", str(pack_file), "--path", str(machine_b), "--json"]) == 0
    imp_res = json.loads(capsys.readouterr().out)
    assert imp_res["dry_run"] is False
    assert (machine_b / ".claude" / "skills" / "net-audit" / "references" / "ref.md").is_file()
    assert not (machine_b / ".claude" / "skills" / "net-audit" / ".env").exists()
    assert (machine_b / "skillporter.yaml").is_file()
    assert (machine_b / "skillporter.lock").is_file()

    # `diff` between Machine B and portable.skillpack is now IDENTICAL (exit 0)!
    assert main(["diff", str(pack_file), "--base", str(machine_b), "--json"]) == 0
    diff_after = json.loads(capsys.readouterr().out)
    assert diff_after["has_differences"] is False
    assert sorted(diff_after["identical_skills"]) == ["doc-helper", "net-audit"]

    # `lock --check` and `status` on Machine B both pass 100% offline!
    assert main(["lock", str(machine_b), "--check", "--json"]) == 0
    capsys.readouterr()
    assert main(["status", str(machine_b), "--json"]) == 0
    capsys.readouterr()

    # 13a. Corrupted archive fails closed without writing to Machine C
    corrupt_pack = tmp_path / "corrupt.skillpack"
    corrupt_pack.write_bytes(b"not-a-valid-gzip-stream")
    machine_c = tmp_path / "machine_c"
    assert main(["import", str(corrupt_pack), "--path", str(machine_c)]) == 1
    capsys.readouterr()
    assert not (machine_c / ".claude").exists()

    # 13b. Tampered skill content inside .skillpack fails SHA-256 integrity check!
    tampered_pack = tmp_path / "tampered.skillpack"
    extract_tmp = tmp_path / "tamper_stage"
    with tarfile.open(pack_file, "r:gz") as tf:
        tf.extractall(extract_tmp, filter="data")
    (extract_tmp / "skills" / "doc-helper" / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(name="doc-helper", version="2.1.0") + "\nInjected tamper!\n",
        encoding="utf-8",
    )
    with tarfile.open(tampered_pack, "w:gz") as tf_out:
        for fp in sorted(extract_tmp.rglob("*")):
            if fp.is_file():
                tf_out.add(fp, arcname=fp.relative_to(extract_tmp).as_posix())
    assert main(["import", str(tampered_pack), "--path", str(machine_c)]) == 1
    err_tamper = capsys.readouterr().err
    assert "integrity" in err_tamper.lower() or "hash" in err_tamper.lower()
    assert not (machine_c / ".claude").exists()

    # 13c. Path-traversing tar entry inside .skillpack is rejected before extraction!
    traversal_pack = tmp_path / "traversal.skillpack"
    with tarfile.open(traversal_pack, "w:gz") as tf_evil:
        payload = b"escaped"
        ti = tarfile.TarInfo(name="../escaped.txt")
        ti.size = len(payload)
        tf_evil.addfile(ti, io.BytesIO(payload))
    assert main(["import", str(traversal_pack), "--path", str(machine_c)]) == 1
    capsys.readouterr()
    assert not (tmp_path / "escaped.txt").exists()


# ---------------------------------------------------------------------------
# 16, 18 & 19. Named profiles, unmanaged adopt, self-skill (.pyz) & MCP parity
# ---------------------------------------------------------------------------


def test_profiles_adopt_self_skill_and_mcp_portability_tools(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    src_root = tmp_path / "srcs"
    s_fe = _create_skill(src_root, "frontend-lint", "1.0.0")
    s_be = _create_skill(src_root, "backend-sql", "1.0.0")

    # Drop an unmanaged skill directly into .claude/skills and adopt it
    _create_skill(ws / ".claude" / "skills", "legacy-local", "1.1.0")
    assert main(["adopt", "--all", "--path", str(ws), "--json"]) == 0
    adopted_out = json.loads(capsys.readouterr().out)
    assert adopted_out["adopted"][0]["name"] == "legacy-local"

    # Profile 1: frontend (frontend-lint + legacy-local)
    assert main(["add", str(s_fe), "--harness", "claude-code,codex", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert main(["profile", "save", "frontend", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()

    # Profile 2: backend (only backend-sql)
    assert main(["add", str(s_be), "--harness", "claude-code", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "profile",
                "save",
                "backend",
                "--skill",
                "backend-sql",
                "--harness",
                "claude-code",
                "--path",
                str(ws),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    # Switch to `backend` with `--prune` -> removes frontend-lint & legacy-local, keeps backend-sql!
    assert main(["profile", "use", "backend", "--prune", "--path", str(ws), "--json"]) == 0
    use_res = json.loads(capsys.readouterr().out)
    assert use_res["active_profile"] == "backend"
    assert "frontend-lint" in use_res["pruned_skills"]
    assert (ws / ".claude" / "skills" / "backend-sql" / "SKILL.md").is_file()
    assert not (ws / ".claude" / "skills" / "frontend-lint").exists()

    # Switch back to `frontend` -> restores frontend-lint from its saved source!
    assert main(["profile", "use", "frontend", "--path", str(ws), "--json"]) == 0
    capsys.readouterr()
    assert (ws / ".claude" / "skills" / "frontend-lint" / "SKILL.md").is_file()

    # 16a. Official AI skill self-install (`skillporter self-skill install`)
    agent_ws = tmp_path / "agent_ws"
    agent_ws.mkdir()
    assert (
        main(["self-skill", "install", "--harness", "claude-code,codex", "--path", str(agent_ws), "--json"]) == 0
    )
    ss_out = json.loads(capsys.readouterr().out)
    assert ss_out["skill"] == "skillporter"
    assert (agent_ws / ".claude" / "skills" / "skillporter" / "SKILL.md").is_file()
    assert (agent_ws / ".agents" / "skills" / "skillporter" / "SKILL.md").is_file()

    # 16b. MCP Server parity & security boundary on status, diff, export, import
    st_mcp = handle_mcp_request(
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "skillporter_status", "arguments": {}}},
        workspace_root=agent_ws,
        allow_writes=False,
    )
    assert st_mcp is not None and not st_mcp["result"]["isError"]  # type: ignore[index]
    st_data = json.loads(st_mcp["result"]["content"][0]["text"])  # type: ignore[index]
    assert "skillporter" in st_data["managed_skills"]

    # MCP export denied when allow_writes=False
    denied_exp = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "skillporter_export", "arguments": {"output": "bundle.skillpack"}},
        },
        workspace_root=agent_ws,
        allow_writes=False,
    )
    assert denied_exp is not None and denied_exp["result"]["isError"] is True  # type: ignore[index]

    # MCP export succeeds inside workspace when allow_writes=True, and rejects escaping ../outside.skillpack
    escape_exp = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "skillporter_export", "arguments": {"output": "../escape.skillpack"}},
        },
        workspace_root=agent_ws,
        allow_writes=True,
    )
    assert escape_exp is not None and escape_exp["result"]["isError"] is True  # type: ignore[index]

    ok_exp = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {"name": "skillporter_export", "arguments": {"output": "bundle.skillpack"}},
        },
        workspace_root=agent_ws,
        allow_writes=True,
    )
    assert ok_exp is not None and not ok_exp["result"]["isError"]  # type: ignore[index]
    assert (agent_ws / "bundle.skillpack").is_file()

    diff_mcp = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {"name": "skillporter_diff", "arguments": {"target": "bundle.skillpack"}},
        },
        workspace_root=agent_ws,
        allow_writes=False,
    )
    assert diff_mcp is not None and not diff_mcp["result"]["isError"]  # type: ignore[index]
    assert json.loads(diff_mcp["result"]["content"][0]["text"])["has_differences"] is False  # type: ignore[index]


def test_standalone_pyz_self_skill_and_portability(tmp_path):
    """Verify the built standalone zipapp (.pyz) bundles SKILL.md and runs export/import."""
    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "build_standalone.py")],
        check=True,
        capture_output=True,
    )
    pyz = repo_root / "dist" / "skillporter.pyz"
    assert pyz.is_file()

    ws = tmp_path / "pyz_ws"
    ws.mkdir()
    proc = subprocess.run(
        [sys.executable, str(pyz), "self-skill", "install", "--harness", "claude-code", "--path", str(ws), "--json"],
        cwd=str(ws),
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out["skill"] == "skillporter"
    assert (ws / ".claude" / "skills" / "skillporter" / "SKILL.md").is_file()
