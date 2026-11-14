# CENSO-NO-MANIFESTO retro

## Brief quality

- The brief's numbers held when re-measured: 536 entries (46 catalogs, 490 baseline files), 69 of 107 units, every
  entry resolving to exactly one unit, 21 open non-draft PRs, 19 touching a shared file, 12 touching `CODEOWNERS`, and
  7 touching each `scripts.json`. The one clarification: "5 on average" is the mean over all 107 units (536/107). Over
  the 69 units that have entries, the mean is 7.8.
- Two parts of the brief pulled against each other. Step 2 put the census block in `unit.v1.json`, and step 3a said
  "pick ONE". The record went to `units/<id>/census.jsonl` (call C2), so step 2's schema became a new contract.
- The brief foresaw the cross-lane case in step 7, and it happened. `lane_errors` refuses a PR that touches the units
  of two lanes, and the TypeScript readers are tooling-lane. The migration and the final door therefore became program
  units (C8). `v3/queue.json` is not in the repository, so the documented in-repo path, `docs/programs/`, holds them.
- The brief's driver ("runs `scripts/generate codeowners` on the merged tree") assumed the merged tree is on disk when
  the driver runs. It is not: git merges in memory and calls the driver before it writes the worktree. The driver
  rebuilds the tree from `GITHEAD_<sha>` with `git merge-tree` (C10).

## Premises

| Premise | Held? |
|---|---|
| Every entry resolves to exactly one unit, so none changes hands | held. A dry run of `scripts/census migrate` over all 18 areas in a scratch worktree kept all 536 entries identical, filled 69 records and left 0 per-area files, and `scripts/census check` was green against the base |
| The absolute scan's `--list` output is enough to rebuild the baseline | held. Parsing it reproduces all 490 baseline files exactly |
| A merge driver can find the other side | held for `git merge` and `git pull` (`GITHEAD_<sha>`). A rebase or cherry-pick has no such variable, so the driver falls back to `git merge-file` |

## Failures and root-cause class

| Failure | Class | Fix |
|---|---|---|
| `config.check`: an object-typed registry parameter must be `x-text` | contract (the registry meta-schema reserves objects for locale text) | split into scalar keys (`census.<census>_legacy_dir`, `census.<census>_view_description`) |
| `literal_census`: `parents[2]` counted as a new `number 2` in the unit | code | `.parent.parent.parent` |
| `unit_check`: `engine-structure` imports `engine-census` undeclared | code | declared in `requires` |
| `unit_check`: a comment in the shell wrapper naming `apps/web/tsconfig.paths.json` counted as an import of `web-build` | code (a path mention in a shell file is an edge) | the comment names the file by its role |
| `defects`: adding paths to `engine-generate` changed the derived area of KD-024bbecb | contract (a derived record that only `scripts/defects` rewrites) | the driver became its own unit (C11) |
| The driver's first version merged `tsconfig.paths.json` with a conflict | code (the nested merge conflicted on the generated keys) | a renderer that keeps hand-written content declares `strip()`, so only that part is merged |

## Lessons

1. **A datum several units write belongs in each unit's folder, behind one command.** The census, `CODEOWNERS` and the
   `@ou` paths all failed the same way: a shared document. Check for the class: count the writer units per committed
   file (`scripts/census list` does it for the census); owner: engine-units.
2. **A merge driver never sees the merged tree on disk.** git merges in memory, so a driver that regenerates must
   rebuild the tree itself (`git merge-tree`) and must tell its nested call apart; owner: engine-generate.
3. **A shell comment that names another unit's file is an import.** The unit graph reads path mentions in shell
   files, so a wrapper describes a file by its role, not its path; owner: engine-units (exclude comments from the edge
   scan).
4. **A cross-lane program is found by the lane check, not by the plan.** A brief that touches readers in two lanes
   should be split before coding; `structure.lane_errors` on the planned file list would say so up front; owner:
   engine-coordinator.
