# Field review: does Hermes see the installed skill?

**Baseline:** `bdfb9e684f4f6a9eb9eafd6f94f6bd9446ec4511` (Skillporter 3.2.0), 2026-11-19. **Verdict: user scope passes; project scope passes only after the user trusts the project. Skillporter reports success before that condition is met.** The installer put the right bytes in both places. It is the visibility report, not the copy operation, that failed this check.

## What a user sees

| Action | Skillporter in the temporary project | Installed Hermes catalog, fresh process each time |
|---|---|---|
| Start empty; dry-run either install | `would install … to 1 destination(s)` | `[]` at start and after each dry-run |
| Install `field-user`, user scope | Created `$HERMES_HOME/skills/field-user`; bytes matched source; `diagnose`: `yes`; `doctor`: `HEALTHY` | `field-user` with description `Identify the user field fixture.` from **both** project and unrelated cwd |
| Remove `field-user` | One destination removed; original still present | `[]` |
| Install `field-project`, project scope, no trust decision | Created `.hermes/skills/field-project`; bytes matched source; `diagnose`: `yes`, “every skill is reachable and synchronized”; `doctor`: `HEALTHY (all checked skills reachable, valid, and hash-verified).` | `[]` **from the project itself**; also `[]` from the unrelated cwd |
| Trust only the fixture project in the disposable Hermes profile; no reinstall | No change to the installed file | `field-project` with description `Identify the project field fixture.` in project; `[]` from unrelated cwd |
| Remove `field-project` while still trusted | One destination removed; original still present | `[]` in project |

All commands exited 0, **including the empty Hermes listings**. The result is the presence of the named row, not the exit code. The trust-setting step was performed by the auditor, not by Skillporter. Installing must not grant trust on the user's behalf.

[README matrix](../../README.md#harness-support-matrix-19-harnesses) puts one `RUNTIME_VERIFIED` label beside both paths. The [evidence guide](../harnesses/README.md#what-runtime-verified-means-here) expressly excludes Hermes from the prior two-scope observations; the [adapter](../../skillporter/harnesses.py) records a tier and paths, not the trust decision for this cwd. A historical adapter test can be true while today's installed skill is invisible. Qualify project support in the matrix/guide and distinguish “installed at the expected path” from “listed by Hermes” in diagnostics. If trust or live discovery is not checked, say so rather than promising reachability.

## Why test the receiving agent?

Primary sources checked via public GitHub issue API / raw documentation (no account or install):

- [NousResearch/hermes-agent #48975](https://github.com/NousResearch/hermes-agent/issues/48975) describes the intended boundary: non-interactive surfaces inherit a prior decision for the canonical project, otherwise no project skills. This is a design requirement, not a reason to bypass trust. The local experiment varied just that decision.
- [openai/codex #20637](https://github.com/openai/codex/issues/20637): a user reports that `npx skills ls -g --json` listed a skill with entry file `SKILL.MD` that did not appear in their Codex session. [#11314](https://github.com/openai/codex/issues/11314) is a separate, closed report for CLI v0.98.0 on macOS: a symlinked `.agents/skills` root was invisible; a real directory worked. These are reports about specific versions, not findings about current Codex on this host.
- [Vercel Labs skills CLI](https://github.com/vercel-labs/skills/blob/main/docs/commands.md) already offers local-source install, project/global scope, agent selection, listing and `--copy` instead of symlinks. For one Hermes profile a plain directory copy is also a meaningful baseline: discovery changed here without a hub registration step. Installer inventory is not an independent oracle. These sources establish a real failure mode and alternatives, not demand for another package manager.

## Exact replay

Windows 11 build 26300, Python 3.14.9 in the installed Hermes environment `89e173cd6c7e4858b4c8613c7df6eb61`. SHA-256 of installed `tools/skills_tool.py`: `492d1cc49f0f3e982aed98c8538d455988c06b376fb4560f473f6c1f602c3154`; `agent/skill_utils.py`: `9b643866caf9b0db3b568045e2b49bf2903f89197497c815a492afec89b33722`. No dependency installation. `find_all_skills()` is the installed catalog implementation called by Hermes's `skills_list`, with normal platform/disabled/trust filtering. No roots injected, no mock, no Skillporter discovery code used as the oracle. This exercises discovery, **not** prompt inclusion, skill activation, model quality, or hot reload.

From the baseline checkout, using that environment's Python, save the block as `field.py` **outside the repo in a disposable scratch directory** and run `python -B "<scratch>/field.py"`. Each child receives an allowlisted environment, a synthetic home and a distinct, initially empty `HERMES_HOME`. Both working directories, config and source files are disposable. No model, service, live profile, credential store, package registry or exploit test is required. The CLI entry point is the checkout via `PYTHONPATH`, not a globally installed Skillporter. The `-I` Hermes child ignores that path. Text columns in the table omit only unrelated output and the random temporary prefix.

```python
import importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path

repo = Path.cwd()
hermes = Path(importlib.util.find_spec('hermes_cli').origin).parents[1]
probe = """from pathlib import Path
import os, sys, json
sys.path.insert(0, sys.argv[1])
from tools.skills_tool import skill_search_dirs, find_all_skills
roots, active = skill_search_dirs()
assert active.resolve() == (Path(os.environ['HERMES_HOME'])/'skills').resolve()
assert all(d.resolve().is_relative_to(Path(sys.argv[2])) for _, d in roots)
print(json.dumps(find_all_skills()))"""
with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
    t = Path(tmp).resolve()
    p, q, h, profile = [t/n for n in ('project', 'other', 'home', 'profile')]
    for d in (p, q, h, profile, t/'tmp'): d.mkdir()
    (p/'.git').mkdir()  # nearest Git root marker, no remote or hooks
    env = {k: os.environ[k] for k in ('SystemRoot','WINDIR','COMSPEC') if k in os.environ}
    env.update(HOME=str(h), USERPROFILE=str(h), HERMES_HOME=str(profile),
               APPDATA=str(h/'roaming'), LOCALAPPDATA=str(h/'local'),
               TEMP=str(t/'tmp'), TMP=str(t/'tmp'), TMPDIR=str(t/'tmp'),
               PATH=str(Path(sys.executable).parent), PYTHONPATH=str(repo), PYTHONUTF8='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    def run(*args, cwd=p):
        cp = subprocess.run([sys.executable,'-B',*args], cwd=cwd, env=env,
                            capture_output=True, encoding='utf-8', stdin=subprocess.DEVNULL, timeout=60)
        print(cp.returncode, cp.stdout.strip(), cp.stderr.strip())
        return cp
    def catalog(cwd=p): return run('-I','-X','utf8','-c',probe,str(hermes),str(t),cwd=cwd).check_returncode()
    def sp(*args): return run('-m','skillporter',*args)
    catalog()
    for scope in ('user','project'):
        name = 'field-'+scope
        src = t/'source'/name
        src.mkdir(parents=True)
        md = src/'SKILL.md'
        md.write_text(f'---\nname: {name}\ndescription: Identify the {scope} field fixture.\n---\n# Field fixture\nPlain text only.\n', encoding='utf-8')
        flags = ('--harness','hermes','--scope',scope)
        sp('install',str(src),*flags,'--dry-run')
        catalog()
        sp('install',str(src),*flags)
        dest = (profile if scope=='user' else p/'.hermes')/'skills'/name/'SKILL.md'
        print('same bytes:', dest.is_file() and dest.read_bytes()==md.read_bytes())
        sp('diagnose','.',*flags)
        sp('doctor','.',*flags)
        catalog(); catalog(q)
        if scope=='project':
            (profile/'config.yaml').write_text(json.dumps({'skills':{'trusted_project_dirs':[p.as_posix()]}}),encoding='utf-8')
            catalog(); catalog(q)
        sp('remove',name,*flags,'-y')
        print('destination/source exist:', dest.exists(), md.exists())
        catalog()
```

## Acceptance checks for a separate re-audit (not sign-off on a fix)

1. Record candidate SHA, OS and Hermes build. Run the replay from the candidate with a newly empty home; reject a run if a root escapes the fixture, an unexpected fixture name appears before install, or a child errors. Do not reuse this run's trust decision.
2. Require the user-scope exact name and description in both cwds after install, neither before install nor after removal. Require byte equality, the correct profile destination, and source preservation. A green installer exit alone fails this gate.
3. For project scope require **absent → present → absent** in the project catalog across untrusted install, explicit fixture trust and removal. Require absence in the unrelated cwd even while trusted. No install/diagnostic may change the profile's trust settings. Do not broaden trust or copy the skill globally to make this pass.
4. On the untrusted leg compare `diagnose` and `doctor` text **and their `--json` variants** with the empty catalog. Accept either an accurate trust/visibility result or a clearly labelled filesystem-only result with runtime discovery unknown. Fail unqualified “reachable”/“verified” for this installation. Check the README and harness guide for the same scope and prerequisite; on the trusted leg require actual Hermes evidence for any claim of observed discovery.
5. Do not generalize this result to the other 18 adapters. Any new runtime promotion needs that harness's own listing or equivalent, version, scope, prerequisites, and a negative control. No other harness, package channel, security guarantee or live session was independently certified here.
