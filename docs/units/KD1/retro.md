# KD1 retro: known base defects as a structural process (PR #572)

Facts with evidence, from the initial brief to the accepted gate. Times are UTC (the brief's clock is UTC-3, so 00:10
there is 03:10 here). Commit times come from `git log`; the token counts are the session's own meter (15.0 M at start).

## 1. Brief quality

| Finding | Evidence | Effect | Fix that would have prevented it |
|---|---|---|---|
| **Ambiguous: "reuse GS1's per-test cache".** GS1's cache stores a PASS marker per script test (`gate_test_cache.py`); it cannot hold "failed on the base with signature S". | `gate_test_cache.record` refuses an empty key and stores only passes | A sibling cache (`defect_detect.outcome`, key = base sha + test id) on the same storage port. Cheap, but the brief implied a reuse that does not exist | Brief: "the base outcome (pass/fail + signature) is a new marker kind next to GS1's". Owner: A Torre |
| **Wrong: seed ids and signatures typed in the brief.** The brief names `premises.test.sh > Repository.test_repository_register_is_valid` and the human wording of the signature. The gate's id for a script test is the script path and its signature is `AssertionError: Items in the first set but not the second:` (measured). | `defect_detect.rerun` on `974cab54` (`/tmp` seed run, 48 s for both) | Seeds use the measured values; the brief's wording is kept as `summary` | Brief: "signatures are measured by the gate, never typed". Owner: A Torre |
| **Ambiguous: "owner from map (S1 area)".** The map gives `engine-premises` / `engine-generate`, both owned by `engine-lane`; there is no S1 owner. | `scripts/defects list` | None (derived) | Name the expected owner only as a check, not as a requirement |
| **Missing: how the gate closes a defect.** "The gate closes it automatically" cannot write a repo file from a PR checkout. | gate runs in a detached checkout | Design added `defect.*` events plus `scripts/defects sync`; the trigger (maestro) is outside the repo | Brief should say where registry writes are committed, or accept the sync seam. Owner: A Torre |
| **Missing: which D-069 "rows".** D-069 has sixteen principles; the brief did not say which. | `docs/process/principles/D-069.md` | I first wrote "D-069 item 15" (which is user-facing text) in code, config and docs; found after commit 7, corrected in commit 8 | Name the items in the brief |
| **Conflicting process orders.** Six process messages in ~15 minutes (00:10, 00:14, 00:15, 00:16, 00:23, 00:24) and three more later (status, ETA). Each replaced the previous one on where the Plan lives. | session transcript | The PR was opened early with a docs-only CAP-012 commit; audit.md and plan.md became commits 2-3; the PR body was rewritten twice | One process message per change, with a version; the lane reads it once. Owner: A Torre |

## 2. Audit and plan

- Audit: read-only reads plus 2 single-test runs in parallel (`premises.test.sh` 41 s, `generate.test.sh` 4 s). It found GS1's cache, `gate_failures` signatures, the unit map and the quarantine as the closest pattern. It did not find that a config key needs its reader to exist (found by a failing test, F1).
- Premises (see `plan.md`): the **high** premise (a failing script test is comparable on the base by its normalized signature) held: the same `gate_failures.script_failures` function produced both signatures. The **medium** premise (throwaway worktree works with the PR toolchain) held after one addition: the worktree needs the `apps/web/node_modules` symlink (`generate.test.sh` runs the web package). Owner premise held. The v3 schema premise held (`max(version)` in the port; `gate_events` now emits v3).
- Plan changes: 7 → 8 commits. Audit and plan became commits 2 and 3 by order; router and lifecycle were merged into commit 7; the plan's per-commit tests listed `structure-check` only for commit 8, which let commits 5 and 6 go out with 8 `structure-check` errors (missing `requires` in the new unit manifest, missing `assets.json` entry, unit import cycle declarations). Fixed in commit 7 (one commit, substantive, so no fix-up).

## 3. Execution

Commit timeline (UTC, from `git log`): 03:14 CAP-012 · 03:17 audit · 03:17 plan · 03:18 contracts · 03:24 registry · 03:28 detection · 03:37 router + lifecycle + structure · 03:40 seed + docs. About 26 minutes from the first commit to the last, after the audit and the process messages above. Quota: about 0.3 M of 15.0 M tokens used up to the gate launch; the router sub-agent used 107 K of its own.

Failures, each with its root-cause class:

| # | What failed | Class | Why | Rework | Prevention (owner) |
|---|---|---|---|---|---|
| F1 | `config.test.sh` 33 failures after adding `config/registry/defects.json` | **Registry entry before its reader**: `test_every_entry_is_typed_documented_owned_and_read` needs each `x-readers` file to exist | I wrote the full registry first | Split the registry per commit: each commit adds only the keys its module reads; wait ~3 min per config run | A helper `scripts/config add-keys` that refuses a reader that does not exist, or the config checker run by the commit hook (engine lane) |
| F2 | `test_events_md_and_the_schemas_name_the_same_events` | **Catalog needs prose**: EVENTS.md must name every event | Added schemas without rows | 6 rows in EVENTS.md | `event_contracts.py lock` could print the missing EVENTS.md rows (engine lane) |
| F3 | 9 errors in the first `test_defects.py` run | **Unfamiliar API order**: `json_schema.errors(instance, schema)` | I assumed `(schema, instance)` | 2-line fix | Both callers (`validate`, `errors`) take the schema first; make `errors` match (engine lane) |
| F4 | CLI test on a temp root failed | **Fixture assumption**: `derive_owner` needs a git root | I used a subprocess on a non-git temp dir | Test calls `main()` in process | None needed; a registry `--root` helper could take `files=` (low value) |
| F5 | `structure-check` errors on pushed commits 5 and 6 (8 errors) | **Check not run per commit**: unit `requires` and `assets.json` | The plan ran `structure-check` only at commit 8 | Fixed in commit 7 | The commit plan template should list the structure stage per commit; or the auto-push hook runs `structure-check` (engine lane) |
| F6 | "D-069 item 15" cited for the wrong principle | **Assumed a number instead of reading the list** | I did not read the D-069 headings before citing | `sed` across 10 files, one over-replacement reverted by hand | A check that every `D-069 item N` reference matches the heading text of item N (structure owner) |
| F7 | `gate-local` printed `GATE: FAILED` even when the report said PASS | **Exit-code authority split** between the shell variable and the report | `failed` stayed non-zero | `if report; then failed=0` (gate change, D-069) | Found by reading, no test failed: add a gate-local test that feeds a report returning PASS for a failed stage (gate owner) |
| F8 | `gate-local.test.sh` "a registry value of another ceiling changes it" fails in my ad-hoc shell, on the clean base too | **Environment**: outside the gate's hermetic env the shared config store needs a GitHub credential (`config.StoreError: unknown schema envelope.v1.json`) | Not mine. It passed inside the gate (cached PASS in run 2), so it is a base defect of the *shell*, not of the gate; I reported it as a "third base defect" in a STATUS comment before knowing that | Reproduced on a base worktree (3.7 s) | Run the targeted test through the gate's env wrapper, not a bare shell; `hermetic.install` should pin the store in this test (engine lane) |
| F9 | Gate run 1: `structure check` failed, 4 errors: the defect registry files had no `assets.json` entry | **Untracked files escape the check**: my local `structure-check` ran before `git add`, and the check reads tracked files only | One more commit (inventory entry) and a second gate | Run `structure-check` after `git add`, or make it read `git ls-files --others --exclude-standard` too (engine lane) |
| F10 | Gate run 1: `forge-events.test.sh` 2 failures | **A test pinned the newest version of an evolving schema as a literal** (`gate.passed` v2); v3 (`known_defects`) broke it | One commit; tests now take the newest version from the catalog | A `grep` for `['version']` pins found one more of mine (`test_defect_detect.py`, same class, fixed in the same commit) and `test_config_api.py:77` (`config.changed` v1, not touched, it breaks when that event gains a version); add the catalog helper to `event_contracts` so a test cannot repeat it (engine lane) |
| F11 | Gate verdict correct but `stages.json` rewritten without the known defects | **Two writers of one report**: the exit trap's 3-argument call overwrote the verdict call's file | Found by comparing the report with the posted verdict; fixed with a guard and two pinning checks in `gate-local.test.sh` | One writer per artifact (gate owner) |

Dead ends and waits: four `Monitor` watches (4–5 min each) expired without events because the test they watched had been started in a task whose completion notice I should have waited for instead; one `sleep 60` blocked by the harness; one wrong tool name. The 120 s foreground limit moved `config.test.sh` to the background twice. The router sub-agent (worktree, ~3.6 min, 107 K tokens) ran while I wrote detection; its cherry-pick merged without conflict, but it left three registry keys that duplicate existing facts (`base_branch`, `base_ref_candidates`, plus my own `base_ref`), which I removed in favor of `gate.batch_base_ref` and `train.base_branch`.

## 4. Gate

| Run | Head | Result | Time | What it showed |
|---|---|---|---|---|
| 1 | `c9408948` | FAILED | 493.9 s (script tests 315.6 s, structure 39.4 s; cold per-test cache, full script suite because the selector files changed) | structure: 4 assets errors (F9); script tests: `forge-events` (F10), `structure-check.test.sh` (F9), and the two seeded defects. The verdict `gate.failed` v3 listed `known_defects` KD-024bbecb and KD-4db6e693 next to 4 own failing tests: **only the PR's own failures blocked** |
| 2 | `d7c8bb1e` | **PASSED** | 128.0 s (under the 180 s ceiling; script tests 73.6 s, warm cache) | `scripts/tests/generate.test.sh` and `scripts/tests/premises.test.sh` still FAIL in the stage log; both fail on the base `974cab54` with the same signature (re-run in a throwaway worktree, cached per base sha), so the stage is reported PASS and `gate.passed` v3 lists them under `known_defects` |
| 3 | `a87cbb6e` | **PASSED** | 102.0 s (script tests 43.0 s, structure 41.2 s) | the head after the gate-local guard (`ddf5740b`, pushed after run 2 had passed, so run 2's pass did not cover it) and the first retro; same two excused defects |
| 4 | the head that adds the lessons below | recorded in the PR comment RETRO | docs only | a commit that only edits `retro.md` changes the head, so it is gated again before the merge |

Known base defects seen: the two seeded ones (as designed). No third base defect in the gate (F8 was my shell).
Number of gates: 3 before this paragraph was last edited (1 red, 2 green), plus run 4. Gate runs before the accepted one: 1 red. Targeted runs: `event-contracts` ×3, `config` ×3, `defects`/`defect-*` ×~8, `structure-check` ×2, `forge-events` ×1, `gate-local` ×3. Baseline re-runs of the two suspect tests: once in the audit, once as the seed measurement (`defect_detect.rerun`, 48 s for both).
Where the time went in the accepted gate: structure check 39.2 s and script tests 73.6 s of 128.0 s; the stage costs are GS1's, unchanged.

## 5. Lessons: change, owner

1. Registry keys and their readers land in the same commit; add a helper that checks it (F1). Owner: engine lane.
2. Run the structure stage after each commit, not at the end (F5). Owner: engine lane (hook) / plan template (structure owner).
3. Brief: name the principle items, the signature source and where registry writes are committed (section 1). Owner: A Torre.
4. A single process message per change; the lane re-reads it once (section 1). Owner: A Torre.
5. Cross-references to numbered rules are checked against their headings (F6). Owner: structure owner.
6. A gate-local test for "report PASS overrides a failed stage" (F7). Owner: gate owner.
7. Known base defects: with this PR merged, `scripts/defects sync` and `route` turn the next detections into fix units for `engine-lane`. The seeds are registered with `--no-emit` (no events): the first `sync` after merge will re-record them as `observed`.
8. Targeted tests for a change in a gate file run through the gate's own wrapper (F8), and the structure stage runs per commit (F5, F9). Owner: engine lane.
9. **Never push code after the final gate without re-gating** (Daniel, 00:4x). Run 2 passed on `d7c8bb1e`; I then pushed `ddf5740b` (gate-local) and the retro, so the head `a87cbb6e` was ungated until run 3. The merge rule is already "gate green on the exact head"; the gap was mine, between the green gate and the next push. Prevention: the auto-push hook (or `scripts/pr-ready`) should print "head moved since the last gate pass" when a push follows a `.dev.pass` of an older sha (engine lane / owner: gate owner).
