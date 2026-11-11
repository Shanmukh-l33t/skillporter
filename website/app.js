const HARNESS_DATA = [
  { id: "claude-code", name: "Claude Code", category: "coding", support: "NATIVE", ver: "INTEGRATION_TESTED", proj: ".claude/skills", user: "~/.claude/skills", shared: false },
  { id: "codex", name: "OpenAI Codex", category: "coding", support: "NATIVE", ver: "INTEGRATION_TESTED", proj: ".agents/skills", user: "~/.agents/skills", shared: true },
  { id: "cursor", name: "Cursor", category: "coding", support: "NATIVE", ver: "INTEGRATION_TESTED", proj: ".agents/skills (+3 compat)", user: "~/.agents/skills", shared: true },
  { id: "github-copilot", name: "GitHub Copilot", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".github/skills (+2 compat)", user: "~/.copilot/skills", shared: true },
  { id: "gemini-cli", name: "Gemini CLI", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".agents/skills (+1 compat)", user: "~/.agents/skills", shared: true },
  { id: "antigravity", name: "Google Antigravity", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".agents/skills (+1 compat)", user: "~/.gemini/config/skills", shared: true },
  { id: "windsurf", name: "Windsurf", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".windsurf/skills", user: "~/.codeium/windsurf/skills", shared: false },
  { id: "cline", name: "Cline", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".cline/skills (+3 compat)", user: "~/.cline/skills", shared: true },
  { id: "roo-code", name: "Roo Code", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".roo/skills (+1 compat)", user: "~/.roo/skills", shared: true },
  { id: "opencode", name: "OpenCode", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".opencode/skills (+2 compat)", user: "~/.config/opencode/skills", shared: true },
  { id: "zed", name: "Zed", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".agents/skills", user: "~/.agents/skills", shared: true },
  { id: "replit", name: "Replit Agent", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".agents/skills (+1 compat)", user: "~/.config/agents/skills", shared: true },
  { id: "junie", name: "JetBrains Junie", category: "coding", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".junie/skills (+1 compat)", user: "~/.junie/skills", shared: true },
  { id: "hermes", name: "Hermes Agent", category: "autonomous", support: "NATIVE", ver: "RUNTIME_VERIFIED", proj: ".hermes/skills", user: "$HERMES_HOME/skills", shared: false },
  { id: "openclaw", name: "OpenClaw", category: "autonomous", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".openclaw/skills (+2 compat)", user: "~/.openclaw/skills", shared: true },
  { id: "openhands", name: "OpenHands", category: "autonomous", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".agents/skills (+2 compat)", user: "~/.agents/skills", shared: true },
  { id: "goose", name: "Goose", category: "autonomous", support: "NATIVE", ver: "DOCUMENTATION_VERIFIED", proj: ".agents/skills (+1 compat)", user: "~/.agents/skills", shared: true },
  { id: "continue", name: "Continue", category: "coding", support: "COMPATIBLE", ver: "DOCUMENTATION_VERIFIED", proj: ".continue/skills", user: "~/.continue/skills", shared: false },
  { id: "aider", name: "Aider / AiderDesk", category: "coding", support: "ADAPTED", ver: "DOCUMENTATION_VERIFIED", proj: ".aider-desk/skills", user: "~/.aider-desk/skills", shared: false }
];

const TERMINAL_DEMOS = {
  add: `$ skillporter add Shanmukh-l33t/skillporter --harness all
SKILLPORTER

Source: github:Shanmukh-l33t/skillporter
Commit: ceb64c65cf5b

Found skills:
  skillporter

Target harnesses:
  Claude Code (claude-code)
  OpenAI Codex (codex)
  Cursor (cursor)
  Gemini CLI (gemini-cli)
  Hermes Agent (hermes)

Installation plan:
  3 destination(s) across 5 harness(es)
  2 shared destination(s) deduplicated (.agents/skills)

Validation: PASSED
Security assessment (static):
  0 informational/medium finding(s)
  0 critical/high finding(s)

Installing...

Claude Code            SUCCESS  (copy via .claude/skills)
OpenAI Codex           SUCCESS  (copy via .agents/skills)
Cursor                 SUCCESS  (shared path already installed for codex)
Gemini CLI             SUCCESS  (shared path already installed for codex)
Hermes Agent           SUCCESS  (copy via .hermes/skills)

Installation verified.`,

  diagnose: `$ skillporter diagnose .
skillporter 2.0.0 — diagnosing /workspace/acme-agent-repo (scope: project)

skills found: sec-auditor, api-reviewer

SKILL         claude-code     codex           cursor          windsurf
----------------------------------------------------------------------------
sec-auditor   yes             yes             yes             MISSING
api-reviewer  yes             DRIFT           DRIFT           yes

findings:
  - skill 'api-reviewer' has content drift across copies: .agents/skills/api-reviewer (8f91c2a0), .claude/skills/api-reviewer (e41209b1)
  - skill 'sec-auditor' is not visible to: windsurf (visible to: claude-code, codex, cursor)`,

  scan: `$ skillporter scan .
skillporter 2.0.0 — static security assessment

skillporter: PASSED  (sha256: 90c53f8a12b4)
  0 findings across all scanned files.

Note: Static scanning inspects patterns and symlinks; it does not guarantee runtime safety.`,

  matrix: `$ skillporter matrix
skillporter 2.0.0 — universal harness compatibility matrix (19 harnesses)

HARNESS         SUPPORT     VERIFICATION            PRIMARY PROJECT PATH
--------------  ----------  ----------------------  ------------------------------------
aider           ADAPTED     DOCUMENTATION_VERIFIED  .aider-desk/skills
antigravity     NATIVE      DOCUMENTATION_VERIFIED  .agents/skills (+1 compat)
claude-code     NATIVE      INTEGRATION_TESTED      .claude/skills
cline           NATIVE      DOCUMENTATION_VERIFIED  .cline/skills (+3 compat)
codex           NATIVE      INTEGRATION_TESTED      .agents/skills
continue        COMPATIBLE  DOCUMENTATION_VERIFIED  .continue/skills
cursor          NATIVE      INTEGRATION_TESTED      .agents/skills (+3 compat)
gemini-cli      NATIVE      DOCUMENTATION_VERIFIED  .agents/skills (+1 compat)
github-copilot  NATIVE      DOCUMENTATION_VERIFIED  .github/skills (+2 compat)
goose           NATIVE      DOCUMENTATION_VERIFIED  .agents/skills (+1 compat)
hermes          NATIVE      RUNTIME_VERIFIED        .hermes/skills
junie           NATIVE      DOCUMENTATION_VERIFIED  .junie/skills (+1 compat)
openclaw        NATIVE      DOCUMENTATION_VERIFIED  .openclaw/skills (+2 compat)
opencode        NATIVE      DOCUMENTATION_VERIFIED  .opencode/skills (+2 compat)
openhands       NATIVE      DOCUMENTATION_VERIFIED  .agents/skills (+2 compat)
replit          NATIVE      DOCUMENTATION_VERIFIED  .agents/skills (+1 compat)
roo-code        NATIVE      DOCUMENTATION_VERIFIED  .roo/skills (+1 compat)
windsurf        NATIVE      DOCUMENTATION_VERIFIED  .windsurf/skills
zed             NATIVE      DOCUMENTATION_VERIFIED  .agents/skills`
};

function renderHarnesses(filter = "all") {
  const tbody = document.getElementById("harness-tbody");
  tbody.innerHTML = "";
  HARNESS_DATA.filter((h) => {
    if (filter === "coding") return h.category === "coding";
    if (filter === "autonomous") return h.category === "autonomous";
    if (filter === "shared") return h.shared;
    return true;
  }).forEach((h) => {
    const tr = document.createElement("tr");
    const cls = h.support === "NATIVE" ? "badge-native" : "badge-compat";
    tr.innerHTML = `
      <td><strong>${h.name}</strong> <code>(${h.id})</code></td>
      <td>${h.category}</td>
      <td><span class="${cls}">${h.support}</span></td>
      <td><code>${h.ver}</code></td>
      <td><code>${h.proj}</code></td>
      <td><code>${h.user}</code></td>
    `;
    tbody.appendChild(tr);
  });
}

document.querySelectorAll(".install-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".install-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("install-cmd-text").textContent = btn.dataset.cmd;
  });
});

document.getElementById("copy-cmd-btn").addEventListener("click", (e) => {
  const txt = document.getElementById("install-cmd-text").textContent;
  navigator.clipboard.writeText(txt);
  e.target.textContent = "Copied!";
  setTimeout(() => { e.target.textContent = "Copy"; }, 1400);
});

document.querySelectorAll(".term-mode").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".term-mode").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("terminal-output").textContent = TERMINAL_DEMOS[btn.dataset.term];
  });
});

document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderHarnesses(btn.dataset.filter);
  });
});

document.getElementById("theme-toggle").addEventListener("click", () => {
  const html = document.documentElement;
  html.dataset.theme = html.dataset.theme === "dark" ? "light" : "dark";
});

document.getElementById("terminal-output").textContent = TERMINAL_DEMOS.add;
renderHarnesses("all");
