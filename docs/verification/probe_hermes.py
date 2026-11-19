"""Verify installed Hermes skill loading and MCP discovery without a model or real config."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from probe import Probe, skill

CLI = "from hermes_cli.main import main; raise SystemExit(main())"
VIEW = """import json, sys
from tools.skills_tool import skill_view
r = json.loads(skill_view(sys.argv[1], preprocess=False))
print(json.dumps({k: r[k] for k in ('success', 'name', 'skill_dir', 'content', 'error') if k in r}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="Published Skillporter executable")
    parser.add_argument("hermes_python", type=Path, help="Python executable from installed Hermes environment")
    parser.add_argument("--scratch", type=Path, required=True, help="Existing scratch parent directory")
    args = parser.parse_args()
    python = args.hermes_python.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="sp-hermes-", dir=args.scratch.resolve()) as temp:
        p = Probe(args.binary.resolve(strict=True), Path(temp))
        subprocess.run(["git", "init", "-q"], cwd=p.cwd, env=p.env, check=True, timeout=30)
        p.run("-I", "-c", CLI, "--version", binary=python)
        for scope in ("project", "user"):
            name = f"sp-hermes-{scope}"
            body = f"Render a short release summary. Marker: {scope}-release-notes."
            src = skill(p.root / "src", name, body=body)
            p.run("add", src, "--harness", "hermes", "--scope", scope, "--offline")
            target = p.cwd / ".hermes" if scope == "project" else Path(p.env["HERMES_HOME"])
            installed = target / "skills" / name / "SKILL.md"
            p.check(f"{scope} installation copied fixture", installed.read_bytes() == (src / "SKILL.md").read_bytes())
            if scope == "project":
                before = p.run("-I", "-c", VIEW, name, binary=python)
                p.check("untrusted project skill not loaded", not json.loads(before.stdout)["success"])
                p.run("-I", "-c", CLI, "skills", "trust", binary=python)
            after = p.run("-I", "-c", VIEW, name, binary=python)
            viewed = json.loads(after.stdout)
            p.check(
                f"Hermes runtime resolved {scope} skill and exact body",
                viewed["success"] and body in viewed["content"] and Path(viewed["skill_dir"]) == installed.parent,
            )
        p.run("-I", "-c", CLI, "skills", "list", "--source", "local", binary=python)
        # This is a new fixture config in the disposable profile, not the user's config.
        config = Path(p.env["HERMES_HOME"]) / "config.yaml"
        config.write_text(
            json.dumps(
                {"mcp_servers": {"skillporter": {"command": str(p.binary), "args": ["mcp", "--root", str(p.cwd)]}}}
            ),
            encoding="utf-8",
        )
        p.run("-I", "-c", CLI, "mcp", "test", "skillporter", binary=python, contains="Tools discovered: 18")
        print("\nAnomalies:", p.failures)
        return bool(p.failures)


if __name__ == "__main__":
    raise SystemExit(main())
