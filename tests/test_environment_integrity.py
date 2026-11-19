"""Workspace integrity regressions using only local, disposable skills."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from skillporter import diagnose as discovery
from skillporter import environment, harnesses
from skillporter.cli import main
from skillporter.manifest import LOCKFILE_FILENAME
from skillporter.state import load_state


def _skill(base, name="release-notes", *, version=""):
    folder = base / name
    folder.mkdir(parents=True)
    metadata = f"metadata:\n  version: '{version}'\n" if version else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Summarize the changes for a release.\n{metadata}---\n\n"
        "Group the changes by component and check them against the changelog.\n",
        encoding="utf-8",
    )
    return folder


def _cli(capsys, code, *args):
    result = main([*(str(arg) for arg in args), "--json"])
    captured = capsys.readouterr()
    assert result == code, captured
    return json.loads(captured.out)


def _link(path, target):
    try:
        path.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        pytest.skip("Windows does not grant this process symlink creation privileges")


def test_claude_copy_does_not_require_absent_default_targets(tmp_path, capsys):
    _skill(tmp_path / ".claude/skills")
    diag = _cli(capsys, 0, "diagnose", tmp_path)
    assert diag["findings"] == []
    assert diag["harnesses"]["codex"]["reachable_skills"] == []
    status = _cli(capsys, 0, "status", tmp_path)
    assert status["healthy"] is True
    assert "codex" not in status["selected_harnesses"]
    assert status["skills"]["release-notes"]["status"] == "UNMANAGED"
    explicit = _cli(capsys, 1, "diagnose", tmp_path, "--harness", "codex")
    assert any("missing from expected paths for: codex" in item for item in explicit["findings"])
    doctor = _cli(capsys, 0, "doctor", tmp_path, "--fix")
    assert not doctor["repaired"]
    assert not (tmp_path / ".agents").exists()


def test_status_reports_only_known_versions(tmp_path, capsys):
    base = tmp_path / ".agents/skills"
    _skill(base)
    _skill(base, "triage", version="1.0.0")
    (tmp_path / "skillporter.yaml").write_text(
        "schema_version: 2\nharnesses: [codex]\nskills:\n"
        "  - name: triage\n    source: ./.agents/skills/triage\n    version: '2.3.0'\n",
        encoding="utf-8",
    )
    status = _cli(capsys, 0, "status", tmp_path)
    assert status["skills"]["release-notes"]["version"] == ""
    assert status["skills"]["triage"]["version"] == "1.0.0"


def test_duplicate_skill_needs_attention_even_if_hashes_match(tmp_path, capsys):
    _skill(tmp_path / ".agents/skills")
    _skill(tmp_path / ".cursor/skills")
    (tmp_path / "skillporter.yaml").write_text("schema_version: 2\nharnesses: [cursor]\n", encoding="utf-8")
    status = _cli(capsys, 1, "status", tmp_path)
    assert status["healthy"] is False
    assert status["skills"]["release-notes"]["status"] == "DUPLICATE"
    assert status["attention_skills"] == ["release-notes"]
    assert status["drifted_skills"] == []


def test_shared_location_lists_and_hashes_once_per_status(tmp_path, capsys, monkeypatch):
    project = tmp_path / "project"
    source = _skill(tmp_path / "upstream")
    base = project / ".agents/skills"
    project.mkdir()
    _cli(capsys, 0, "add", source, "--path", project, "--harness", "codex,cursor")
    nested = _skill(base / "editorial", "fact-check")
    installed = base / source.name
    (project / "skillporter.yaml").write_text(
        "schema_version: 2\nskills:\n  - name: fact-check\n    source: ./.agents/skills/editorial/fact-check\n"
        "    harnesses: [cursor]\n",
        encoding="utf-8",
    )

    reads, hashes, detections = Counter(), Counter(), Counter()
    iterdir, tree_hash, detect = Path.iterdir, discovery.compute_tree_hash, harnesses.detect_harnesses

    def read(path):
        reads[path] += 1
        return iterdir(path)

    def digest(path):
        hashes[path.resolve()] += 1
        return tree_hash(path)

    def detect_once(root, **kwargs):
        detections[root] += 1
        return detect(root, **kwargs)

    monkeypatch.setattr(Path, "iterdir", read)
    monkeypatch.setattr(discovery, "compute_tree_hash", digest)
    monkeypatch.setattr(environment, "compute_tree_hash", digest, raising=False)
    monkeypatch.setattr(harnesses, "detect_harnesses", detect_once)
    status = _cli(capsys, 0, "status", project)
    assert "cursor" in status["skills"][nested.name]["installed_harnesses"]
    assert "codex" not in status["skills"][nested.name]["installed_harnesses"]
    assert hashes == {installed: 1, nested: 1}
    assert detections == {project: 1}
    assert reads[base] == 1
    with (installed / "SKILL.md").open("a", encoding="utf-8") as stream:
        stream.write("\nCheck the patch release notes too.\n")
    status = _cli(capsys, 1, "status", project)
    assert status["drifted_skills"] == [source.name]
    assert hashes[installed] == 2


def test_dangling_harness_root_is_broken_not_content_drift(tmp_path, capsys):
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    _skill(project / ".agents/skills")
    target = tmp_path / "unavailable"
    link = project / ".claude/skills"
    _link(link, target)
    diag = _cli(capsys, 1, "diagnose", project, "--harness", "claude-code", "--harness", "codex")
    location = diag["harnesses"]["claude-code"]["locations"][0]
    assert location["status"] == "broken"
    assert location["broken_links"] == [str(link)]
    assert diag["drifted"] == {}
    before = _cli(capsys, 1, "doctor", project, "--fix", "--dry-run")
    assert before["drifted"] == {} and link.is_symlink()
    after = _cli(capsys, 0, "doctor", project, "--fix")
    assert after["drifted"] == {} and not link.is_symlink() and not target.exists()


def test_missing_locked_copy_is_not_a_content_mismatch(tmp_path, capsys):
    project = tmp_path / "project"
    source = _skill(tmp_path / "upstream")
    project.mkdir()
    _cli(capsys, 0, "add", source, "--path", project, "--harness", "codex")
    _cli(capsys, 0, "lock", project)
    installed = project / ".agents/skills" / source.name
    (installed / "SKILL.md").unlink()
    status = _cli(capsys, 1, "status", project)
    assert status["skills"][source.name]["status"] == "ORPHANED"
    assert status["drifted_skills"] == []
    assert any("missing on disk" in item for item in status["lock_drift"])


def test_add_repair_and_remove_real_shared_install(tmp_path, capsys):
    project = tmp_path / "project"
    source = _skill(tmp_path / "upstream")
    project.mkdir()
    source_md = (source / "SKILL.md").read_bytes()
    add = ("add", source, "--path", project, "--harness", "codex,cursor")
    _cli(capsys, 0, *add, "--dry-run")
    assert not any(project.iterdir())
    _cli(capsys, 0, *add)
    _cli(capsys, 0, "lock", project)
    installed = project / ".agents/skills" / source.name / "SKILL.md"
    lock = (project / LOCKFILE_FILENAME).read_bytes()
    original = installed.read_bytes()
    assert original == source_md
    edited = original + b"\nDraft note, not ready for release.\n"
    installed.write_bytes(edited)
    assert _cli(capsys, 0, "scan", installed.parent, "--offline", "--engine", "static")["passed"]
    status = _cli(capsys, 1, "status", project)
    assert status["drifted_skills"] == [source.name] and status["lock_drift"]
    preview = _cli(capsys, 1, "doctor", project, "--fix", "--dry-run")
    assert source.name in preview["drifted"] and not preview["repaired"]
    assert installed.read_bytes() == edited
    applied = _cli(capsys, 0, "doctor", project, "--fix")
    assert source.name in applied["drift_before_fix"] and not applied["drifted"] and applied["repaired"]
    assert installed.read_bytes() == original
    assert (project / LOCKFILE_FILENAME).read_bytes() == lock
    assert _cli(capsys, 0, "doctor", project)["healthy"]
    assert _cli(capsys, 0, "lock", project, "--check")["clean"]

    remove = ("remove", source.name, "--path", project, "--harness", "cursor")
    assert _cli(capsys, 0, *remove, "--dry-run")["dry_run"]
    assert load_state(project)[source.name].harnesses == ["codex", "cursor"]
    _cli(capsys, 0, *remove)
    assert load_state(project)[source.name].harnesses == ["codex"]
    assert installed.read_bytes() == original
    _cli(capsys, 0, "remove", source.name, "--path", project, "--harness", "codex")
    assert not installed.exists() and not load_state(project)
    assert (source / "SKILL.md").read_bytes() == source_md


def test_duplicate_copy_is_reported_by_diagnose_too(tmp_path, capsys):
    """status called it DUPLICATE while diagnose said 'no findings'; both must agree."""
    _skill(tmp_path / ".agents/skills")
    _skill(tmp_path / ".cursor/skills")
    (tmp_path / "skillporter.yaml").write_text("schema_version: 2\nharnesses: [cursor]\n", encoding="utf-8")
    diag = _cli(capsys, 1, "diagnose", tmp_path)
    assert any("loaded from 2 paths by cursor" in item for item in diag["findings"])
    status = _cli(capsys, 1, "status", tmp_path)
    assert status["skills"]["release-notes"]["status"] == "DUPLICATE"
    assert any("loaded from 2 paths" in f for f in status["findings"])
