# OU-DECOUPLE — audit

Stage 3 of Daniel's unit standard of 30/10 (Diagnóstico: a measured baseline, a main metric and guard metrics),
carried in the audit file the `structure check` requires (D-077, D-081). Read-only and measured, not estimated. It
states causes by a chain of whys and proposes no solution.

## Entradas
- [intake.md](intake.md): the real problem (the engine cannot exist without OU: it names OU in the files that act, it
  judges engine changes partly with OU's stages, and some paths have no area) and the four failed systems S1–S4.
- [research.md](research.md): the state of the art (declared boundaries checked by the build, total ownership, extract
  with history after a tag, retire production reversibly) and the ladder of ambition.

Method. All numbers were measured in this session's container (4 vCPUs) on 30/10 between 17:55 and 18:30 BRT, on
base `02a7816a` plus this PR's documentation commits. Tools: `git ls-files` and `git grep` for counts.
`gate_areas.plan_for` was called on every tracked path, one path per diff, for the stages each path selects.
`scripts/test-suite` measured the engine suite, and `forge_events.py read --pr N` read the gate verdicts of #816–#821.
`scripts/gate-dev --pr 822 --explain` gave the scoped plan. Two read-only explorations covered every `apps/web` file
that reads engine paths and every `scripts/` file that names `apps/web`. "Acting" files are every tracked file outside
`apps/web` except historical records: `docs/units/**`, `docs/programs/**`, `docs/audits/**`, `docs/project/**`,
`docs/process/{roadmap,postmortems,incidents,lessons,defects,premises,spikes}/**` and
`docs/domain/DECISIONS.md`. Those describe the past and are not rewritten.

## Findings
1. **547 files outside `apps/web` name it. 351 of them act today.** `git grep -l "apps/web" -- . ':!apps/web'`:
   docs 240, config 87, scripts 79, scripts/tests 58, units 76, root 6 (`AGENTS.md`, `README.md`, `CODEOWNERS`,
   `.gitattributes`, `.gitignore`, `.gitleaks.toml`), services 1 (`services/runner/github/tower-runner.yml:43`).
   Acting files: 351 (config 87, scripts 79, scripts/tests 58, units 76, docs 44, root 6, services 1). Historical
   records: 196.
2. **16 tracked paths have no area, and each one alone is a full battery.** `gate_areas.plan_for([path])` →
   `full`, 23 stages, `unmapped path: …`: `services/**` (6), `.githooks/*` (3), `.cursor/*` (2),
   `.claude/settings.json`, `.gitattributes`, `.gitignore`, `.gitleaks.toml`, `apps/web/tsconfig.paths.json`.
   `scripts/lib/gate_areas.py:447-450` returns the full plan on the first unmapped path. No check counts them.
3. **An empty diff is a full battery too, and right now it occupies the only runner.** `gate_areas.py:439-440`
   (`empty diff; full battery`). Since about 17:55 BRT the VM runner has been gating #821's head `3415906d`, which
   merged at 16:37 BRT, with 21 stages: "expected time left 40m48s of 47m33s" at 18:08 BRT (#821's status comment).
   Its structure check failed after 5m14s. Meanwhile no new head is gated: #822 has no gate comment.
4. **939 of the 3,193 engine paths that have an area pull OU stages on a one-file diff.** 925 add `install (frozen
   lockfile)` and `unit tests`, 9 add those plus `gate-db`, and 5 select almost the whole battery.
   `plan_for(['scripts/lib/train.py'])` gives the reason: "web test
   apps/web/scripts/lib/architecture-engine.test.ts reads an unknown path" (`gate_web_readers.extend`, called from
   `gate_areas.py:475`).
5. **15 of the 23 stages are OU's, and recent engine PRs paid for them.** Engine stages: the 7 `always` and `script
   tests`. Verdicts read back (wall, stages, OU stages): #816 105 s, 10, 2; #818 249 s, 10, 2; #819 329 s, 10, 2;
   #820 165 s, 8, 0; #821 173 s, 8, 0. #817 was a full battery (21 stages, 13 OU) of 226–533 s in a 4-vCPU session.
   On the VM a full battery is expected at 47m33s (finding 3).
6. **Engine rules are proven only inside OU.** OU's vitest suite carries engine coverage with no engine-side
   equivalent:
   - "merge-phase decides on the local gate, not on GitHub checks" (`apps/web/src/site/domain/no-github-actions.test.ts`).
   - The repo-wide "no legacy `@legacy.example` address" (`no-legacy-email.test.ts`).
   - The raster asset guard (`apps/web/scripts/repo-assets-check.ts`, launched with `pnpm` in `$web` by
     `scripts/lib/gate-fixed.sh:115`).
   - The architecture checker's own mechanics (`architecture-engine.test.ts`, the generic cases of
     `check-architecture.test.ts`).
   - The preview policy rules (`preview-deploy.test.ts`).

   The hermetic harness and TX32's stale-address rule are already covered on the engine side (`test_hermetic.py`,
   `test_unit_addresses.py`).
7. **The engine's architecture checker has no subject outside OU and imports OU code.** All 25 rules of its
   manifests target `apps/web/src`. No stage runs `scripts/check-architecture.mjs` on engine code: its only real-tree
   run is `check-architecture.heavy.test.ts`, in OU's `performance tests`. `scripts/lib/architecture/tree.mjs:8`
   imports `../../../apps/web/scripts/lib/census-files.ts`, and `units/engine-architecture-check` requires the OU unit
   `tooling-literals`.
8. **The unit manifests split cleanly.** 113 manifests: 74 own only `apps/web/**` paths, 39 own none, and 0 own both.
   The 10 cells (`units/cells/*.json`) are OU contexts except `engine`.
9. **26 OU files read engine paths.** Examples: `apps/web/vitest.config.ts` reads
   `config/registry/{battery,tests,units,generate}.json`; `ou-addresses.mjs` and `perf-catalog.ts` read the registry.
   The engine writes into OU: `scripts/generate` renders `apps/web/tsconfig.paths.json`, and the merge driver
   regenerates OU's generated files (`units/engine-merge-regenerate`). Some registry keys are read only by OU
   (`battery.alone_max_workers`, `tests.timeout_ms`, `budgets.perf_*`, `budgets.bundle_*`, `text.empty_catalog_*`).
   Two engine node tests load through `apps/web/package.json` (`scripts/tests/media-parity.test.mjs`,
   `production-capture.test.mjs`, in the non-dev stage `capture regression`).
10. **The engine's own suite, baseline.** `scripts/test-suite` (all of `scripts/tests/*.test.sh`, nothing answered by
    key): 111 script tests, 111 ran, wall 329 s on 4 vCPUs. One failed, `structure-check.test.sh`, because this
    unit's folder held `intake.md` without `research.md` in the working tree during the run. Rerun alone on the clean
    tree: PASS (20 tests, 72 s). Python test files 136 (`scripts/tests/test_*.py`) with 2,258 `def test_` functions.
11. **Production of a paused product is up, and this session cannot reach it.** `scripts/cloud/preflight` exits 2:
    `missing NEON_API_KEY`, `missing VERCEL_TOKEN`. The proxy status shows CONNECT to `api.vercel.com:443` and
    `console.neon.tech:443` answered 403 (policy denial). No step of this unit needs Neon. The Vercel action needs a
    credential this session does not have.
12. **The archive is cheap.** 3,830 commits, 1,236 of them touch `apps/web`; `.git` is 179 MB. `git subtree` ships
    with git 2.43 here, and `git filter-repo` is not installed.

## Métricas
| Metric | Kind | Baseline (measured) | Target |
|---|---|---|---|
| M. Acting engine files that name `apps/web` | main | 351 | 0, held by a check |
| T1. Tracked paths with no area | target | 16 | 0, held by a check that fails on the first new one |
| T2. Engine paths whose one-file diff selects an OU stage | target | 939 of 3,193 | 0 |
| T3. OU stages in the gate's plan | target | 15 of 23 | 0 |
| T4. OU files in the tree (`apps/web/**`) / OU unit manifests | target | 1,249 / 74 | 0 / 0, after a pushed archive tag |
| G1. Engine script tests (`scripts/tests/*.test.sh`) passing | guard | 111 of 111 (finding 10) | not lower, except tests of removed OU code, each listed with its reason |
| G2. Engine Python test functions | guard | 2,258 in 136 files | same rule as G1 |
| G3. Engine gate of each PR | guard | green on every head merged | green; same 8 engine stages |
| G4. Engine gate wall for an engine-only diff (session) | guard | 105–329 s (#816–#821) | not slower |
| G5. Engine behaviour | guard | the train merges, the runner and control-plane tests pass | unchanged: each PR of this unit merges through the train |
| G6. Neon and R2 data | guard | untouched | untouched: no command of this unit addresses them |

## Causas raiz

### R1. The engine has no declared boundary with the products it delivers
Cadeia de porquês:
1. Por que do 351 acting engine files name `apps/web` (finding 1)? Because the gate, the area map, the generators,
   the census, the merge driver, CODEOWNERS and the docs address OU's paths as constants.
2. Por que are they constants and not a product's declaration? Because the engine was grown inside OU's repository
   to deliver OU: the gate began as OU's CI (ADR-24), and every later layer took OU's layout as given.
3. Por que did moving literals into the registry (D-068) not separate them? Because the registry made the values
   configurable, not foreign. `gate-areas.json`, `gate-web-readers.json` and the census still describe one product,
   and nothing tells an engine value apart from a product value.
4. Por que did no check object? Because no rule says the engine may not depend on a product. The literal census
   accepts a registered `apps/web`, and the unit manifests give OU and the engine separate units (finding 8) but
   no direction between them.

Classe: arquitetura/desenho
Evidência: findings 1, 7, 8, 9; `scripts/lib/gate-areas.json` (11 of 15 areas name `apps/web`); `units/engine-*` vs
the 74 OU manifests.

### R2. The area map is not total, and both of its fallbacks are "run everything"
Cadeia de porquês:
1. Por que do 16 paths run the full battery (finding 2)? Because `plan_for` returns the full plan on an unmapped
   path, and those paths match no area.
2. Por que do they match no area? Because `services/` (GATE-TRAIN-SERVICES), `.cursor/`, `.claude/`, the hooks and
   the root dotfiles were added without an entry in `gate-areas.json`, and nothing asked for one.
3. Por que did nothing ask? Because no check states the invariant "every tracked path belongs to an area". The map
   was built as an optimisation on top of "run everything", so the old behaviour stayed as the fallback.
4. Por que is the fallback silent? Because it is correct (it never under-tests) and its price, about 47 minutes of
   the single VM runner, is paid by someone else's queue. The empty diff takes the same branch (finding 3), so a
   merged head runs the whole battery.

Classe: regra faltando
Evidência: `scripts/lib/gate_areas.py:439-450`; findings 2 and 3; #821's status comment.

### R3. Engine checks were written as product tests
Cadeia de porquês:
1. Por que do 939 engine paths pull OU's install and unit tests (finding 4)? Because `gate_web_readers` finds an OU
   vitest file that reads engine paths it cannot resolve, and fails closed by attaching OU's unit tests to every
   engine path.
2. Por que does an OU test read engine paths? Because engine rules and the architecture checker's mechanics were
   tested in OU's vitest suite (findings 6 and 7).
3. Por que there? Because OU's suite was the only TypeScript test runner in the repository, and the checker is
   JavaScript. The engine's `node --test` harness came later (`scripts/tests/control-plane.test.sh`) and nothing
   moved the older tests.
4. Por que did that not show? Because no rule says a test lives with the code it proves, so the coverage looked
   complete while it sat in the product.

Classe: arquitetura/desenho
Evidência: findings 4, 6 and 7; `plan_for(['scripts/lib/train.py'])` reasons.

### R4. The repository has no procedure to retire a product
Cadeia de porquês:
1. Por que is a paused product's site still up, and its code still in the engine's repository (finding 11)? Because
   pausing OU changed nothing in the repository or in production.
2. Por que did it change nothing? Because the delivery rules cover creating and changing units (D-077) and freezing
   production (D-054), but no rule covers archiving, removing and decommissioning a product, or their order.
3. Por que is the order the hard part? Because the gate is pinned to the base (P-46, D-096). A removal is judged by the
   base's gate, so the gate must stop depending on the product before the removal lands, and the archive must exist
   before either.

Classe: regra faltando
Evidência: findings 3, 11 and 12; D-054, D-096; no `retire` in `docs/process/`.

## Distância do estado da arte
- Boundaries: we are on rung 0. The research's reference declares product boundaries and fails the build on a
  crossing (Bazel visibility, Nx, Packwerk). Here the engine reaches into the product in 351 files, and the product
  into the engine in 26.
- Ownership: partial. The area map plays the role of Bazel packages but is not total (16 gaps) and fails open.
- Affected sets: closer than the rest. Script tests are already selected by declared covers and answered by content
  key (GATE-SPEED). The cross-product reader scan is the weak link: an unknown read selects everything.
- Archive and retirement: absent. There is no tag, no extraction procedure and no decommission rule. The cheap
  standard (tag, filter-repo on demand, a reversible pause) is all available for free.

## Base defects expected
- The VM runner gates a merged head with the full battery (finding 3). It holds the only runner for about 47 minutes,
  so this unit's gates run in its session (`scripts/gate-dev --pr N`, AGENTS.md) and its merges go through the train.
- The runner's known orphan: a job killed at `service.job_timeout_s` (3,600 s) leaves `gate-local` holding
  `.gate/gate.lock` (Daniel's note). #821's 47-minute job is close to that limit. Owner: engine-service.
- `scripts/cloud/preflight` exits 2 in this session for the missing Neon and Vercel credentials, a policy of this
  environment and not a repository defect.
