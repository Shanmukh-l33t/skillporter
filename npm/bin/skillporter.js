#!/usr/bin/env node
/**
 * Skillporter NPX Launcher
 *
 * Thin Node.js wrapper that delegates 100% of execution to the authoritative
 * Skillporter Python core (bundled `skillporter.pyz`, local `python3`/`python`,
 * or `uvx skillporter`). Never duplicates business logic.
 */

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const args = process.argv.slice(2);
const bundledPyz = path.join(__dirname, "skillporter.pyz");
const repoRoot = path.resolve(__dirname, "..", "..");

function hasCommand(cmd, checkArgs = ["--version"]) {
  const res = spawnSync(cmd, checkArgs, { stdio: "ignore" });
  return res.status === 0;
}

function runAndExit(cmd, cmdArgs, extraEnv = {}) {
  const res = spawnSync(cmd, cmdArgs, {
    stdio: "inherit",
    env: Object.assign({}, process.env, extraEnv),
  });
  if (res.error) {
    console.error(`skillporter launcher error: ${res.error.message}`);
    process.exit(2);
  }
  process.exit(res.status !== null ? res.status : 1);
}

// 1. Prefer bundled zero-dependency zipapp with python3 / python / py -3
if (fs.existsSync(bundledPyz)) {
  for (const py of ["python3", "python"]) {
    if (hasCommand(py)) {
      runAndExit(py, [bundledPyz, ...args]);
    }
  }
  if (process.platform === "win32" && hasCommand("py", ["-3", "--version"])) {
    runAndExit("py", ["-3", bundledPyz, ...args]);
  }
}

// 2. Fallback: run from source checkout if inside the repository
if (fs.existsSync(path.join(repoRoot, "skillporter", "__main__.py"))) {
  for (const py of ["python3", "python"]) {
    if (hasCommand(py)) {
      runAndExit(py, ["-m", "skillporter", ...args], { PYTHONPATH: repoRoot });
    }
  }
}

// 3. Fallback: delegate to uvx if installed
if (hasCommand("uvx")) {
  runAndExit("uvx", ["skillporter", ...args]);
}

console.error(
  "error: Skillporter requires Python 3.9+ or `uvx` in PATH.\n" +
    "Install Python from https://www.python.org/ or uv from https://docs.astral.sh/uv/"
);
process.exit(2);
