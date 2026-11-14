# Program test-excellence: plan

Built from [audit.md](audit.md) (principles T1–T10, inventory ranked by PRs blocked, overlap of 128 shared files across 76 heads, census of the whole test system). Design target: 1,000 PRs per day only. Status is never written here: `scripts/program status test-excellence` folds it from events. The PR graph is data (contracts/programs/program.v1.json), §7. Revision 2 (A Torre 01:23 BRT): `depends_on` holds only REAL edges; every unit without one is launchable now, in parallel with wave 1.

## 0. Summary

- **Wave 1 is this PR (#742, `mod/tx-program`, engine lane): the preparation unit and the unblocking fixes.** TX00 splits the one shared test file that conflicted tonight into a directory suite (T1); TX01 is the one-command pre-push targeted check that finds tonight's inventory misses in seconds with the exact fix, runs the owning tests of the diff and warns about files shared with open PRs (T2, T9); TX02 routes every deferred item through the existing known-defect/env mechanism (T4, T8).
- **Wave 2 (engine lane, parallel, disjoint files)** removes the remaining causes: hermetic script tests (T6), flake attribution on the PR's own head (T4, T8), env premises labelled env (T4), sound selection of web tests that read engine files (T3, the 27-PR base-red), derived companion ownership and CODEOWNERS (T2), literal baselines derived from the base census (T2), expected lists derived inside tests (T2), per-feature Python test files (T1), orphan tests found and run (T1, T10), and a new test that selects only itself (T3).
- **Wave 3 (tooling and identity lanes, parallel)** fixes the load flakes in app tests at the cause without raising a timeout (T7) and derives the web path aliases (T2).
- **Wave 4** measures the goal for a day of real traffic and writes the program retro.

Estimates are measured, not guessed: the 26 PRs merged in the audit window took a median of 86 min from open to merge; the six smallest engine units (GX-27 9, GX-18 12, GX-22 25, GX-32 30, GX-20 32, GX-28 40 min) give **S = 30 min**; GX-10, GX-12, GX-13, GX-23 (86 min each) give **M = 86 min**; GX-16 and GX-11 (102 min) give **L = 102 min**.

**Critical path (measured):** two chains, both starting at launch.
- Chain A: TX00 (this PR, MERGE-READY target 06:00Z = 120 min after launch) → TX10 (M 86) = **206 min**.
- Chain B: every other wave-2 and wave-3 unit starts now (no real edge): the longest is M = 86 min.
- The build path is chain A, **206 min**; TX40 then needs one day of traffic (measurement, not build). Without the revision (every unit behind TX00) the path would have been the same 206 min but with 11 units idle for 120 min; now 11 of 13 units start at once.

## 1. Waves and units

| Unit | Wave | Title | Files it owns (disjoint from every other unit) | Lane | Real deps | Size | Branch | Launch |
|---|---|---|---|---|---|---|---|---|
| TX00 | 1 | Preparation: a suite is a directory; `gate-local.test.sh` split per feature and per hook | `scripts/tests/lib/**`, `scripts/tests/suite-runner.test.sh`, `scripts/tests/gate-local.test.sh`, `scripts/tests/gate-local/**`, covers `gate-local`/`suite-runner`/`hermetic-expectations`, `scripts/tests/rest-fake-ready.test.sh:40`, `docs/structure/assets.json:223`, `scripts/gate-local:373` (shellcheck list), `units/engine-gate-run`, `units/engine-test-support`, the `engine-gate-run` literal baseline, `CODEOWNERS` (regenerated) | engine | – | done (`4110b738`) | `mod/tx-program` #742 | this session |
| TX01 | 1 | Pre-push targeted check | `scripts/lib/prepush.py`, `scripts/prepush`, `scripts/tests/{prepush.test.sh,test_prepush.py}`, `scripts/tests/covers/prepush.json`, `config/registry/prepush.json`, `.githooks/pre-push`, `units/engine-push-guard`, `docs/operations/local-gate.md` (one section). Not `local_checks.py`/`local-checks.json`/`test_local_checks.py`: open #732 edits them | engine | – | in this PR | `mod/tx-program` #742 | this session |
| TX02 | 1 | Deferred items through the existing known-defect/env route; backlog | `docs/programs/test-excellence/backlog.md` | engine | – | in this PR | `mod/tx-program` #742 | this session |
| TX10 | 2 | Hermetic script tests: private `TMPDIR` per script test (under `/tmp`, 0755), the gate's own state (`OU_GATE_*`, forge call-count file) scrubbed from test children, failure-log copy under `$logs` and a checked stage-record write, the timeout mislabel (B8: `gate_kill_tree` kills the watcher's sleep first), `scripts/run test` pins the config store | `scripts/lib/gate_test_cache.py`, `scripts/lib/gate-runner.sh`, `scripts/run`, `scripts/tests/gate-local/runner.test.sh`, new `scripts/tests/test_gate_test_cache_env.py`, `scripts/tests/test_config_api.py:281` | engine | **TX00** (edits its part file) | M 86 | `mod/tx-hermetic` | after #742 merges |
| TX11 | 2 | Flake attribution: a red test that passes on one same-head re-run is classified `flake`, recorded through `scripts/defects`, shown in the status table; the verdict follows the re-run; a second flake of the same test is quarantined through the registry, still visible | new `scripts/lib/gate_flake.py` + tests + covers; one call in `scripts/lib/gate_adjudicate.py`; the `flake` class in `scripts/lib/gate_classify.py` | engine | – | L 102 | `mod/tx-flake` | **now** |
| TX12 | 2 | Env premises labelled env, not code: root-identity and claude-session tests check their machine premise and print `FAIL env: <premise>`; per-test preflight stamp; `env.*` id range a registry read; `OU_CONFIG_STORE=file` passed through `sudo env` | `scripts/tests/test_root_identity.py`, `scripts/tests/root_probe.py`, `scripts/tests/test_claude_session.py`, `scripts/lib/session_identity.py`, `scripts/cloud/env.sh:26` | engine | – | M 86 | `mod/tx-envlabel` | **now** |
| TX13 | 2 | Base-red incident: the web bundle back under `budgets.web_bundle_bytes_max` at its cause (695469 > 695296 on the base; #742's pinned gate on `ca39a1e0` passed every other stage); the limit is never raised | the files the bisect names (apps/web), never `config/registry/budgets.json` | the lane that owns the cause (web-build is tooling) | – | M 86 | `mod/tx-bundle` | **now** (blocks #742's gate) |
| TX20 | 2 | Sound selection: a web test that reads a repository file outside `apps/web` is selected when that file changes (fail closed) | new `scripts/lib/gate_web_readers.py` + tests + covers; one call in `scripts/lib/gate_areas.py` | engine | – | M 86 | `mod/tx-select` | **now** |
| TX21 | 2 | Derived companion ownership (a covers manifest is owned by its script's unit; exact fix messages for a double claim and an unowned file) and CODEOWNERS generated on demand, not committed | `scripts/lib/units.py`, `scripts/lib/unit_check.py`, `scripts/lib/generate_codeowners.py`, `units/engine-gate-plan/unit.json`, their tests | engine | – | M 86 | `mod/tx-owners` | **now** |
| TX22 | 2 | Literal baselines derived from the base census (shrink-only kept), messages with source file and line | `scripts/lib/literal_census.py`, `scripts/tests/test_literal_census.py`, `scripts/lib/absolute-literals-baseline/**`, `scripts/lib/literal-catalogs/**` | engine | – | M 86 | `mod/tx-literals` | **now** |
| TX23 | 2 | Expected lists derived inside tests: the stage list (`test_gate_areas.py:46`), the `BEFORE_SPLIT` sha256 (`test_gate_report_skips.py:132`), the hard-coded selections (`test_gate_script_tests.py:24-64, 79-86`) | those three tests | engine | – | S 30 | `mod/tx-expected` | **now** |
| TX24 | 2 | Per-feature Python test files with glob discovery for the hottest shared ones (`test_train.py` 21 commits/6 PRs, `test_structure.py` 16/11, `test_forge_events.py` 15/10, `test_gate_status.py`, `test_planner_role.py`) and one route file per unit for `rest_fake.py` (7 PRs) | those tests, their wrappers, `scripts/tests/rest_fake/**` | engine | – | L 102 | `mod/tx-pysplit` | **now** |
| TX25 | 2 | Orphan tests run: `test_gate_gc.py` (10 tests) and `test_text_check.py` (21) are run by no wrapper; the 10 wrappers that list Python files by hand glob them; a derived check that every `test_*.py` is run by exactly one wrapper | the 10 wrappers (e.g. `scripts/tests/structure-check.test.sh:5`), new `scripts/lib/test_orphans.py` + tests + covers, the two orphans' wrappers | engine | – | M 86 | `mod/tx-orphans` | **now** |
| TX26 | 2 | A new script test selects only itself: `scripts/tests/covers/*.json` leave the selector fallback (today a covers edit runs the whole suite: 56 % of 293 merges ran the full script suite, 38 for selector edits) | `config/registry/gate-tests.json` (`fallback`), `scripts/lib/gate_script_tests.py` (`select`), `scripts/tests/test_gate_script_tests.py` new cases in a new file | engine | – | S 30 | `mod/tx-covers` | **now** |
| TX30 | 3 | tooling: `catalog-cli/sync.test.ts` and `absolute-literals.test.ts` write megabytes into a shared tmpdir and never remove it (15 ms alone, 6.6 s under gate load): sparse files, one dir per test, `rmSync`; no timeout raised | `apps/web/scripts/lib/catalog-cli/sync.test.ts`, `apps/web/scripts/lib/absolute-literals.test.ts` | tooling | – | S 30 | `mod/tx-tmpfiles` | **now** |
| TX31 | 3 | identity: `handler.test.ts` cold-imports better-auth inside the 5 s timer (611 ms first test vs 9–32 ms): resettable `configuredAuth` cache, import once, no `resetModules` | `apps/web/src/identity/server/config.ts`, `apps/web/src/identity/server/handler.test.ts` | identity | – | S 30 | `mod/tx-identity` | **now** |
| TX32 | 3 | Web path aliases derived from the unit manifests (26 open PRs edit `apps/web/tsconfig.json`) | `apps/web/tsconfig.json` + its generator target | tooling | – | M 86 | `mod/tx-aliases` | **now** |
| TX40 | 4 | Measure `test_blocks_not_own_per_day` over one day of traffic; program retro | `docs/programs/test-excellence/retro.md` | engine | every wave-2 unit (real: it measures them) | S 30 + one day | `mod/tx-program` follow-up | after wave 2 |

13 units launch now (TX11, TX12, TX13, TX20–TX26, TX30–TX32), TX10 after #742 merges, TX40 after wave 2. TX13 (added 05:04Z) is the base-red found by #742's own pinned gate: not a program edge, an external blocker of #742's verdict. No two units own the same file; TX30 and TX32 share the tooling lane on disjoint files. Briefs: `briefs/<unit>.txt`.

## 2. Edge table (real vs collision)

| Edge | Kind | Resolution |
|---|---|---|
| TX10 → TX00 | real | TX10 edits `scripts/tests/gate-local/runner.test.sh`, which TX00 creates |
| TX40 → wave 2 | real | it measures the merged units |
| any unit → `gate-local.test.sh` | collision | removed by TX00: each unit adds or edits its own part file |
| TX24 → TX00 | **removed** (revision 2) | Python splits glob `test_<module>_*.py` in their wrapper; they do not need the shell suite runner |
| TX11 → TX02 | **removed** (revision 2) | TX11 records flakes through `scripts/defects` directly; the backlog is documentation |
| TX10 ↔ TX24 on `test_gate_test_cache.py` | collision, removed by design | TX10 adds its cases in a new `test_gate_test_cache_env.py`; TX24 does not split `test_gate_test_cache.py` |
| TX10 ↔ TX11 on `gate-runner.sh` / `gate_test_cache.py` | collision, removed by design | TX11 lives in a new `gate_flake.py` and one call in `gate_adjudicate.py`; it does not edit TX10's files |
| TX25 ↔ TX26 on `gate_script_tests.py` | collision, removed by design | TX25's orphan check is a new module `test_orphans.py` |
| TX21 ↔ every PR on `CODEOWNERS` | collision | until TX21 merges, each PR regenerates it (`scripts/generate codeowners`); after TX21 it is not committed |
| TX22 ↔ every PR on the literal baselines | collision | until TX22 merges, `--write <unit>` per PR; after TX22 nothing is committed |
| wave 3 ↔ wave 2 | none | different lanes and files |
| #742's verdict → TX13 | base-red, not a program edge | #742 merges the base after TX13 merges and re-gates; nothing else waits |

## 3. Migration of the pending PRs (do not edit their branches; each applies this at its next base merge)

| PR | Its hunk today | After the unit merges, the hunk goes to |
|---|---|---|
| #732 GX-15, after **TX00** (#742) | `scripts/tests/gate-local.test.sh @@ -169,6 +169,9`: deletes the no-op loop `for h in prereq; do … done`, adds a `prereq_launch()` helper and 2 checks for the `prereq` hook | `scripts/tests/gate-local/hook-prereq.test.sh`: replace its one no-op check with the `prereq_launch()` helper and the 2 checks (same lines, after `source "$(dirname "$0")/setup.sh"`). Resolve the conflict in `scripts/tests/gate-local.test.sh` by taking the base version (the 8-line runner). Counts: base 59 checks; #732 adds 2 and removes 1 → 60 (`hook-prereq` 2). |
| #732 GX-15, after **TX23** | `test_gate_areas.py:46` adds `"pr metadata"` to the expected stage list; `test_gate_report_skips.py:132` re-pins `BEFORE_SPLIT` | both hunks disappear: the lists are derived; take the base version of both files |
| #740 GX-25 (red today) | no restructured file. Its red is audit §3 (b) | drop `scripts/tests/covers/gate-timing-report.json` from `units/engine-gate-report/unit.json` (`engine-gate-plan` owns it by `scripts/tests/covers/**`; after TX21 the covers file follows its script's unit automatically) and add `"engine-slo": "^1"` to that unit's `requires`; `scripts/prepush` prints both lines in seconds |
| #740 GX-25, after **TX24** | `test_gate_status.py`: L15 import, L80 ledger in `Base`, L99 rename, L215 new `class Started` (7 tests) | `class Started` (and its import) goes to `scripts/tests/test_gate_status_started.py`; the L80 and L99 edits stay in the base file |
| #734 LP9, after **TX24** | `test_planner_role.py`: L280 `RoleLease` edit, `WakePath` +5 tests (L343, L379) | the `WakePath` tests go to `scripts/tests/test_planner_role_wake.py`; the L280 edit stays |
| #662 N1, after **TX25** | `scripts/tests/structure-check.test.sh` (one listed file) | the wrapper globs; drop its line |
| #667 BD1, after **TX24** | `scripts/tests/rest_fake.py` adds a `/compare/` route (also added by #722 on the base) | its route goes to `scripts/tests/rest_fake/<unit>.py`; the duplicate `/compare/` disappears |
| #741 GX-31, #724 PERM-ALLOW, #683 GS2 | no restructured file | a plain base merge; regenerate `CODEOWNERS` if they touch a manifest (until TX21) |

Two units adding tests to the same feature area after TX00: both add a new part file under `scripts/tests/gate-local/`; shown with a local two-branch merge, zero conflicts, in the PR evidence.

## 4. Commit graph of this PR (wave 1)

| Commit | Plan item | Files | Parallel with | Targeted tests |
|---|---|---|---|---|
| 1 | audit, program record | docs | – | `scripts/program check test-excellence` |
| 2 | plan | docs | – | `scripts/program check test-excellence` |
| 3 | TX00 | §1 TX00 | 4 (sub-agent, disjoint) | `gate-local` (59 = 59), `suite-runner`, `rest-fake-ready`, `hermetic-expectations`, `units`, `structure-check`, `literals`, `gate-script-tests`, `generate`: all green, 20 s wall |
| 4 | TX01 | §1 TX01 | 3, 5 | `prepush`, `units`, `literals`, `gate-script-tests` |
| 5 | TX02 + briefs | `backlog.md`, `briefs/*.txt` | 4 | `scripts/program check test-excellence` |
| 6 | evidence + RETRO | `retro.md` | – | – |

One final pinned gate on the exact head: `OU_CONFIG_STORE=file bash scripts/cloud/setup.sh` then `(export OU_CONFIG_STORE=file; source scripts/cloud/env.sh; unset OU_CONFIG_STORE; scripts/gate-dev --pr 742)`.

## 5. Premises

| Premise | Blast radius | Status |
|---|---|---|
| P-46 (brief) | the program | cited |
| The gate discovers only `scripts/tests/*.test.sh`, so parts under `scripts/tests/<suite>/` run only through their suite runner | TX00 | verified: `scripts/lib/gate_script_tests.py:27` |
| The literal census scans tracked files under `scripts/`, nested test dirs included | TX00 | verified: the split's literals moved to the parts with no area total increase (`literal_census.check(root, base)` → 0 errors) |
| `scripts/tests/gate-local/**` in the covers manifest selects `gate-local.test.sh` when a part changes, so the per-test cache never reuses a stale pass | TX00 | verified: `select` on each part path → `gate-local.test.sh` |
| Removing a shared inventory never weakens its check (only derivation) | TX21, TX22, TX23, TX25 | **CRITICAL** in each brief: the unit proves the same failing fixture fails before and after |
| A same-head re-run that passes is a flake, not a pass to forget | TX11 | **CRITICAL** (changes how a verdict is produced): the brief requires the record and the status-table line before the verdict follows the re-run |

## 6. Known base defects expected during this PR's gate

See [backlog.md](backlog.md); none is excused by hand.

## 7. Graph as data

```json program.v1
{
  "contract": "program.v1",
  "program": "test-excellence",
  "complaint": {
    "symptom": "tests are a recurring PR blocker that is mostly not the PR's own fault: shared test files conflict, inventories miss a unit's own file until the full gate, the base and the machine go red, tests fail only under load",
    "evidence": "docs/programs/test-excellence/audit.md: 40 gate.failed on 32 PRs and 5 pr.conflicted since 27/10 23:00Z; row 1 base red 112 min blocked 27 PRs; gate-local.test.sh conflicted 3 PRs 9 times",
    "goal": {"metric": "test_blocks_not_own_per_day", "comparator": "lte", "target": 0, "unit": "blocks/day"}
  },
  "units": [
    {"id": "TX00", "title": "Preparation: a suite is a directory; gate-local.test.sh split per feature and per hook", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 1, "done": ["59 checks before and after the split", "two units adding gate-local tests merge with zero conflicts"], "area": ["scripts/tests/lib/**", "scripts/tests/gate-local/**", "scripts/tests/gate-local.test.sh"]},
    {"id": "TX01", "title": "Pre-push targeted check", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 1, "done": ["one command, seconds", "catches the #740 ownership miss and a shared-file overlap"], "area": ["scripts/lib/prepush.py", "scripts/prepush", "config/registry/prepush.json", ".githooks/pre-push"]},
    {"id": "TX02", "title": "Deferred items through the known-defect/env route", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 1, "done": ["backlog.md lists every deferred item with its route and owner"], "area": ["docs/programs/test-excellence/backlog.md"]},
    {"id": "TX10", "title": "Hermetic script tests", "depends_on": ["TX00"], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["each script test has a private TMPDIR", "no gate variable reaches a test child", "no fixed /tmp log path"], "area": ["scripts/lib/gate_test_cache.py", "scripts/lib/gate-runner.sh", "scripts/run"]},
    {"id": "TX11", "title": "Flake attribution on the PR's own head", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["a red test green on one same-head re-run is classified flake, recorded and shown"], "area": ["scripts/lib/gate_flake.py", "scripts/lib/gate_adjudicate.py", "scripts/lib/gate_classify.py"]},
    {"id": "TX12", "title": "Env premises labelled env, not code", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["a missing machine premise prints FAIL env and is classified env"], "area": ["scripts/tests/test_root_identity.py", "scripts/tests/root_probe.py", "scripts/tests/test_claude_session.py", "scripts/lib/session_identity.py"]},
    {"id": "TX13", "title": "Base-red: the web bundle back under its budget at the cause", "depends_on": [], "owner": "tooling-lane", "model": "opus", "wave": 2, "done": ["the base builds production under budgets.web_bundle_bytes_max with the limit unchanged"], "area": ["apps/web/**"]},
    {"id": "TX20", "title": "Sound selection of web tests that read engine files", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["a scripts-only diff to a file a web test reads selects that test"], "area": ["scripts/lib/gate_web_readers.py", "scripts/lib/gate_areas.py"]},
    {"id": "TX21", "title": "Derived companion ownership; CODEOWNERS on demand", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["a covers manifest is owned by its script's unit", "no PR edits CODEOWNERS"], "area": ["scripts/lib/units.py", "scripts/lib/unit_check.py", "scripts/lib/generate_codeowners.py"]},
    {"id": "TX22", "title": "Literal baselines derived from the base census", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["no committed per-file literal counts; shrink-only kept"], "area": ["scripts/lib/literal_census.py", "scripts/lib/absolute-literals-baseline/**"]},
    {"id": "TX23", "title": "Expected lists derived inside tests", "depends_on": [], "owner": "engine-lane", "model": "sonnet", "wave": 2, "done": ["adding a stage edits no expected list"], "area": ["scripts/tests/test_gate_areas.py", "scripts/tests/test_gate_report_skips.py", "scripts/tests/test_gate_script_tests.py"]},
    {"id": "TX24", "title": "Per-feature Python test files and rest_fake routes", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["a unit adds a Python test file instead of editing a shared one"], "area": ["scripts/tests/rest_fake/**"]},
    {"id": "TX25", "title": "Orphan tests run; wrappers glob", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 2, "done": ["every test_*.py is run by exactly one wrapper", "test_gate_gc.py and test_text_check.py run in the gate"], "area": ["scripts/lib/test_orphans.py"]},
    {"id": "TX26", "title": "A new script test selects only itself", "depends_on": [], "owner": "engine-lane", "model": "sonnet", "wave": 2, "done": ["a covers manifest edit selects its own test, not the whole suite"], "area": ["config/registry/gate-tests.json", "scripts/lib/gate_script_tests.py"]},
    {"id": "TX30", "title": "tooling tmpfile load flakes at the cause", "depends_on": [], "owner": "tooling-lane", "model": "sonnet", "wave": 3, "done": ["passes under a loaded gate with the timeout unchanged"], "area": ["apps/web/scripts/lib/catalog-cli/sync.test.ts", "apps/web/scripts/lib/absolute-literals.test.ts"]},
    {"id": "TX31", "title": "identity handler.test.ts timeout at the cause", "depends_on": [], "owner": "identity-lane", "model": "sonnet", "wave": 3, "done": ["passes under a loaded gate with the timeout unchanged"], "area": ["apps/web/src/identity/server/**"]},
    {"id": "TX32", "title": "Web path aliases derived", "depends_on": [], "owner": "tooling-lane", "model": "opus", "wave": 3, "done": ["no PR edits apps/web/tsconfig.json to add an alias"], "area": ["apps/web/tsconfig.json"]},
    {"id": "TX40", "title": "Measure the goal over a day; program retro", "depends_on": ["TX10", "TX11", "TX12", "TX13", "TX20", "TX21", "TX22", "TX23", "TX24", "TX25", "TX26"], "owner": "engine-lane", "model": "opus", "wave": 4, "done": ["test_blocks_not_own_per_day measured from events"], "area": ["docs/programs/test-excellence/retro.md"]}
  ]
}
```
