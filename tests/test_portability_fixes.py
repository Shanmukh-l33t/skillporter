"""Regression tests for .skillpack export/import/diff defects (D5, D6, B3, B18)."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from skillporter import harnesses
from skillporter.cli import main
from skillporter.security import compute_tree_hash
from skillporter.sources import safe_extract_tar

_SKILL = (
    "---\nname: {name}\ndescription: Execute {name} workflow reliably. Use when running {name}.\n"
    'license: MIT\nmetadata:\n  version: "1.0.0"\n---\n\n# {name}\n\n{body}'
)


def _skill(base: Path, name: str, *, body: str = "Safe instructions.\n", files: dict[str, str] | None = None) -> Path:
    sdir = base / name
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "SKILL.md").write_text(_SKILL.format(name=name, body=body), encoding="utf-8")
    for rel, content in (files or {}).items():
        fp = sdir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return sdir


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    for var in ("HERMES_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    # Harness detection also looks for agent binaries on PATH. Restrict PATH to the directory holding git so a
    # developer machine's own claude/codex/opencode/hermes installs cannot change what these tests see as "detected".
    git = shutil.which("git")
    monkeypatch.setenv("PATH", str(Path(git).parent) if git else str(tmp_path))
    return h


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def _read_pack(pack: Path) -> tuple[dict, dict[str, bytes]]:
    files: dict[str, bytes] = {}
    with tarfile.open(pack, "r:gz") as tf:
        for m in tf.getmembers():
            fh = tf.extractfile(m)
            if m.isfile() and fh is not None:
                files[m.name] = fh.read()
    return json.loads(files.pop("skillpack.json")), files


def _write_pack(pack: Path, doc: dict, files: dict[str, bytes]) -> None:
    with tarfile.open(pack, "w:gz") as tf:
        payloads = {"skillpack.json": json.dumps(doc).encode(), **files}
        for name, data in payloads.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


def _rewrite(pack: Path, mutate: Callable[[dict, dict[str, bytes]], None]) -> None:
    doc, files = _read_pack(pack)
    mutate(doc, files)
    _write_pack(pack, doc, files)


def _written_harness_dirs(ws: Path) -> set[str]:
    return {p.name for p in ws.iterdir() if p.is_dir() and p.name.startswith(".")} - {".git", ".skillporter"}


def _exported_pack(
    tmp_path: Path, name: str = "alpha", targets: str = "claude-code,codex"
) -> tuple[Path, Path]:
    ws = _git_repo(tmp_path / "src_ws")
    src = _skill(tmp_path / "srcs", name)
    assert main(["add", str(src), "--harness", targets, "--path", str(ws)]) == 0
    pack = tmp_path / "e.skillpack"
    assert main(["export", str(pack), "--path", str(ws)]) == 0
    return ws, pack


# ---------------------------------------------------------------------------
# D5: export records installed harnesses; import never fans out to unselected ones
# ---------------------------------------------------------------------------


def test_export_records_only_installed_harnesses(tmp_path, home, capsys):
    _, pack = _exported_pack(tmp_path)
    capsys.readouterr()
    doc, _ = _read_pack(pack)
    assert doc["harnesses"] == ["claude-code", "codex"]
    assert doc["skills"]["alpha"]["harnesses"] == ["claude-code", "codex"]
    assert len(doc["harnesses"]) < len(harnesses.names())


def test_import_default_writes_only_selected_harness_dirs(tmp_path, home, capsys):
    _, pack = _exported_pack(tmp_path)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    assert main(["import", str(pack), "--path", str(dest)]) == 0
    assert _written_harness_dirs(dest) == {".claude", ".agents"}
    assert (dest / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()


def test_legacy_pack_with_every_reachable_harness_is_not_fanned_out(tmp_path, home, capsys):
    _, pack = _exported_pack(tmp_path)
    everything = sorted(harnesses.names())

    def legacy(doc, files):
        doc.pop("harness_selection", None)
        # Use the manifest an older `init` would have written, not today's empty default.
        doc["manifest"] = {"harnesses": ["claude-code", "codex", "cursor"]}
        doc["harnesses"] = everything
        doc["skills"]["alpha"]["harnesses"] = everything

    _rewrite(pack, legacy)
    capsys.readouterr()

    dest = _git_repo(tmp_path / "dest")
    assert main(["import", str(pack), "--path", str(dest), "--dry-run", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    planned = preview["plan"]["target_harnesses_by_skill"]["alpha"]
    assert set(planned) <= {"claude-code", "codex", "cursor"}
    assert "cline" not in planned
    assert _written_harness_dirs(dest) == set()

    assert main(["import", str(pack), "--path", str(dest), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    written = _written_harness_dirs(dest)
    assert written == {".claude", ".agents"}
    # the preview listed exactly what was then written
    assert {r["harness"] for r in result["installed"]} == set(planned)
    previewed = {d for s in preview["plan"]["skills"] for d in s["destinations"]}
    assert previewed == {r["dest"] for r in result["installed"]}


def test_explicit_harness_flag_still_installs_into_requested_harnesses(tmp_path, home, capsys):
    _, pack = _exported_pack(tmp_path)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    assert main(["import", str(pack), "--path", str(dest), "--harness", "claude-code,cline"]) == 0
    assert _written_harness_dirs(dest) == {".claude", ".cline"}


def test_legacy_pack_targets_not_detected_or_configured_are_listed_not_written(tmp_path, home, capsys):
    ws = _git_repo(tmp_path / "src_ws")
    src = _skill(tmp_path / "srcs", "alpha")
    assert main(["add", str(src), "--harness", "claude-code,windsurf", "--path", str(ws)]) == 0
    pack = tmp_path / "w.skillpack"
    assert main(["export", str(pack), "--path", str(ws)]) == 0
    _rewrite(pack, lambda doc, files: doc.pop("harness_selection"))
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    assert main(["import", str(pack), "--path", str(dest), "--dry-run", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert "windsurf" in plan["missing_harnesses"]
    assert "windsurf" not in plan["target_harnesses_by_skill"]["alpha"]


def test_diff_between_workspace_and_fresh_export_has_no_harness_noise(tmp_path, home, capsys):
    ws, pack = _exported_pack(tmp_path)
    capsys.readouterr()
    assert main(["diff", str(pack), "--base", str(ws), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["has_differences"] is False


# ---------------------------------------------------------------------------
# D6: diff hashes the on-disk skill trees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("with_lock", [True, False])
def test_diff_reports_on_disk_edit_in_any_installed_copy(tmp_path, home, capsys, with_lock):
    ws, pack = _exported_pack(tmp_path)
    if with_lock:
        assert main(["lock", str(ws)]) == 0
    capsys.readouterr()
    # edit only the .claude copy (the .agents copy sorts first and stays pristine)
    edited = ws / ".claude" / "skills" / "alpha" / "SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nLocal edit.\n", encoding="utf-8")

    rc = main(["diff", str(pack), "--base", str(ws), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["has_differences"] is True
    assert [c["skill"] for c in out["content_diffs"]] == ["alpha"]
    assert out["content_diffs"][0]["changed_files"] == ["SKILL.md"]
    assert out["identical_skills"] == []


def test_diff_directory_target_reports_on_disk_edit(tmp_path, home, capsys):
    ws, _ = _exported_pack(tmp_path)
    other = _git_repo(tmp_path / "other")
    assert main(["add", str(tmp_path / "srcs" / "alpha"), "--harness", "claude-code,codex", "--path", str(other)]) == 0
    assert main(["lock", str(other)]) == 0
    capsys.readouterr()
    assert main(["diff", str(other), "--base", str(ws), "--json"]) == 0
    capsys.readouterr()
    skill_md = other / ".claude" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nedit\n", encoding="utf-8")
    assert main(["diff", str(other), "--base", str(ws), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["content_diffs"][0]["skill"] == "alpha"


# ---------------------------------------------------------------------------
# B3: fetch-time policy and scan gating for non-bundled skills
# ---------------------------------------------------------------------------

_SHELL_FILES = {"scripts/run.py": "import subprocess\nsubprocess.run('ls', shell=True)\n"}


def _referenced_pack(tmp_path: Path, source: Path) -> Path:
    _, pack = _exported_pack(tmp_path, name="alpha", targets="claude-code")
    tree, fhashes = compute_tree_hash(source)

    def to_reference(doc, files):
        meta = doc["skills"]["alpha"]
        meta.update(
            bundled=False, archive_dir="", source=str(source), tree_hash=tree, file_hashes=fhashes, resolved_commit=""
        )
        for key in [k for k in files if k.startswith("skills/")]:
            del files[key]

    _rewrite(pack, to_reference)
    return pack


def test_fetched_source_is_policy_evaluated_at_apply_time(tmp_path, home, capsys):
    source = _skill(tmp_path / "upstream", "alpha", body="Run `scripts/run.py`.\n", files=_SHELL_FILES)
    pack = _referenced_pack(tmp_path, source)
    capsys.readouterr()

    banned = _git_repo(tmp_path / "banned")
    (banned / "skillporter.policy.yaml").write_text("banned_capabilities:\n  - shell_exec\n", encoding="utf-8")
    rc = main(["import", str(pack), "--path", str(banned), "--harness", "claude-code", "--allow-risky"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error:" in err and "policy" in err.lower() and "shell_exec" in err
    assert "Traceback" not in err
    assert not (banned / ".claude" / "skills" / "alpha").exists()


def test_fetched_source_without_policy_violation_still_imports(tmp_path, home, capsys):
    source = _skill(tmp_path / "upstream", "alpha", body="Safe.\n")
    pack = _referenced_pack(tmp_path, source)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    (dest / "skillporter.policy.yaml").write_text("banned_capabilities:\n  - shell_exec\n", encoding="utf-8")
    assert main(["import", str(pack), "--path", str(dest), "--harness", "claude-code"]) == 0
    assert (dest / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()


def test_fetched_source_risk_threshold_blocks_unless_allowed(tmp_path, home, capsys):
    source = _skill(tmp_path / "upstream", "alpha", body="Run `scripts/run.py`.\n", files=_SHELL_FILES)
    pack = _referenced_pack(tmp_path, source)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    rc = main(["import", str(pack), "--path", str(dest), "--harness", "claude-code", "--max-risk-score", "0"])
    err = capsys.readouterr().err
    assert rc == 1 and "error:" in err
    assert not (dest / ".claude" / "skills" / "alpha").exists()
    assert main(["import", str(pack), "--path", str(dest), "--harness", "claude-code", "--allow-risky"]) == 0


def test_fetched_source_structural_escape_is_never_overridable(tmp_path, home, capsys):
    source = _skill(tmp_path / "upstream", "alpha")
    pack = _referenced_pack(tmp_path, source)
    (source / "escape").symlink_to("/etc")
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    rc = main(["import", str(pack), "--path", str(dest), "--harness", "claude-code", "--allow-risky", "--force"])
    assert rc != 0
    assert "Traceback" not in capsys.readouterr().err
    assert not (dest / ".claude" / "skills" / "alpha").exists()


# ---------------------------------------------------------------------------
# B18: errors are one-line `error:` messages, never tracebacks, nothing written outside the workspace
# ---------------------------------------------------------------------------


def _assert_clean_error(capsys, rc: int) -> str:
    err = capsys.readouterr().err
    assert rc in (1, 2)
    assert err.count("error:") == 1 and "Traceback" not in err
    assert len([ln for ln in err.strip().splitlines() if ln.strip()]) == 1
    return err


def test_import_pack_with_absolute_skill_name_is_a_clean_error(tmp_path, home, capsys):
    _, pack = _exported_pack(tmp_path)
    outside = tmp_path / "outside_target"

    def rename(doc, files):
        doc["skills"][str(outside)] = doc["skills"].pop("alpha")

    _rewrite(pack, rename)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    for extra in ([], ["--dry-run"]):
        rc = main(["import", str(pack), "--path", str(dest), *extra])
        _assert_clean_error(capsys, rc)
    assert not outside.exists() and _written_harness_dirs(dest) == set()


@pytest.mark.parametrize("source", ["", "   "])
def test_import_pack_with_unbundled_empty_source_is_a_clean_error(tmp_path, home, capsys, source):
    _, pack = _exported_pack(tmp_path)

    def unbundle(doc, files):
        doc["skills"]["alpha"].update(bundled=False, source=source, archive_dir="")
        for key in [k for k in files if k.startswith("skills/")]:
            del files[key]

    _rewrite(pack, unbundle)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    rc = main(["import", str(pack), "--path", str(dest)])
    _assert_clean_error(capsys, rc)
    assert _written_harness_dirs(dest) == set()


def test_import_pack_with_unfetchable_source_is_a_clean_error(tmp_path, home, capsys):
    _, pack = _exported_pack(tmp_path)

    def unbundle(doc, files):
        doc["skills"]["alpha"].update(bundled=False, source=str(tmp_path / "does-not-exist"), archive_dir="")
        for key in [k for k in files if k.startswith("skills/")]:
            del files[key]

    _rewrite(pack, unbundle)
    capsys.readouterr()
    dest = _git_repo(tmp_path / "dest")
    rc = main(["import", str(pack), "--path", str(dest)])
    _assert_clean_error(capsys, rc)
    assert _written_harness_dirs(dest) == set()


def test_pack_cli_is_byte_reproducible(tmp_path, home):
    src = _skill(tmp_path, "notes", files={"references/example.md": "Example.\n"})
    tree_hash, file_hashes = compute_tree_hash(src)
    archives = []
    timestamps = []
    for i in range(2):
        out = tmp_path / f"pack-{i}"
        result = subprocess.run(
            [sys.executable, "-m", "skillporter", "pack", str(src), "--out", str(out), *(["--json"] if i == 0 else [])],
            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            capture_output=True, text=True, check=True,
        )
        archive = out / "notes-1.0.0.tar.gz"
        provenance = out / "notes-1.0.0.provenance.json"
        blob = archive.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        prov = json.loads(provenance.read_bytes())
        assert prov["archive_sha256"] == digest
        assert (prov["tree_hash"], prov["file_hashes"]) == (tree_hash, file_hashes)
        if i == 0:
            assert json.loads(result.stdout) == {
                "skill": "notes", "version": "1.0.0", "archive": str(archive),
                "provenance": str(provenance), "archive_sha256": digest, "tree_hash": prov["tree_hash"],
            }
            time.sleep(1.1)
        else:
            assert "packed notes@1.0.0:" in result.stdout and digest[:16] in result.stdout
            assert str(archive) in result.stdout and str(provenance) in result.stdout
        archives.append(blob)
        timestamps.append(prov["generated_at"])

    assert timestamps[0] != timestamps[1]
    assert gzip.decompress(archives[0]) == gzip.decompress(archives[1])
    assert archives[0] == archives[1]
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    safe_extract_tar(archive, extracted)
    assert compute_tree_hash(extracted / "notes") == compute_tree_hash(src)


def test_pack_skill_with_traversal_frontmatter_name_is_a_clean_error(tmp_path, home, capsys):
    sdir = tmp_path / "evil"
    sdir.mkdir()
    (sdir / "SKILL.md").write_text(_SKILL.format(name="../../x", body="Body.\n"), encoding="utf-8")
    out_dir = tmp_path / "out" / "nested"
    rc = main(["pack", str(sdir), "--out", str(out_dir)])
    _assert_clean_error(capsys, rc)
    assert not out_dir.exists()
    assert not (tmp_path / "x-1.0.0.tar.gz").exists() and not (tmp_path / "out" / "x-1.0.0.tar.gz").exists()


def test_export_of_skill_with_unsafe_name_is_a_clean_error(tmp_path, home, capsys, monkeypatch):
    from skillporter import portability

    ws = _git_repo(tmp_path / "ws")
    _skill(ws / ".claude" / "skills", "alpha")
    real = portability.validate_skill_name_segment

    def boom(name, base=None):
        if name == "alpha":
            return real("../alpha", base)
        return real(name, base)

    monkeypatch.setattr(portability, "validate_skill_name_segment", boom)
    rc = main(["export", str(tmp_path / "o.skillpack"), "--path", str(ws)])
    _assert_clean_error(capsys, rc)
    assert not (tmp_path / "o.skillpack").exists()


def test_mcp_diff_reports_on_disk_edit_in_a_secondary_copy(tmp_path, home):
    from skillporter.mcp_server import handle_mcp_request

    ws = _git_repo(tmp_path / "ws")
    base = _git_repo(tmp_path / "base")
    src = _skill(tmp_path / "src", "alpha")
    for root in (ws, base):
        assert main(["add", str(src), "--harness", "claude-code", "--harness", "codex", "--path", str(root)]) == 0
    edited = ws / ".claude" / "skills" / "alpha" / "SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n- extra rule\n", encoding="utf-8")

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "skillporter_diff", "arguments": {"path": str(ws), "target": str(base)}},
    }
    resp = handle_mcp_request(req, workspace_root=ws.parent.resolve(), allow_writes=False)
    assert resp is not None and resp["result"]["isError"] is False
    report = json.loads(resp["result"]["content"][0]["text"])
    assert report["has_differences"] is True
    assert [d["skill"] for d in report["content_diffs"]] == ["alpha"]
    assert report["content_diffs"][0]["changed_files"] == ["SKILL.md"]
