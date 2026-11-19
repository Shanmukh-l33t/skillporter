"""Run ordinary Skillporter journeys against a preinstalled CLI, never the real HOME."""

import argparse
import gzip
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def isolated(home):
    # Keep only OS/process essentials; do not inherit provider, registry, or Git credentials.
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "SYSTEMDRIVE",
            "LANG",
            "LC_ALL",
        }
    }
    for key, path in {
        "HOME": home,
        "USERPROFILE": home,
        "HERMES_HOME": home / "hermes",
        "APPDATA": home / "appdata",
        "LOCALAPPDATA": home / "localappdata",
        "XDG_CONFIG_HOME": home / "config",
        "XDG_CACHE_HOME": home / "cache",
        "XDG_DATA_HOME": home / "data",
        "XDG_STATE_HOME": home / "state",
        "TMPDIR": home / "tmp",
        "TMP": home / "tmp",
        "TEMP": home / "tmp",
    }.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    return dict(
        env,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        NO_COLOR="1",
    )


def skill(base, name, version="1.0.0", body="Write a short release summary."):
    path = base / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: Use when writing release notes.\n"
        f'metadata:\n  version: "{version}"\n---\n\n# Release notes\n\n{body}\n',
        encoding="utf-8",
    )
    return path.parent


def snapshot(path):
    return {
        f.relative_to(path).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in path.rglob("*")
        if f.is_file()
    }


class Probe:
    def __init__(self, binary, root):
        self.binary = binary
        self.root = root
        self.env = isolated(root / "home")
        self.cwd = root / "project"
        self.cwd.mkdir()
        self.failures = []

    def check(self, label, ok):
        print(f"{'PASS' if ok else 'FAIL'} {label}")
        if not ok:
            self.failures.append(label)

    def log(self, text):
        print(self.redact(text))

    def redact(self, text):
        for path in (str(self.root), str(self.root).replace("\\", "\\\\"), self.root.as_posix()):
            text = text.replace(path, "$TMP")
        return text.replace(str(self.binary), "$SKILLPORTER")

    def run(self, *args, code: int | None = 0, contains=None, cwd=None, binary=None, full=False):
        cwd = cwd or self.cwd
        label = shlex.join(map(str, args))
        result = subprocess.run(
            [binary or self.binary, *map(str, args)],
            cwd=cwd,
            env=self.env,
            input="",
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        out = result.stdout + result.stderr
        shown = self.redact(out.strip())
        shown = shown if full or len(shown) < 950 else shown[:750] + "\n… excerpt …\n" + shown[-150:]
        self.log(
            f"\n[{cwd.name}] $ {Path(binary).stem if binary else 'skillporter'} {label}\n"
            f"exit={result.returncode}\n{shown}"
        )
        if code is not None:
            self.check(
                label.split()[0] + " exit/content", result.returncode == code and (contains is None or contains in out)
            )
        return result

    def lifecycle(self):
        source = skill(self.root / "src", "release-notes")
        marker = source / "SKILL.md"
        dest = self.cwd / ".claude/skills/release-notes/SKILL.md"
        shared = self.cwd / ".agents/skills/release-notes/SKILL.md"
        targets = ("--harness", "claude-code", "--harness", "codex", "--harness", "cursor")
        self.run("add", source, *targets, "--dry-run", "--offline")
        self.check("dry-run left workspace empty", not snapshot(self.cwd))
        self.run("add", source, *targets, "--offline")
        self.check(
            "native and shared paths match source, no duplicate Cursor path",
            dest.read_bytes() == shared.read_bytes() == marker.read_bytes()
            and not (self.cwd / ".cursor/skills/release-notes").exists(),
        )
        self.run("list", contains="release-notes")
        self.run("status", contains="release-notes")
        self.run("diagnose", *targets, contains="release-notes")
        self.run("init")
        self.run("sync")
        self.run("lock")
        before = snapshot(self.cwd)
        self.run("lock", "--check")
        self.check("lock check made no file changes", snapshot(self.cwd) == before)
        lock = json.loads((self.cwd / "skillporter.lock").read_text(encoding="utf-8"))
        entry = lock["skills"]["release-notes"]
        self.check(
            "local content pin and per-file hash",
            entry["pin_state"] == "PINNED_CONTENT"
            and entry["file_hashes"]["SKILL.md"] == hashlib.sha256(marker.read_bytes()).hexdigest(),
        )
        self.run("audit", "--limit", "2", contains="release-notes")
        self.run("profile", "save", "release")
        self.run("profile", "list", contains="release")
        self.run("profile", "show", "release", contains="release-notes")
        pack = self.root / "release.skillpack"
        self.run("export", pack, "--managed-only")
        self.run("diff", pack)
        other = self.root / "target"
        other.mkdir()
        self.run("import", pack, "--dry-run", cwd=other)
        self.check("import dry-run left target empty", not snapshot(other))
        self.run("import", pack, cwd=other)
        self.check(
            "import restored identical files to recorded paths",
            all((other / f.relative_to(self.cwd)).read_bytes() == marker.read_bytes() for f in (dest, shared)),
        )
        self.check(
            "default import did not add other dedicated harness paths",
            not any((other / path).exists() for path in (".cline/skills", ".github/skills", ".roo/skills")),
        )
        self.run("diff", pack, cwd=other)
        self.run("profile", "list", cwd=other, contains="release")
        self.run("profile", "use", "release", cwd=other)
        self.check(
            "activating imported profile respects saved selected harnesses",
            not any((other / path).exists() for path in (".cline/skills", ".github/skills", ".roo/skills")),
        )
        self.run("profile", "delete", "release", cwd=other)
        conflict = self.root / "conflict"
        foreign = skill(conflict / ".agents/skills", "release-notes", body="Keep my own notes.") / "SKILL.md"
        before = foreign.read_bytes()
        self.run("import", pack, cwd=conflict, code=1)
        self.check(
            "conflicting import preserved existing file and created no install",
            foreign.read_bytes() == before and not (conflict / ".claude/skills/release-notes").exists(),
        )
        self.run("import", pack, "--on-conflict", "overwrite", cwd=conflict)
        self.check("retry restored package bytes", foreign.read_bytes() == marker.read_bytes())
        v1 = marker.read_bytes()
        dest.write_bytes(v1 + b"\nLocal edit.\n")
        self.run("lock", "--check", code=1, contains="drift")
        self.run("sync", code=1, contains="refusing to re-lock")
        self.check("refused sync preserved local edit", b"Local edit." in dest.read_bytes())
        self.run("doctor", "--fix", "--dry-run", code=1)
        self.check("doctor dry-run preserved drift", b"Local edit." in dest.read_bytes())
        self.run("doctor", "--fix")
        self.run("lock", "--check")
        self.check("doctor restored locked bytes", dest.read_bytes() == v1)
        self.run("remove", "release-notes", "--harness", "cursor")
        self.check("shared copy kept for Codex", shared.is_file())
        self.run("remove", "release-notes", "--dry-run")
        self.run("remove", "release-notes", code=2)
        self.check("unconfirmed full removal preserved installed copy", dest.is_file())
        self.run("uninstall", "release-notes", "-y")
        self.check(
            "uninstall preserved source and removed copies",
            marker.is_file() and not dest.exists() and not shared.exists(),
        )
        manual = skill(self.cwd / ".claude/skills", "handwritten")
        self.run("adopt", "handwritten")
        self.run("move", "handwritten", "--from", "claude-code", "--to", "cursor", "--isolated")
        moved = self.cwd / ".cursor/skills/handwritten/SKILL.md"
        self.check(
            "move replaced adopted source location with isolated Cursor copy", not manual.exists() and moved.is_file()
        )
        self.run("outdated", "handwritten", contains="UP-TO-DATE")

    def versions(self):
        source = skill(self.root / "src", "release-notes")
        marker = source / "SKILL.md"
        v1 = marker.read_bytes()
        dest = self.cwd / ".claude/skills/release-notes/SKILL.md"
        shared = self.cwd / ".agents/skills/release-notes/SKILL.md"
        self.run("add", source, "--harness", "claude-code", "--harness", "codex", "--offline")
        skill(source.parent, source.name, "1.1.0", "Write notes with a highlights section.")
        before = snapshot(self.cwd)
        self.run("outdated", "release-notes", contains="1.1.0")
        self.run("update", "release-notes", "--check", contains="release-notes")
        self.check("version checks did not write files", snapshot(self.cwd) == before)
        self.run("update", "release-notes")
        v2 = marker.read_bytes()
        self.check("update installed v2 across both paths", dest.read_bytes() == shared.read_bytes() == v2)
        self.run("rollback", "release-notes", "--dry-run")
        self.check("rollback dry-run left v2", dest.read_bytes() == v2)
        self.run("rollback", "release-notes")
        self.check("rollback restored both v1 copies", dest.read_bytes() == shared.read_bytes() == v1)

    def dependencies(self):
        catalog = self.cwd / "catalog"
        for name, version in (("base-utils", "1.4.0"), ("mid-layer", "1.1.0"), ("top-app", "2.0.0")):
            skill(catalog, name, version)
        mid = catalog / "mid-layer/SKILL.md"
        mid_text = mid.read_text(encoding="utf-8")
        dep = "\ndependencies:\n  - base-utils@^1.0.0\n---\n"
        mid.write_text(mid_text.replace("\n---\n", dep, 1), encoding="utf-8")
        manifest = self.cwd / "skillporter.yaml"
        text = (
            f"schema_version: 2\nproject: deps\nharnesses: [claude-code, codex]\nskills:\n"
            f"  - name: top-app\n    source: {(catalog / 'top-app').as_posix()}\n"
            f'    version: "^2.0.0"\n    dependencies:\n      - name: mid-layer\n        version: "^1.0.0"\n'
            f"        source: {(catalog / 'mid-layer').as_posix()}\n"
        )
        manifest.write_text(text, encoding="utf-8")
        graph = self.run("graph", "--json", full=True)
        order = ["base-utils", "mid-layer", "top-app"]
        self.check("transitive topological order", json.loads(graph.stdout)["install_order"] == order)
        self.run("sync", "--dry-run")
        self.check(
            "sync dry-run created no installs or lock",
            not (self.cwd / ".claude").exists() and not (self.cwd / "skillporter.lock").exists(),
        )
        self.run("sync")
        self.check(
            "all three nodes installed in both harnesses",
            all(
                (self.cwd / target / name / "SKILL.md").is_file()
                for target in (".claude/skills", ".agents/skills")
                for name in order
            ),
        )
        self.run("lock", "--check")
        conflict = self.root / "version-conflict"
        shutil.copytree(catalog, conflict / "catalog")
        conflict_text = text.replace(catalog.as_posix(), (conflict / "catalog").as_posix())
        (conflict / manifest.name).write_text(conflict_text.replace('"^1.0.0"', '"^9.0.0"'), encoding="utf-8")
        self.run("sync", cwd=conflict, code=1, contains="version conflict")
        self.check(
            "unsatisfied constraint created no installs or lock",
            not (conflict / ".claude").exists() and not (conflict / "skillporter.lock").exists(),
        )

    def remote(self):
        ref = "e4bb5d960d87126ff3b3a8af1a104b7db67560ba"
        self.run(
            "add",
            "anthropics/skills",
            "--ref",
            ref,
            "--skill",
            "pdf",
            "--harness",
            "claude-code",
            "--harness",
            "codex",
            "--offline",
        )
        self.check(
            "GitHub skill files installed without executing scripts",
            all((self.cwd / target / "pdf/SKILL.md").is_file() for target in (".claude/skills", ".agents/skills")),
        )
        self.run("lock")
        if (self.cwd / "skillporter.lock").is_file():
            entry = json.loads((self.cwd / "skillporter.lock").read_text(encoding="utf-8"))["skills"]["pdf"]
            self.check(
                "lock records requested Git commit and content digest",
                entry["resolved_commit"] == ref
                and entry["pin_state"] == "PINNED_COMMIT"
                and "SKILL.md" in entry["file_hashes"],
            )

    def sources(self):
        git = ["git", "-c", "user.name=Probe", "-c", "user.email=probe@example.invalid"]
        repo = self.root / "repo"
        skill(repo / "skills", "git-notes")
        for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "v1"]):
            subprocess.run([*git, *args], cwd=repo, env=self.env, check=True, timeout=30)
        commit = subprocess.check_output([*git, "rev-parse", "HEAD"], cwd=repo, env=self.env, text=True).strip()
        self.run("add", repo.as_uri(), "--skill", "git-notes", "--harness", "claude-code", "--offline")
        self.run("lock")
        entry = json.loads((self.cwd / "skillporter.lock").read_text(encoding="utf-8"))["skills"]["git-notes"]
        self.check(
            "file:// Git source pinned the fetched commit",
            entry["resolved_commit"] == commit and entry["pin_state"] == "PINNED_COMMIT",
        )
        bare = self.root / "bare.git"
        subprocess.run([*git, "clone", "-q", "--bare", str(repo), str(bare)], env=self.env, check=True, timeout=60)
        self.run("add", bare, "--skill", "git-notes", "--harness", "codex", "--on-conflict", "overwrite", "--offline")
        self.run("outdated", "git-notes", contains="UP-TO-DATE")
        archive = Path(shutil.make_archive(str(self.root / "zipped"), "zip", root_dir=str(repo), base_dir="skills"))
        self.run("add", archive, "--skill", "git-notes", "--harness", "cursor", "--isolated", "--offline")
        self.check(
            "ZIP archive installed Cursor-isolated copy",
            (self.cwd / ".cursor/skills/git-notes/SKILL.md").read_bytes()
            == (repo / "skills/git-notes/SKILL.md").read_bytes(),
        )
        linkws = self.root / "linkws"
        linkws.mkdir()
        link_src = skill(self.root / "link-src", "link-notes")
        symlinked = self.run(
            "add", link_src, "--harness", "claude-code", "--strategy", "symlink", "--offline", cwd=linkws, code=None
        )
        link = linkws / ".claude/skills/link-notes"
        self.check("symlink strategy or explicit platform error", link.is_symlink() or symlinked.returncode == 2)

    def mcp(self):
        s = skill(self.cwd, "mcp-notes")
        dest = self.cwd / ".claude/skills/mcp-notes/SKILL.md"
        for writes in (False, True):
            args = [str(self.binary), "mcp", "--root", "."] + (["--allow-writes"] if writes else [])
            calls = [
                (
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "verification-probe", "version": "1"},
                    },
                ),
                ("notifications/initialized", {}),
                ("ping", {}),
                ("tools/list", {}),
                ("tools/call", {"name": "skillporter_inspect", "arguments": {"source": "./mcp-notes"}}),
                (
                    "tools/call",
                    {
                        "name": "skillporter_install",
                        "arguments": {"skill": "./mcp-notes", "harnesses": ["claude-code"]},
                    },
                ),
                ("tools/call", {"name": "skillporter_status", "arguments": {}}),
            ]
            requests = [
                {
                    "jsonrpc": "2.0",
                    "method": name,
                    "params": params,
                    **({"id": i} if not name.startswith("notifications/") else {}),
                }
                for i, (name, params) in enumerate(calls, 1)
            ]
            result = subprocess.run(
                args,
                cwd=self.cwd,
                env=self.env,
                capture_output=True,
                encoding="utf-8",
                input="\n".join(map(json.dumps, requests)) + "\n",
                timeout=60,
            )
            replies = {obj["id"]: obj for obj in map(json.loads, result.stdout.splitlines())}
            print(f"$ skillporter {' '.join(args[1:])}\nexit={result.returncode}; response ids={list(replies)}")
            self.check(
                "MCP clean stdio and no reply to notification",
                result.returncode == 0 and set(replies) == {1, 3, 4, 5, 6, 7},
            )
            init = replies[1]["result"]
            tools = replies[4]["result"]["tools"]
            print(init, [tool["name"] for tool in tools])
            self.check(
                "MCP negotiation, ping and 18-tool inventory",
                init["protocolVersion"] == "2024-11-05"
                and init["serverInfo"]["writesEnabled"] == writes
                and replies[3]["result"] == {}
                and len(tools) == 18,
            )
            for i in (5, 6, 7):
                data = replies[i]["result"]
                excerpt = data["content"][0]["text"]
                self.log(f"{calls[i - 1][1]['name']}: isError={data['isError']}; {excerpt[:270]}")
                self.check("MCP call outcome", data["isError"] == (i == 6 and not writes))
            self.check(
                "MCP write gate reflected on disk",
                (dest.is_file() and dest.read_bytes() == (s / "SKILL.md").read_bytes())
                if writes
                else not dest.exists(),
            )

    def authoring(self):
        s = self.cwd / "draft-notes"
        self.run("new", s.name, "--with-references", "--with-tests")
        self.run("lint", s, "--strict")
        self.run("test", s)
        self.run("preview", s, "--harness", "cursor", "--adapt-format", "cursor-mdc")
        self.run("inspect", s, "--preview-adapt", "cursor-mdc")
        self.run("install", s, "--harness", "claude-code")
        self.run("validate", s, "--offline")
        for fmt in ("json", "sarif"):
            result = self.run("scan", s, "--offline", "--format", fmt)
            result_json = json.loads(result.stdout)
            self.check(
                f"valid {fmt} output", bool(result_json) and (fmt != "sarif" or result_json["version"] == "2.1.0")
            )
        bad = self.cwd / "bad-doc"
        bad.mkdir()
        (bad / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")
        self.run("validate", bad, "--offline", code=1)
        self.run("sandbox", "run", s)
        self.run("policy", "init")
        self.run("policy", "show")
        self.run("policy", "check")
        self.run("pack", s, "--out", self.root / "pack1")
        self.run("pack", s, "--out", self.root / "pack2")
        pack1 = self.root / "pack1"
        archives = list(pack1.glob("*.tar.gz"))
        (one,) = archives
        two = self.root / "pack2" / one.name
        a, b = one.read_bytes(), two.read_bytes()
        print(f"gzip mtime: {int.from_bytes(a[4:8], 'little')} vs {int.from_bytes(b[4:8], 'little')}")
        self.check("pack tar payloads are equal", gzip.decompress(a) == gzip.decompress(b))
        self.check("pack archives are byte-identical", a == b)
        self.run("add", one, "--harness", "cursor", "--isolated", "--offline")
        self.check(
            "local archive add installed scaffold bytes",
            (self.cwd / ".cursor/skills/draft-notes/SKILL.md").read_bytes() == (s / "SKILL.md").read_bytes(),
        )
        self.run("publish", s, "--registry", self.root / "registry.json", "--dry-run")
        self.check("publish dry-run did not create registry", not (self.root / "registry.json").exists())
        self.run("search", "pdf")
        self.run("info", "hermes", contains="Hermes")
        self.run("explain", "DRIFT")
        self.run("self-skill", "show", contains="skillporter")
        self.run("self-skill", "path")
        self.run("self-skill", "install", "--harness", "hermes")
        self.run("harness", "list")
        self.run("harness", "inspect", "cursor")
        self.run("harness", "status")
        self.run("detect", "--all", "--versions", full=True)
        self.run("matrix")
        report = self.root / "report.md"
        result = self.run("ci-report", "--format", "json", "--output", report, code=1)
        self.check(
            "CI reports bad-doc as a finding, stdout JSON and file Markdown",
            not json.loads(result.stdout)["healthy"] and "bad-doc" in report.read_text(encoding="utf-8"),
        )
        before = snapshot(self.cwd)
        self.run("demo")
        self.check("demo did not write into project", snapshot(self.cwd) == before)

    def instructions(self):
        doc = "# Team guide\n\n- Use pytest before handing off.\n"
        for name in ("AGENTS.md", "CLAUDE.md"):
            (self.cwd / name).write_text(doc, encoding="utf-8")
        (self.cwd / "pyproject.toml").write_text('[project]\nname = "sample-project"\n', encoding="utf-8")
        self.run("consolidate")
        self.check("consolidate preview did not change input", (self.cwd / "CLAUDE.md").read_text() == doc)
        self.run("consolidate", "--apply")
        self.run("consolidate", "--status")
        self.run("context", "--harness", "claude-code")
        self.run("consolidate", "--reconcile")
        self.run("consolidate", "--rollback")
        self.check(
            "rollback restored both guides", all((self.cwd / n).read_text() == doc for n in ("AGENTS.md", "CLAUDE.md"))
        )
        self.run("suggest")
        s = skill(self.root / "src", "release-notes")
        self.run("install", s, "--harness", "claude-code")
        self.run("insights", "--record-usage", "release-notes", "--harness-used", "claude-code")
        self.run("insights", contains="release-notes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", help="Absolute path to the preinstalled skillporter executable")
    parser.add_argument("--scratch", required=True, type=Path, help="Existing scratch parent directory")
    parser.add_argument("journeys", nargs="*")
    args = parser.parse_intermixed_args()
    totals = []
    local = ("lifecycle", "versions", "authoring", "instructions", "dependencies", "sources", "mcp")
    if set(args.journeys) - set((*local, "remote")):
        parser.error("journeys: " + ", ".join((*local, "remote")))
    for journey in args.journeys or local:
        print(f"\n=== {journey} ===")
        with tempfile.TemporaryDirectory(prefix="sp-verify-", dir=args.scratch.resolve()) as temp:
            p = Probe(Path(args.binary).resolve(strict=True), Path(temp))
            try:
                getattr(p, journey)()
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                p.log(f"BLOCKED: {exc}")
                p.failures.append("prerequisite")
            totals.extend(f"{journey}: {failure}" for failure in p.failures)
    print("\nAnomalies:", totals)
    return bool(totals)


if __name__ == "__main__":
    raise SystemExit(main())
