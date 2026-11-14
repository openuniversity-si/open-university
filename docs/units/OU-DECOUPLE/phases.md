# OU-DECOUPLE — phases

Step 5 of Daniel's unit standard of 30/10: one loop per phase of `plan.md` (audit, plan, execute, measure). A phase
passes only when its target is met and no guard metric got worse; otherwise it loops again. Each phase is one PR. Its
audit and plan open the PR, and its measurement closes it.

## F1. Nothing runs the full battery by accident (PR 2)

### Auditoria
- The 16 paths with no area, and the script tests whose covers already name them (`scripts/tests/covers/*.json`):
  - `services/runner/**` (3): `service`.
  - `services/control-plane/**` (4, with `wrangler.toml`): `control-plane`.
  - `.githooks/*` (3): `push-guard`, `prepush`, `local-checks`.
  - `.claude/settings.json`: `claude-settings`.
  - `.gitattributes`: `merge-regenerate`.
  - `.cursor/environment.json`, `.cursor/rules/delivery.mdc`, `.gitignore`, `.gitleaks.toml`: none.
  - `apps/web/tsconfig.paths.json`: OU's TypeScript path map, rendered by the engine's `addresses` target.
- `plan_for` returns the full plan for an unmapped path (`scripts/lib/gate_areas.py:447-450`) and for an empty diff
  (`:439-440`).
- The refusal cannot be a planner error. A classify failure leaves no plan file, and then `gate_want` runs every stage
  (`scripts/gate-local:386`). So it has to be a failing stage that always runs: the structure check.
- The pin (P-46): the structure check is the base's tool. If it read the base's area map, it would refuse a path the
  head maps in an area the same PR adds. So it reads the map of the checkout it judges. The planner is also the
  base's, so it keeps the full battery only for a diff that changes the map itself, which a new map should get.
- `test_gate_areas.py` and `test_gate_plan.py` assert today's fallbacks, so they change with the rule.

### Plano
1. This loop (audit and plan).
2. Every path gets an area. `engine-services` is `services/**`. `repo-config` is `.githooks/**`, `.gitattributes`,
   `.gitignore`, `.gitleaks.toml`, `.claude/**` and `.cursor/**`. Both map to `script-tests`, and a path no covers
   name runs the whole script suite, the engine's own and never OU's. `apps/web/tsconfig.paths.json` joins `web-ui`
   next to `apps/web/tsconfig.json`.
3. D-106. The structure check refuses a tracked path with no area, by name, reading the judged checkout's map; a test
   covers it.
4. The planner. An unmapped path selects the `always` stages, so its refusal is the verdict and nothing else runs,
   unless the diff changes `scripts/lib/gate-areas.json`, which keeps the full battery. An empty diff selects the
   `always` stages. The tests follow.
5. The measurement.

Targets:
- T1: 16 → 0 paths with no area on the head, measured by the new check.
- `plan_for(['.gitignore'])` selects only engine stages.
- `plan_for([])` and `plan_for(['NEW-ROOT-FILE'])` select the 7 `always` stages, and the second is refused by the
  structure check.

Guards: G1, G2 (the changed tests keep their count or grow), G3, G4, G5.

### Medição
Measured on the head `ec60afa7`, in this session, at 18:45 BRT.

| Metric | Baseline (`af3fb0ee`) | F1 head | Verdict |
|---|---|---|---|
| T1. Tracked paths with no area | 16 | 0. `gate_areas.coverage_errors` on the checkout returns `[]` in 0.13 s over 4,462 paths | met |
| `plan_for(['.gitignore'])` | full, 23 stages | scoped, 8 engine stages (the `always` stages plus `script tests`) | met |
| `plan_for([])` / `plan_for(['NEW-ROOT-FILE'])` | full, 23 stages | scoped, the 7 `always` stages. The second names the refusal: "unmapped path: NEW-ROOT-FILE; the structure check refuses it (D-106)" | met |
| `plan_for(['NEW-ROOT-FILE', 'scripts/lib/gate-areas.json'])` | full | full ("the area map changed") | as designed |
| G1. Script tests (`scripts/test-suite`) | 111 of 111 pass | 111 of 111 pass: 81 answered by key, 30 ran, wall 151 s | held |
| G2. `def test_` in `scripts/tests/**.py` | 2,524 | 2,527 (+3, the coverage tests) | held |
| M. Acting engine files that name `apps/web` | 351 | 351 (F1 does not target it) | unchanged |
| T2. Engine paths that pull OU stages | 939 | 939 (F2's target) | unchanged |

The pin applies the refusal from the next PR: this PR's own gate runs the base's structure check, which has no
coverage rule yet. F1 passes.

## F2. The engine gate runs only engine checks (PR 3)

### Auditoria
- `scripts/lib/gate-areas.json` orders 23 stages. 15 are OU's, reached through the groups `web-check`, `builds`,
  `e2e`, `gate-db` and `deploy`, and 11 of the 17 areas select them. `buildTypesCheckedBy` names two OU builds and
  `typecheck`, and `subjectInstallUnless` names `production deploy`. The loader requires both to name ordered stages
  (`gate_areas.AreaMap`), and it requires the areas `docs`, `database`, `fidelity` and `design`.
  `gate_policy` reads the `database` globs at import.
- Measured on `de2b119c`: 939 of the 3,213 engine paths that have an area still pull `install (frozen lockfile)`
  and `unit tests`. The cause is the readers scan (audit finding 4).
- Engine rules proven only in OU (audit finding 6), by fate:
  - **Port.** The repo-wide "no `@legacy.example` address" rule (`no-legacy-email.test.ts`) and the raster asset
    guard (`repo-assets-check.ts`), which runs only outside dev mode, with `pnpm` in `apps/web`.
  - **Leave with OU's delivery tail in F4.** The `merge-phase` check-runs pin and the preview policy rules.
  - **Retire with OU in F4.** The architecture checker's mechanics: all 25 of its rules target `apps/web/src`, and
    no stage runs it on engine code.
- A deletion cannot be judged green today. The pinned selector names tests from the base's covers, and a selected
  test whose script is missing "always runs" (`gate_test_cache.py:19`): `bash` on a missing file fails. Every test
  that F4 deletes together with its covers would turn F4 red.
- What else the base's engine stages do on a tree without OU is measured here. The F2 tools are run over a worktree
  with OU deleted (step 5 of the plan).

### Plano
1. This loop (audit and plan).
2. D-107. The script-test runner does not run a test whose script and covers manifest the judged change both delete,
   and reports it by name. A test deleted alone, while its manifest still names it, still runs and fails.
3. The ported rules become the structure check's `repo_hygiene` module. The legacy address pattern and the raster
   pattern with its allowlist are registry keys.
4. OU's 15 stages leave the area map. OU's areas keep their paths with no group, so every path keeps an area, and
   the loader no longer requires OU stages (`buildTypesCheckedBy` becomes optional). The tests follow.
5. The dry run: F2's engine stages over a worktree with OU deleted, fixing in F2 what the base must already
   tolerate and listing the rest for F4.
6. The measurement.

Targets:
- T2: 939 → 0 engine paths that pull an OU stage.
- T3: 15 → 0 OU stages in the area map's `order`.
- The two ported rules refuse a planted violation.
- The dry run's structure check, generated drift and selected script tests pass on the deletion worktree, or each
  failure is named for F4 with its owner.

Guards: G1, G2 (the counts grow by the ported tests; none drops), G3, G4, G5.

### Execução: the dry run (step 5)
Run at 19:15–19:30 BRT on a local worktree (never pushed) at F2's head `93761235`, with `apps/web` (1,249 files),
the 74 OU units and `units/cells` deleted, then the OU literal baselines too (1,379 paths). F2's own tools judged it.
- `structure-check --base`: no traceback. The errors are all data the deletion PR carries:
  - the OU literal baselines and catalogs ("belongs to no unit");
  - `l10n.scoped_files` and `l10n.scoped_exports`;
  - 37 `docs/structure/assets.json` entries;
  - registry keys whose only readers are OU files: battery, budgets, tests, text, units and generate;
  - three engine units that require OU units (`engine-architecture-check`, `engine-capture`, `engine-wrappers`);
  - one link in `docs/process/SITE-HEALTH.md`.
- `generate --check`: the `locale-text` output is missing and CODEOWNERS is stale. Both are fixed by the head
  dropping the OU targets and regenerating. `context-map`, `contexts` and `intents` skip on their own.
- `schema-compat`: 0 errors on 102 contracts.
- The whole pinned gate, run with F2's own `scripts/gate-local --dev --sha <dry run> --plan-file … --report-only`,
  produced:
  - a dev plan scoped to the 8 engine stages (`dbRequired` and `nodeRequired` false);
  - no install, no web stage and no crash, after two guards this step adds;
  - 112 script tests run, 89 PASS and 23 FAIL. The failures are head tests that still read OU, and they are F4's
    work list: battery, claude-session, config, delivery, engine-capture, env, gate-areas, gate-optimization,
    gate-select, gate-split, gate-web-readers, generate, hermetic, production-check, prune-inherited, push-guard,
    root-identity, structure-check, text-check, toolchain-pins, tower-media-retry, tower-media and units.
- The two guards (D-107, D-108): `share_node_modules` installs nothing without `apps/web/package.json`, and a dev
  run whose plan wants no web stage skips `gate_fixed_stages`. Without them the deletion's gate would `pnpm install`
  into a missing directory and key caches under it.

### Medição
Measured on the head `430156c2`, in this session, at 19:40 BRT.

| Metric | Before F2 (`de2b119c`) | F2 head | Verdict |
|---|---|---|---|
| T2. Engine paths whose one-file diff selects an OU stage | 939 of 3,213 | 0 of 3,221 | met |
| T3. OU stages in the area map's `order` | 15 of 23 | 0 of 8 | met |
| The two ported rules refuse a planted violation | (only in OU's vitest) | `test_repo_hygiene.py`: a legacy address, a raster image | met |
| Dry run of the deletion | — | the 8 engine stages judge it with no crash; 23 head tests listed for F4 | met |
| G1. Script tests | 111 of 111 | 112 of 112 (+`repo-hygiene`): 68 answered by key, 44 ran, wall 137 s | held |
| G2. `def test_` in `scripts/tests/**.py` | 2,527 | 2,535 (+8: hygiene 5, D-107 2, carry 1; no test dropped, OU-plan cases rewritten to the engine plan) | held |
| M. Acting engine files that name `apps/web` | 351 | 354 (+3: the hygiene keys and module name OU's allowlist, which F4 empties) | F4/F5's target |

F2 passes. The engine gate of every PR from now on is the 8 engine stages.

### Loop 2 (gate red on `d973f351`)
The pinned structure check failed: the base's coverage check (F1) validated the head's map with the base's loader,
which requires `buildTypesCheckedBy` to name ordered stages. Root: D-106's check read more of the judged map than
it needs, and a loader change cannot be judged by the loader it replaces (P-46, as D-096). Fix (D-109): OU's stages
stay listed in `order` with no group, `full_stages` is the `always` stages plus the grouped ones, and plans select
only those. The coverage check reads only globs. Verified by loading this head's map with `de2b119c`'s
`gate_areas.py`: `coverage_errors` returns `[]`. T2 is still 0, and no plan selects an OU stage (T3 measured as
selectable stages: 0). F4 drops the names.

## F3. Archive (no PR)
- Target: the archive exists before the removal lands, and its sha is recorded.
- Measured, 20:00 BRT: the base tip `567176bbf0697560e622911b7bf37af8962dbaa5` (#824's merge) holds the 1,249
  files of `apps/web`, the 74 OU unit manifests and every OU-only script.
- The annotated tag `ou-archive-2026-10-30` was created locally. Pushing it was refused, three times by `git push`
  (HTTP 403 from the session's git proxy, which allows only this unit's branch) and once by
  `POST /repos/openuniversity-si/open-university/git/tags` (403).
- D-110: the archive is that commit, kept by the branch's never-rewritten history; `main` (`251b64fb`) also holds an
  older OU.
- Daniel's step: `git tag -a ou-archive-2026-10-30 567176bb -m "Open University archive (D-105, D-110)" && git push
  origin ou-archive-2026-10-30`.
- A standalone OU repository can be cut from the commit at any time: `git clone https://github.com/openuniversity-si/open-university
  ou && cd ou && git checkout 567176bb && pip install git-filter-repo && git filter-repo --path apps/web/ --path
  units/ --path scripts/tower-catalog --path scripts/tower-media --path scripts/tower-factory`, then push to a new
  private repository.
- Verdict: target met in substance (nothing can be lost, the sha is recorded). The tag object waits for Daniel.

## F4. Open University leaves (PR 4)

### Auditoria
The F2 dry run (above) is this phase's audit. Added from the scripts classification (two read-only explorations,
recorded in `audit.md` findings 6, 7 and 9):
- OU-only, to delete with OU:
  - the delivery tail and production tooling: `ship-tail`, `ship-verify`, `merge-phase`, `production-check`,
    `preview-deploy`, `neon-pr`, `neon-migrate`, `gate-db` and their libraries;
  - the admin CLIs (`tower-catalog`, `tower-media`, `tower-factory`, `factory-bench`);
  - the browser capture (`engine-capture`) and the architecture checker (`engine-architecture-check`, whose 25 rules
    target `apps/web/src`);
  - the gate's web helpers (`gate-impact`, `gate-build`, `gate_suite`, `gate-db.sh`);
  - the generators that write into `apps/web` (`addresses`, `locale-text`, `intents`, `contexts`, `context-map`,
    `gate-suite-renames`);
  - OU's literal baselines and catalogs, every registry key whose only readers are OU files, and the tests of all
    of these.
- Engine code that would break without OU:
  - `scripts/cloud/setup.sh` runs a fatal `pnpm install --dir apps/web`;
  - `env_manifest` raises without `apps/web/package.json`;
  - `gate_noite` imports `gate-impact` at load;
  - `test_structure.py` imports `ship_verify`, which reads `apps/web` at import;
  - `gate-local`'s non-dev modes run Neon, the raster guard, the capture and the factory bench;
  - the nightly's and tier 3's named plans list OU stages;
  - 23 head tests read OU (the dry run's list).
- What stays: the train, the runner, events, the merge policy (`release_policy`, `merge_behind`, read by the train
  and by the GitHub client), `delivery.py`'s helpers, the local PostgreSQL (engine script tests use it) and the
  production freeze guard. F5 decides the guard once nothing it guards is left.

### Plano
1. This loop and F3's record (D-110).
2. D-111: what leaves and what stays. Delete OU's product, units, cells, literal data, delivery tail, CLIs, captures,
   architecture checker, gate web helpers and generators, with their tests and registry keys.
3. The engine code that read them: the gate modes and plans, setup, the environment manifest, the generator targets
   and the merge driver.
4. The engine tests whose fixtures or imports reach OU, made to pass on a tree without it. A test of deleted OU
   code goes with that code, and each one is listed.
5. The OU docs whose links and assets the structure check reads. The rest of the docs is F5's.
6. The measurement.

Targets:
- T4: 1,249 → 0 files under `apps/web` and 74 → 0 OU units.
- The structure check, generated drift and the whole script suite are green on the head.
- Every removed engine test is listed with its reason.

Guards: G1–G6.

### Execução
Three read-only/worktree helpers fixed the 25 engine test files that still read OU, in disjoint groups (gate
plan, environment and tooling, units/generate/structure); their patches were merged into this branch and the whole
suite was rerun here. Engine decisions taken on the way, each in D-111:
- `gate_web_readers` is gone; its only subject was OU's tests.
- `unit_addresses` (the `@ou/<id>` map) is gone, and `units.home` keeps the contract-entry rule.
- The environment manifest keeps only its toolchain half.
- The production guard names no entrypoint.
- The host swap queue stays, because the release policy reads it.

### Medição
Measured on the head `e8330198`, in this session, at 21:20 BRT.

| Metric | Before F4 (`567176bb`) | F4 head | Verdict |
|---|---|---|---|
| T4. Files under `apps/web` / OU unit manifests | 1,249 / 74 | 0 / 0 (2,813 tracked files, 36 units) | met |
| Structure check, generated drift | green | green | held |
| G1. Script tests (`scripts/test-suite`) | 112 of 112 | 95 of 95 | held (see below) |
| G2. `def test_` in `scripts/tests/**.py` | 2,535 | 2,333 | held (see below) |
| M. Acting engine files that name `apps/web` | 354 | 118 | F5's target |
| T1 / T2 | 0 / 0 | 0 / 0 | held |

Every test that left tested deleted Open University code; none tested engine behaviour that still exists.
- Script test files removed (17), each with the code it tested:
  - `tower-catalog-wrapper`, `tower-factory-wrapper`, `tower-media`, `tower-media-retry`: the admin CLIs;
  - `gate-db`, `gate-db-neon`, `neon`, `invoker-tooling`: the DB gate and Neon;
  - `delivery`, `cloud-tail`, `merge-phase`, `production-check`, `preview-deploy`: the delivery tail;
  - `engine-capture`, `prune-inherited`: the capture;
  - `gate-optimization`: gate-impact and gate-build;
  - `gate-web-readers`: the readers of OU's tests.
- Test functions in removed Python files (163): `delivery_test` 31, `test_production_check` 28, `test_cloud_tail` 19,
  `test_gate_web_readers` 19, `test_unit_addresses` 19, `test_neon_migrate` 18, `test_gate_optimization` 9,
  `test_preview_deploy` 9, `test_invoker_tooling` 6, `test_gate_db` 5.
- Functions removed from kept files (the rest of the 202):
  - `test_aggregates` 23 → 3: the context-map, contexts, intents and gate-suite-renames generators;
  - `test_gate_select` 31 → 26: the unit tail, the reader map and the walk of `apps/web/src`;
  - `test_gate_split` 16 → 11: the suite union, ship_verify and neon_pr;
  - `test_generate` 23 → 20: locale-text;
  - `test_gate_gc` 18 → 16: gate-build's publish;
  - `test_release_policy` 11 → 9: the Neon and promote clients;
  - `test_structure` 68 → 66: ship_verify's fit review, whose rules `ReviewErrors` still covers;
  - `test_credentials` 7 → 6: the Neon and Vercel headers; two new tests cover `credentials.bearer`;
  - `test_gate_areas` 28 → 27, `test_root_identity` 9 → 8, `test_toolchain_pins` 16 → 15: their subjects were OU files.
- Grown: `test_env` 13 → 15, `test_production_guard` 9 → 10, `test_units` 20 → 21.

F4 passes.

### Loop 2 (gate red on `5c88ee57`, #825)
The pinned gate refused the removal on three rules that read a deleted unit as live:
- "lane undecidable" across 17 OU lanes;
- "visual change without a declared visual capability" over OU's deleted UI files;
- schema compat "removed without a revision that marked it deprecated" on 122 registry keys.

Root: the ownership and visual rules protect live units, and no rule knew a retired one. Removing OU one lane at a
time would take 18 PRs with a half-deleted tree between them. Fix (D-112), landed by #825 (`daa866c9`) after the
removal was held back by a revert (history kept):
- a unit whose manifest the change deletes is retired: it decides no lane, the train refuses nothing for it, and
  its deleted files are no visual edit;
- the 122 keys are marked deprecated first.

The removal then re-lands unchanged in #826, as the revert of the hold-back.

### Medição (loop 2)
Measured on #826's head `97a2b537` at 21:50 BRT.
- T4: 0 files under `apps/web` and 0 OU units (2,813 tracked files, 36 units). Met.
- The structure check, schema compat and generated drift are green, and the script suite passes 95 of 95. G1 and G2
  hold with the accounting above: 2,333 test functions, every removed one a test of deleted OU code.
- M: 118 acting engine files still name `apps/web`, which is F5's target.
- T1 and T2 stay at 0.

F4 passes.

## F5. The engine names no product (PR 6)

### Auditoria
Measured on `c770ba2e` (#826 merged), 22:05 BRT: 118 acting files still name `apps/web`.
- config 41: registry defaults of battery, budgets, census, defects, gate, gate-areas, quarantine, structure, tests,
  test-db, toolchain, train and units;
- scripts 21: gate-local, gate-fixed.sh, gate-runner, gate_policy, gate_noite, gate_select, gate_batch, the gate
  stage tables, census, assets, structure, defects, perf_tests, registry_readers, merge_regenerate, setup.sh, the
  vendor and literal baselines;
- scripts/tests 30: fixtures;
- docs 20 living pages, plus 6 ADRs and 6 OU capabilities;
- root 4 (`.gitignore`, `.gitleaks.toml`, `AGENTS.md`, `README.md`), services 1 (the hosted-runner cache key), units 1.

The gate's non-dev modes (nightly, tier 3) still list OU stages and would fail without `apps/web`. Registry keys can
leave only after a deprecating revision (schema compat), so a key whose feature leaves is deprecated here, not
removed. ADRs are decision records like the units' docs: they are not rewritten.

### Plano
1. This loop.
2. The gate core without OU: modes, named plans, area map, stage tables and gate registry.
3. Units, census, structure, assets, visual guard and defects without OU.
4. Environment, toolchain, battery, budgets, tests registry, setup, the hosted-runner cache key, and the living docs
   (AGENTS.md, CLAUDE.md, README.md, operations, architecture, process).
5. D-113: the guard. A structure-check module refuses a tracked path under a retired product root, and an acting file
   that names one (records exempt, `structure.record_globs`). Also `docs/process/RETIRE.md`, the retirement
   procedure this unit followed.
6. The measurement, then the retro (`retro.md`).

Targets:
- M: 118 → 0, held by the guard.
- Every gate mode orders only engine stages.
- G1/G2 hold, with every removed test listed.

### Execução
Three helpers in disjoint worktrees took the gate core, units/census/structure, and environment/registry/docs. Their
patches were merged here, and the guard (D-113) and `docs/process/RETIRE.md` were written meanwhile. 16 registry keys
whose feature left are deprecated with neutral values; none was removed.

### Medição
Measured on #827's head at 23:59 BRT.
- M: 0 acting files name `apps/web`. `retired_products.check` returns `[]`, and the structure check holds it. A wider
  count that also reads ADRs and the guard's own definition finds 7 (five ADRs, two definition files), all of them
  records by D-113.
- The gate's every mode orders the 8 engine stages, and T1/T2 stay at 0.
- G1: 95 of 95 script tests (`retired-products` added, `gate-fixed` removed with `gate-fixed.sh`).
- G2: 2,337 → 2,306. 29 functions left with the gate's web machinery (the DB import rule, the package surface, the
  web selection, the lint/typecheck keys, plus duplicates of kept `stage_key` tests), 10 with the Drizzle checks, and
  new tests were added. The F5 helpers' lists are in #827.

F5 passes. The unit's retro is [retro.md](retro.md).
