# Removal verification: preview and action parity

`skillporter remove` / `uninstall` deletes files, so the dry run has to describe the same decisions the real run makes. This page records the failure that broke that promise, the fix, and the evidence.

## The failure

`remove` had two planners:

- `commands/remove.py::_planned_rows` walked each target harness's own paths (primary plus non-compatibility secondary paths) and printed `would-remove` for anything on disk.
- `install.py::uninstall` computed its own decisions, which knew about recorded ownership, `--isolated`, custom harness paths, and nested (recursive) destinations.

The two disagreed in both directions. Measured against a temporary workspace:

| Layout | Preview | Actual removal |
|---|---|---|
| `codex` + `cursor` both on shared `.agents/skills` | `would-remove .agents/skills/sample` | `preserved-shared` (correct) |
| Cursor installed with `--isolated` | `would-remove .agents/skills/sample` + `.cursor/skills/sample` | only `.cursor/skills/sample` removed |
| Cursor installed under a custom path | `would-remove .agents/skills/sample` | `custom/skills/sample` removed, the default path kept |
| Two owners sharing one custom path | `not-installed` for the shared path | `preserved-shared` |

A second defect hid in the follow-up state: a partial removal trimmed `state.json` but left `skillporter.yaml` / `skillporter.lock` naming the removed harness whenever the manifest spec had no explicit `harnesses` list (it inherited the project default). The next `sync` then reinstalled the skill for the harness the user had just removed.

## The fix

- One planner. `install.py::_plan_uninstall` returns the complete decision list for `(skill, targets, scope)`. `uninstall(..., dry_run=True)` returns that list, and `_planned_rows` renders it with the preview labels (`would-remove`, `preserved-shared`, `not-installed`). The dry run does no writes: no state, manifest, lock, audit, or transaction recovery.
- Ownership first. Before planning, the planner maps every *other* owner's install destination for the skill: recorded harnesses for a managed skill, active detected harnesses (marker-based, never `PATH`) for an unmanaged one. Any destination that another owner installs into is `preserved-shared` in the preview and untouched by the real run.
- Same path set on both sides. Custom overrides (`skillporter.yaml`, `SKILLPORTER_HARNESS_PATHS`, `--custom-path`), `--isolated` installs, nested recursive destinations, and non-shared secondary paths are all resolved by the same helper used by `install`, so preview and action cannot drift again.
- Ownership-safe state. Destinations are dropped from `state.json` only when nothing else still points at them, a symlink unlink never removes its target, and the manifest/lock trim runs under the same `workspace_lock` as the state update with the *remaining* owners read back from state. A manifest spec with inherited harnesses is rewritten with the surviving harnesses instead of keeping the removed one.

## Evidence

Temporary project and home (nothing outside the temp directory is touched):

```
skillporter init <ws>                         # manifest harnesses: codex, cursor
skillporter add <src> --harness codex         # .agents/skills/sample
skillporter add <src> --harness cursor --isolated --force
skillporter add <unrelated> --harness codex   # .agents/skills/unrelated (marker)
skillporter lock <ws>
```

Shared layout (`codex` and `cursor` on `.agents/skills`):

```
dry-run: [('cursor', '.agents/skills/sample', 'preserved-shared')]
actual:  [('cursor', '.agents/skills/sample', 'preserved-shared')]
state:   ['codex'] ['.agents/skills/sample']
manifest: sample harnesses ['codex']   lock: ['codex']
marker:  True           (bytes and mtime unchanged)
sync:    state ['codex'] / manifest ['codex'] / lock ['codex'], marker unchanged
```

Isolated layout (`cursor` on `.cursor/skills`, `codex` on `.agents/skills`):

```
dry-run: [('cursor', '.cursor/skills/sample', 'would-remove'), ('cursor', '.agents/skills/sample', 'preserved-shared')]
actual:  [('cursor', '.cursor/skills/sample', 'removed'),      ('cursor', '.agents/skills/sample', 'preserved-shared')]
state:   ['codex'] ['.agents/skills/sample']
manifest: sample harnesses ['codex']   lock: ['codex']
marker:  True           (bytes and mtime unchanged)
sync:    state ['codex'] / manifest ['codex'] / lock ['codex'], marker unchanged
```

The source skill is never a destination and survives every case (`sha256` unchanged). After removing the last owner, `state.json`, `skillporter.yaml` and `skillporter.lock` all drop the skill, and a following `sync` does not recreate it.

## Regression tests

```bash
python -m pytest tests/test_remove_update_fixes.py -k remove
```

- `test_remove_preview_matches_action_and_next_sync[shared|isolated|custom|custom-shared]` — for each layout: dry run writes nothing, preview equals the real action list, the surviving owner's copy and an unrelated marker skill keep their bytes and mtimes, state/manifest/lock agree with each other, `sync` changes nothing, and a final full removal leaves no residue anywhere.
- `test_remove_ignores_custom_override_that_was_not_used_for_install` — an override that holds no copy of the skill never causes content there to be deleted, and unrelated skills under that path stay intact.
- Existing suites that pin the old guarantees: `tests/test_adapter_conformance.py::test_shared_agents_skills_removal_preserves_other_owning_harnesses`, `tests/test_scanner_registry_fixes.py::test_remove_unmanaged_*`, `tests/test_redteam_audit_fixes.py::test_remove_purge_source_preserves_remaining_owners_and_avoids_compat_noise`.

## Known limits

- For an unmanaged skill (no `state.json` record) ownership is inferred from adapters detected in the workspace or home. A harness that reads `.agents/skills` but leaves no marker in the project is not counted, so its copy can be removed.
- A managed owner keeps the shared copy alive through its install path. A harness that only *reads* that directory through a compatibility path is not counted as an owner.
- The preview reports the skill-wide picture for the selected targets only; it does not simulate filesystem failure (permissions, `EBUSY`) that can stop the real run partway.