"""Measure checkout CLI reads on temporary synthetic workspaces (Ubuntu/Linux)."""

from __future__ import annotations

import argparse
import csv
import errno
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path

COMMANDS = ("status", "diagnose", "list")
REPO = Path(__file__).resolve().parents[1]
DANGLING = "dangling-scale-link"
HARNESS_PATH = ".agents/skills"


def fixture(project: Path, size: int) -> bool:
    records = {}
    for i in range(size):
        name = f"scale-{i:06d}"
        description = "" if i % 10 == 9 else "description: Synthetic skill. Use when measuring scale.\n"
        files = {
            "SKILL.md": f"---\nname: {name}\n{description}---\n\nSynthetic benchmark skill.\n".encode(),
            "assets/examples/data.txt": b"example\n" * 32,
            "references/deep/guide.md": b"# Benchmark notes\n" * 16,
        }
        shared = project / HARNESS_PATH / name
        claude = project / ".claude/skills" / name
        destinations = [shared, claude] if i % 5 == 0 else [shared]
        for dest in destinations:
            for rel, content in files.items():
                path = dest / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                edited = dest == claude and i % 10 == 0 and rel == "references/deep/guide.md"
                path.write_bytes(content + b"edited\n" if edited else content)
        if i % 2 == 0:
            # Seed the persisted tree hash of the shared copy, not the edited copy.
            hashes = "".join(f"{path}:{sha256(data).hexdigest()}\n" for path, data in sorted(files.items()))
            records[name] = {
                "name": name,
                "source": f"./{HARNESS_PATH}/{name}",
                "tree_hash": sha256(hashes.encode()).hexdigest(),
                "harnesses": ["codex", "cursor"] + (["claude-code"] if claude in destinations else []),
                "destinations": [str(dest) for dest in destinations],
            }
    state = project / ".skillporter/state.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"schema_version": 1, "skills": records}), encoding="utf-8")
    (project / "skillporter.yaml").write_text("harnesses: [codex, cursor]\n", encoding="utf-8")
    try:
        (project / HARNESS_PATH / DANGLING).symlink_to("no-such-skill")
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP}:
            raise
        print(f"symlink skipped: {exc.strerror}", file=sys.stderr)
        return False
    return True


def verify_json(command: str, stdout: Path, size: int, broken: bool) -> None:
    data = json.loads(stdout.read_bytes())
    names = {f"scale-{i:06d}" for i in range(size)}
    managed = {f"scale-{i:06d}" for i in range(0, size, 2)}
    drifted = {f"scale-{i:06d}" for i in range(0, size, 10)}
    if command == "status":
        assert set(data["discovered_skills"]) == names and set(data["managed_skills"]) == managed
        assert set(data["drifted_skills"]) == drifted
        assert sum(not skill["valid"] for skill in data["skills"].values()) == size // 10
        assert all(set(skill["installed_harnesses"]) >= {"codex", "cursor"} for skill in data["skills"].values())
    elif command == "diagnose":
        assert set(data["skills"]) == names and set(data["drifted"]) == drifted
        assert any(DANGLING in finding for finding in data["findings"]) == broken
    else:
        assert len(data) == size and {row["name"] for row in data} == names
        assert {row["name"] for row in data if row["managed"]} == managed


def measure(
    project: Path, env: dict[str, str], timeout: float, command: str, flags: list[str]
) -> tuple[list[str | int], Path]:
    out, err, rss = (project.parent / name for name in ("stdout", "stderr", "rss"))
    rss.unlink(missing_ok=True)
    argv = [
        "/usr/bin/timeout",
        "--verbose",
        "--kill-after=5s",
        f"{timeout}s",
        "/usr/bin/time",
        "-f",
        "%M",
        "-o",
        str(rss),
        sys.executable,
        "-B",
        "-S",
        "-m",
        "skillporter",
        command,
        ".",
        "--no-color",
        *flags,
    ]
    with out.open("wb") as stdout, err.open("wb") as stderr:
        started = time.perf_counter()
        result = subprocess.run(
            argv, cwd=project, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, check=False
        )
        seconds = time.perf_counter() - started
    with out.open("rb") as stdout:
        lines = sum(chunk.count(b"\n") for chunk in iter(lambda: stdout.read(65536), b""))
    with err.open("rb") as stderr:
        stderr.seek(max(0, err.stat().st_size - 4096))
        tail = stderr.read().decode("utf-8", errors="replace").splitlines()
    timed_out = any(line.startswith("/usr/bin/timeout: sending signal ") for line in tail)
    rss_kib = "" if timed_out or not rss.is_file() else rss.read_text(encoding="ascii").strip().rpartition("\n")[2]
    return [
        "timeout" if timed_out else "exit",
        result.returncode,
        f"{seconds:.3f}",
        out.stat().st_size,
        lines,
        rss_kib,
        err.stat().st_size,
        tail[-1] if tail else "",
    ], out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100, 1000, 5000])
    parser.add_argument("--commands", nargs="+", choices=COMMANDS, default=list(COMMANDS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60, help="seconds per CLI run")
    args = parser.parse_args()
    tools = (Path("/usr/bin/time"), Path("/usr/bin/timeout"))
    if sys.platform != "linux" or not all(tool.is_file() for tool in tools):
        parser.error("requires Linux with GNU /usr/bin/time and /usr/bin/timeout (e.g. WSL Ubuntu)")
    if not (REPO / "skillporter").is_dir():
        parser.error(f"no skillporter package beside the script; run it from a checkout root ({REPO})")
    if min(args.sizes) < 10 or args.repeats < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("sizes must be >= 10, repeats >= 1, and timeout positive and finite")

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "case",
            "skills",
            "command",
            "format",
            "run",
            "result",
            "exit",
            "seconds",
            "stdout_bytes",
            "stdout_lines",
            "peak_rss_kib",
            "stderr_bytes",
            "stderr_last_line",
        ]
    )
    with tempfile.TemporaryDirectory(prefix="skillporter-scale-") as directory:
        base = Path(directory).resolve()
        shutil.copytree(REPO / "skillporter", base / "src/skillporter", ignore=shutil.ignore_patterns("__pycache__"))
        for index, size in enumerate(args.sizes):
            with tempfile.TemporaryDirectory(dir=base) as sandbox:
                root = Path(sandbox)
                project, home = root / "project", root / "home"
                home.mkdir()
                env = {
                    "HOME": str(home),
                    "PATH": str(home),
                    "TMPDIR": str(home),
                    "LC_ALL": "C.UTF-8",
                    "PYTHONPATH": str(base / "src"),
                    "PYTHONHASHSEED": "0",
                    "SKILLPORTER_OFFLINE": "1",
                }
                broken = fixture(project, size)
                checked = set()
                for run in range(1, args.repeats + 1):
                    for command in args.commands:
                        for fmt, flags in (("text", []), ("json", ["--json"])):
                            metrics, stdout = measure(project, env, args.timeout, command, flags)
                            writer.writerow(["mixed", size, command, fmt, run, *metrics])
                            sys.stdout.flush()
                            print(f"note: {size} {command} {fmt} run {run} {metrics[0]}", file=sys.stderr, flush=True)
                            if fmt == "json" and metrics[0] == "exit" and command not in checked:
                                assert metrics[1] == (0 if command == "list" else 1), metrics
                                verify_json(command, stdout, size, broken)
                                checked.add(command)
                if index == 0:
                    # A corrupt project manifest stops discovery entirely on the baseline.
                    (project / "skillporter.yaml").write_text("{\n", encoding="utf-8")
                    for command in args.commands:
                        metrics, _ = measure(project, env, args.timeout, command, ["--json"])
                        writer.writerow(["invalid-project-manifest", size, command, "json", 1, *metrics])
                        sys.stdout.flush()


if __name__ == "__main__":
    main()
