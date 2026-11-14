# Program TX-PROGRAM (test excellence): audit

Read-only, cheap evidence. Window: every red gate and every `pr.conflicted` on all PRs and on tracker #548 since 2026-10-27 23:00Z (20:00 BRT) up to 04:04Z on 28/10 (531 comments on 55 issues and PRs, 209 unique forge events, 8 REST calls), plus the changed files of the 50 open PRs and the 26 PRs merged in the window (76 heads, `git diff --name-only <merge-base>..<head>`). Base `mod/roadmap-integration` at launch: `891b835a`. Design target: 1,000 PRs per day (about 42 per hour); 10k and 100k are a distant horizon and are not designed for here.

## 0. Principles of an excellent test system for this engine (derived from the evidence below)

At 1,000 PRs a day, with a PR alive one to two hours, 40 to 80 PRs are in flight at any moment. A file that a fraction *f* of PRs edits has about 40·*f* to 80·*f* concurrent editors: `scripts/tests/gate-local.test.sh` was edited by 4 of the 76 PRs in the window (5 %), so at 1k/day it would always have two to four editors in flight and nearly every merge would conflict on it. Anything shared becomes a queue. The principles, each with the evidence that forces it and how it holds at 1k/day:

| # | Principle | Evidence tonight | How it holds at 1,000 PRs/day |
|---|---|---|---|
| T1 | **Additive ownership.** A unit adds a test by adding a file only it edits; discovery is by directory or glob; no unit edits a shared test file or test list. | `gate-local.test.sh`: 4 train `pr.conflicted` + 5 lane-side conflicts, 3 PRs, all on one loop line (§1 row 5, §2). | Per-feature part files under a suite directory; the runner globs them. Concurrent editors of a shared test file: 0 by construction. |
| T2 | **Derived, never hand-kept.** An inventory computable from the tree (companion ownership, CODEOWNERS, literal baselines, expected stage lists, pinned hashes) is derived; a list that records a decision stays hand-kept but its check runs locally in seconds and names the exact line to add where. | CODEOWNERS edited by 30 of 76 PRs; literal baselines and catalogs: 12 + 6 + 9 conflicting PR pairs; `units.test.sh` red on #740 (a covers file registered twice); literal census red on 3 PRs and structure check on 5 (§1 rows 3, 6; §2). | A hand list edited by every PR is a guaranteed collision at 40/hour; derived data is never merged by hand. |
| T3 | **Sound selection.** A test runs whenever a file it reads changes (declared covers plus traced reads, fail closed); cost scales with the change, not with the repository. | Base red 112 min, 27 PRs blocked: a web unit test (`apps/web/src/site/domain/no-github-actions.test.ts`) reads `scripts/merge-phase`; #722 changed that script and its gate ran no unit tests (§1 row 1). | Under-selection turns into a red base, which blocks all ~40 PRs of the hour; over-selection costs minutes per PR. Both are measured per gate. |
| T4 | **Automatic attribution.** The gate classifies every red as own / base (known defect at a recorded base) / env / flake / contract; only own turns a PR red; the rest is visible and routed to its owner. | 22 of 32 red PRs were red for a base defect (row 1) the known-defect route did not cover (it excuses only `script tests` reds); env failures kept 5 gates from starting (row 2). | A human reading logs does not scale past a few PRs an hour; classification must be data. |
| T5 | **Base never red.** Whatever merges has run every test that reads what it changed, on the merge result; a red base is an incident with an owner and it holds only its own class. | Two base-red episodes: 112 min (row 1) and 25 min (row 9); the train stalled 52 + 12 min. | One red hour = ~40 PRs re-gated. |
| T6 | **Hermetic and deterministic.** No shared `/tmp` path, port, global state, wall-clock or ordering dependence; each test owns its temp dir; the gate's own state never leaks into test children. | `/tmp` races (row 10: `runner_started_at.stage.json`, gate-result-cache marker, hermetic), gate state leaking into children (row 11: call-count file, `OU_GATE_TIER=1`), report-order race (row 4). | With 4 to 8 gates per container and parallel test processes, a shared path is a collision every hour. |
| T7 | **Load-independent.** A verdict never depends on machine load: waits are on events, never fixed sleeps; a timeout is never raised to pass. | vitest `Test timed out` in three suites on loaded gates (row 7). | Load is the normal state at 1k/day. |
| T8 | **Flakes visible, never silent.** A test that passes on an identical rerun is recorded as a flake with signature, owner and expiry through the known-defect registry and shows in every report; nothing is skipped by hand. | #717 green on retry, printed `class env` (row 10). | Silent flakes compound: a 1 % flake per test across 200 script tests reds most gates. |
| T9 | **Feedback in seconds before push.** One command, on the local diff: ownership, inventories, literals, covers and structure checks, the owning tests of the changed files, and a warning when a changed shared file is also in another open PR. | 6 of the 10 own-fault reds were inventory or structure misses found only at the full gate (rows 3, 6, 12); `unit_check.check` finds #740's miss in 0.7 s. | Every gate run saved is a slot for another PR. |
| T10 | **Refactors keep every assertion.** A split counts assertions before and after; a failure message says what to do. | (this program) | Counted in the PR, checked by the suite runner (a part with no check fails). |

10k and 100k PRs/day: the same principles, with selection and caching sharded per unit; not designed here.

## 1. Inventory (ranked by PRs blocked)

Signatures as the gate recorded them (digits as `N`). Wall-clock in minutes, from the red event to the next green or merge on the same PR.

| # | Signature (exact quoted line) | Cause (file:line) | PRs blocked (n) | Wall-clock lost | Class | Decision | Cost |
|---|---|---|---|---|---|---|---|
| 1 | `AssertionError: expected '#!env bash\n# scripts/merge-…' to contain 'local gate'` (`no-github-actions.test.ts > … merge-phase decides on the local gate, not on GitHub checks`) | the web unit test `apps/web/src/site/domain/no-github-actions.test.ts` reads `scripts/merge-phase`; #722 changed it and its gate selected no `unit tests` stage (a scripts-only diff skips the web stages) | 27: #586 #592 #596 #610 #615 #618 #620 #622 #625 #626 #632 #633 #635 #641 #643 #644 #645 #649 #659 #662 #663 #724 + batch #580 #605 #607 #671 #726 | base red 112.5 (#722 merged 00:43:41, fixed by #730 02:36:12); train stalled 52.4; 8 ready PRs waited 39–78 | (c) base-red, root cause T3 | fix at the cause: web tests that read repository files outside `apps/web` are selected by a change to those files (unit TX20) | M |
| 2 | `config.StoreError: ... rate-limited; ... wait N s, more than github-client.max_wait_s (N s)`; `scripts/cloud/env.sh: line N: _ou_cloud_postgres_host[0]: unbound variable`; `FAIL env: missing toolchain: python … postgres`; `missing host tool: python3` | setup and preflight before the gate (config store over GitHub REST, `scripts/cloud/env.sh`, toolchain) | 5: #730 #731 #732 #733 #734 | #730 ~25, #732 20, #734 ≥120 | (c) env | classify (already `FAIL env`); the offline path `OU_CONFIG_STORE=file` is the sanctioned bootstrap; backlog B-env | S |
| 3 | `… and N more` (`scripts/tests/structure-check.test.sh` + structure check stage) | the unit's own new literal or covers file against the LT1 inventory; the local `structure_fast` check runs no literal census | 5: #724 #726 #731 #735 #740 | 3.1, 9.6, 2.8; #724 and #740 still red at the pause | (b)+(e) | caught locally in seconds with the exact fix (unit TX01, this PR) | S |
| 4 | `AssertionError: ['a', 'b', 'c', 'd', 'e'] == ['a', 'b', 'c', 'd', 'e']` (`gate-graph.test.sh`, `test_the_report_order_does_not_depend_on_the_finishing_order`) | a race on the finishing order | 4: #592 #622 #635 #662 | hidden by row 1 | (d) | fixed at the cause in #735 (`9aff4127`); verified in §5 | – |
| 5 | `pr.conflicted` on `scripts/tests/gate-local.test.sh` | the hook no-op loop `for h in …` (`scripts/tests/gate-local.test.sh:170` on the base) edited by GX-10, GX-11, GX-15 and GX-20 | 3: #732 #733 #739 (4 train + 5 lane-side conflicts) | #733 36.6; #732 ≥68 and still open | (a) | restructure: one part file per feature and per hook (TX00, this PR) | S |
| 6 | `AssertionError: Lists differ: ['scripts/tests/test_claude_settings.py: n[N chars]T1)'] != []` (#724), `['scripts/lib/gate_publish.py: number N is[N chars]T1)']` (#726), `['scripts/lib/absolute-literals-baseline/e[N chars]ite']` (#735) | `scripts/tests/literals.test.sh`: a unit's own new literal (LT1) or a stale baseline | 3: #724 #726 #735 | 3.1, 2.8 | (b)+(e) | caught locally with the exact fix (TX01) | S |
| 7 | `Error: Test timed out in N0ms.` | vitest `catalog-cli/sync.test.ts`, `absolute-literals.test.ts`, `identity/server/handler.test.ts` on a loaded gate | 3: #622 #626 #633 | hidden by row 1 | (d) | fix the cause without raising a timeout (app lanes: TX30, TX31) | M |
| 8 | `bash: scripts/tests/planner-role.test.sh: No such file or directory`; structure check or schema compat with no test id | head behind a base that moved mid-run (#724 43 behind; #726 e783d052 2 s after a base move; #735 pinned to a fetched tip) | 3: #724 #726 #735 | 2.2, 3.4 | (c) | classify as env (base moved) through the existing route; backlog B-base-moved | S |
| 9 | `FAIL - each stage measured` (`scripts/tests/gate-db.test.sh`) | base red after #716; known defect KD-335a14a4 (`ModuleNotFoundError: No module named 'forge_events'`) hid it in earlier runs | 3 held in the train (#615 #705 #714) + #716 | base red 25.2; train held 11.6 | (c) | already fixed on the base (#721); verify in §5 | – |
| 10 | `FileNotFoundError: [Errno N] No such file or directory: 'runner_started_at.stage.json'` (gate-local, #626); `FAIL expected [N] got [N]: a corrupt marker runs the stage again` (gate-result-cache, #717, green on retry); `AssertionError: Items in the first set but not the second:` (hermetic, #722) | shared `/tmp` between concurrent tests and gates (`scripts/lib/gate-runner.sh:79` copies every failed stage log to a fixed `/tmp/gate-local-<name>.log`) | 3: #626 #717 #722 | #717 10.1; #722 6.0 | (d) T6 | fix at the cause: a private `TMPDIR` per script test (TX10) | M |
| 11 | `AssertionError: Tuples differ: (N, 'forge: N writes, N reads (GitHub calls of[N chars])\n') != (N, '')` (#716); `AssertionError: Tuples differ: (N, 'db') != (None, 'db')` + `Lists differ: ['defect.detected', 'defect.verified'] != []` (#733) | the gate process leaks its state into test children (a forge call-count file, `OU_GATE_TIER=1`) | 2: #716 #733 | 5.0, 6.4 | (f) T6 | fix at the cause: the script-test runner scrubs the gate's own variables from test children (TX10) | S |
| 12 | `FAIL gate has not passed at abcN …` (claude-session, #722); `AssertionError: False is not true` (gate-pin, #731); push-guard tuple (#732); PR body without the plan checklist (#736) | the PR's own change | 4: #722 #731 #732 #736 | 6.0, 9.6, 11.6, 3.1 | own (e) | the owning tests in the pre-push check (TX01) | – |
| 13 | `budgets.web_bundle_bytes_max` value 695469 > limit 695296 | the web bundle grew past its budget on the base | 1: #586 | still open | (c) base | classify (base budget, not a test); backlog B-bundle; the limit is never raised by this program | – |
| 14 | `eslint-config: no renderer scripts/lib/generate_eslint_config.py` | the pinned base tooling cannot render a target the head adds | 1: #662 | hidden by row 1 | (f) | contract: pinned tooling vs a new generator target; backlog B-pin-render | – |

Totals: 40 `gate.failed` on 32 PRs, 2 train holds on a red base, 5 `pr.conflicted` on 2 PRs (4 name `gate-local.test.sh`) and 8 lane-side base-merge conflicts (5 on the same file). Own-fault reds: 10 PRs, 6 of them inventory or structure misses. Not the PR's own fault: 22 PRs on row 1 alone.

## 2. Overlap of shared files across open PRs

76 heads (50 open, 26 merged in the window); 128 files are touched by 2 or more. Test files, test registries and inventories first. "m" = merged in the window.

| File | Kind | PRs | n | What each PR does |
|---|---|---|---|---|
| `CODEOWNERS` | generated inventory (from `units/*/unit.json`) | 22 open + m580 m714 m717 m722 m723 m726 m733 m739 | 30 | each inserts its own sorted path lines; #625 and #626 conflict |
| `apps/web/tsconfig.json` | registry (path aliases) | 26 U4 PRs | 26 | each adds one `@ou/<unit>` alias; no pair conflicts yet |
| `scripts/lib/absolute-literals-baseline/scripts.json` + `scripts/lib/literal-catalogs/scripts.json` | inventory (literal baseline and catalog) | 618 622 625 626 632 633 635 | 7 | the baseline loses each PR's block; the catalog gets an insert at the same top slot; 12 PR pairs conflict |
| literal baseline + catalog `app.json` | inventory | 588 591 592 600 | 4 | same catalog slot; all 6 pairs conflict |
| literal `catalog`/`platform`/`ui.json` | inventory | 641/644/675, 645/674/681, 649/659/663 | 3 each | same top-slot insert; each trio conflicts pairwise |
| `units/engine-gate-report/unit.json` | inventory (ownership) | 683 740 m720 m726 m733 m739 | 6 | each adds its own paths; #740 conflicts with #739 |
| `scripts/tests/gate-local.test.sh` | test | 732 m727 m733 m739 | 4 | all edit the same hook no-op loop line |
| `config/registry/tests.json` | registry | 610 678 687 689 | 4 | each deletes one exemption line |
| `scripts/tests/rest_fake.py` | test helper | 667 m720 m722 | 3 | #722 and #667 both add a `/compare/` route |
| `scripts/tests/test_gate_areas.py` | test (expected stage list) | 732 m671 m736 | 3 | a stage-adding PR edits the expected list line |
| `scripts/tests/test_gate_report_skips.py` | test (pinned `BEFORE_SPLIT` sha256) | 732 m705 | 2 | every PR that adds a stage re-pins the hash |
| `scripts/lib/gate-stages.json`, `scripts/lib/gate-areas.json` | registry (stages) | 683 732 m671 m736 | 2–3 | #683 and #732 conflict on `install.needs` |
| `units/engine-train/unit.json` | inventory | 689 741 m717 | 3 | #689 and #741 insert at the head of `paths` and conflict |
| `config/registry/defects.json`, `merge.json`, `gate.json` | registry | 667 683 m720 m722 m725 m729 m731 m737 | 3 each | appended key blocks; #667 add/add on `merge.json` |
| `scripts/lib/gate-script-tests.json` | inventory, deleted on the base by GX-08 | 667 683 | 2 | modify/delete conflict |
| `scripts/tests/covers/*.json` (push-guard, planner-role, defect-detect, gate-report-skips, gate-result-cache) | inventory (one file per test) | 732/m723, 734/m714, merged pairs | 2 | appended `covers` lines to another test's manifest |
| 8 `apps/web/test/int/*.int.test.ts` + `progress-oracle.ts` | test | 586 596 | 2 | both rewrite the same import lines; all 9 conflict |
| `gate-timing-report.test.sh`, `test_gate_timing_report.py` | test | 683 740 | 2 | add/add with different content |
| `test_gate_status.py`, `test_gate_report_skips.py`, `test_planner_role.py`, `test_gate_test_cache.py`, `test_gate_graph.py` | test | 740, 732, 734, 683, 683 + one merged PR each | 2 | appended or edited tests in a shared per-module test file |

Conflicts with the current base: #740 (`units/engine-gate-report/unit.json`), #683 (5 files), #667 (14 files), #662 (`scripts/lib/structure.py`), #610 #687 #689 (`CODEOWNERS`); the other 43 open PRs merge cleanly. `scripts/tests/units.test.sh` is touched by no open PR and `scripts/tests/structure-check.test.sh` only by #662: those two are not collision files, they are inventory checks (§3 b).

## 3. The five classes against the principles

### (a) Shared test-file collisions (T1)
- `scripts/tests/gate-local.test.sh` (185 lines, 59 `check` assertions, base `891b835a`) holds the checks of at least nine units (runner, secret scan, ceiling, KD1/GK1 verdict, GX-01 preflight, GX-38 hooks, and one hook each for GX-05, GX-10, GX-11, GX-19, GX-20). The collision line is the no-op loop `for h in …` (`:170`): each unit that owns a hook removes its name there and adds a check above it (#727, #733, #739, #732 each `+4/-1` on it). GX20's retro records the same conflict (`docs/units/GX20/retro.md:30`).
- The same pattern, not yet a collision tonight: per-module Python test files that several units append to (`test_gate_status.py`, `test_gate_report_skips.py`, `test_planner_role.py`), and `scripts/tests/rest_fake.py` (one fake, every unit adds a route).
- Discovery today: the gate discovers `scripts/tests/*.test.sh` by glob (`scripts/lib/gate_script_tests.py:24`, `discover`) and each has one covers manifest (`scripts/tests/covers/<test>.json`, GX-08). A new top-level test is additive already; a new check inside an existing suite is not.

### (b) Tests that fail on the unit's own additions to shared inventories (T2, T9)
- #740 (`8f6ba426`), exact: `scripts/tests/covers/gate-timing-report.json belongs to 2 units (engine-gate-plan, engine-gate-report); a file belongs to one unit (D-067 (6))` and `units/engine-gate-report: imports unit engine-slo without declaring it; add "engine-slo": "^1" to its requires or drop the import (D-067, U2)` (`scripts/tests/test_unit_check.py:185`, `unit_check.check`). Cause: `scripts/tests/covers/**` is owned by `engine-gate-plan` by glob (`units/engine-gate-plan/unit.json`), so a unit that registers its own covers manifest in its own manifest makes a second owner. Both messages already name the fix; the unit learned them only at the full gate, although `unit_check.check` takes 0.7 s on this checkout.
- Literal census (LT1, `scripts/lib/literal_census.py:192`): per-unit baselines `scripts/lib/absolute-literals-baseline/<cell>/<unit>.json` are exact counts per file. A PR that moves, adds or removes a literal rewrites its unit's baseline (`--write <unit>`); PRs of the same unit conflict there (§2). The census reads tracked files only: an untracked new file is not judged until it is added.
- Generated `CODEOWNERS` (`scripts/lib/generate_codeowners.py`) is committed and regenerated by every PR that adds a path to a manifest: 30 of 76 PRs.
- Expected lists inside tests: the stage list in `test_gate_areas.py:46`, the pinned `BEFORE_SPLIT` sha256 in `test_gate_report_skips.py:132`.
- The local check: `.githooks/pre-push` runs `scripts/commit-check --local`, whose `structure_fast` check takes 44 ms and does not run `unit_check`, the literal census or the covers map.

### (c) Base-red and env failures (T4, T5)
See §4 (known defects and backlog) and rows 1, 2, 8, 9, 13 above.

### (d) Load flakes (T6, T7, T8)
See §5 and rows 4, 7, 10, 11.

### (e) Local feedback (T9)
See §6.

### (f) Other items in the same class
- Row 14: the pinned base tooling cannot render a generator target the head adds (contract between pinning and new targets).
- The full-mode `shellcheck` stage (`scripts/gate-local:373`, only when `dev=0`) is red on the base: 39 findings, exit 1, on `/usr/bin/shellcheck` 0.9.0 (not pinned in the toolchain). It globs `scripts/tests/*.sh` only, so nested suite files are not linted.

## 4. Known defects, base-red and env (class c)

- **The route works on every stage now.** GX-32 (#737) set `defects.stages` to script, unit, integration, e2e smoke and performance. NANO-UNBLOCK's B4 says "script tests only", which is stale. A failing test counts as a known defect when its file and covers are untouched (`defect_detect.py:240`) and it fails on the recorded base with the same normalized signature. For script tests that is checked by a base re-run (`:131-157`); for the other stages it comes from the tier-3 `base.red` listing (`:243-249`). A stage whose failures are all known flips to PASS and keeps `raw_result FAIL` (`:296-309`). It shows up in `stages.json`, in the verdict's `known_defects` (`gate_proof.py:49-51`), in `defect.detected` events and in the status table (`gate_status.py:190-196`). Records (`docs/process/defects/<slug>.yml`, changed only through `scripts/defects`) track and route; they excuse nothing.
- **Gaps that stay.** For the non-script stages the only base-red signal is the battery, and the battery is off (`config/registry/battery.json:98`). A load flake on the PR's own head therefore still blocks (backlog X6, unit TX11). Env is only a label (`gate_classify.py:46`): an env stage still fails, and an `AssertionError` anywhere in the stage log turns it into code. Root-identity and claude-session report a machine premise as code (`test_root_identity.py:41, :101`; X10, TX12). Classes are code, env and contract only, and anything unmatched defaults to code (`gate_classify.py:51`).
- **Config store without a token.** `test_config_api.py:281` calls `config.get('config.store_dir')` outside `use_adapter`, after `setUp` lifts the pin. Reproduced: 1 error in 5 tests. `scripts/run test` runs tests without the gate's pin (`scripts/run:40-41`). The gate passes only because `gate-local:253` exports `OU_CONFIG_STORE=file` (X10, TX10).
- **TMPDIR class.** Up to 8 script tests share one `/tmp` (`gate_test_cache.py:220-226`). `gate-runner.sh:79-80` copies every failed stage log to a fixed host-wide `/tmp/gate-local-<stage>.log`. The stage-record write ignores its exit code (`gate-runner.sh:62-68`), so a failed write only shows up later, at the reader (X7, TX10).
- **NANO-UNBLOCK backlog B1–B16:** each one is mapped in [backlog.md](backlog.md) (X1–X21), together with its route and owner.

## 5. Load flakes (class d)

| Item | Measured | Cause (file:line) | Fix at the cause (no timeout raised) | Lane, unit |
|---|---|---|---|---|
| `gate-graph.test.sh` order race | 21 tests OK at the base | fixed in #735 (`9aff4127`): `test_gate_graph.py:130-147` chains Events; residual: the `wait(5)` result is ignored (`:140`, `Barrier(timeout=5)` `:109`), so an expiry reads as an order mismatch | an expiry fails by name (optional follow-up) | engine-gate-plan |
| `catalog-cli/sync.test.ts` "enforces MEDIA_BYTE_BUDGETS" | 15 ms alone, 6.6 s under gate load | synchronous writes of ~2.6 MB into a shared tmpdir (`sync.test.ts:33-44`), never removed; the code under test reads only `statSync().size` (`covers.ts:50`) | sparse files (`truncateSync`), one dir per test, `rmSync` | tooling, TX30 |
| `absolute-literals.test.ts` | timed out once | 14 mkdir+write into the shared tmpdir (`:65-85`) | same as above | tooling, TX30 |
| identity `handler.test.ts` "returns an anonymous session…" | 611 ms first test vs 9–32 ms the others | `vi.resetModules()` (`:8`) plus `await import("./handler.ts")` (`:15`) put the cold better-auth load inside the 5 s timer, because `config.ts:153-165` caches `configuredAuth` at module level | a resettable cache, one import at the top | identity, TX31 |
| `rest-fake-ready.test.sh` (KD-41f822d3) | passes | `:22-26` starts 2 busy loops per core inside the parallel script-test stage, which slows every test next to it | run it in a stage that runs alone | engine-test-support, open (backlog) |
| B8 timeout mislabel | 148 s labelled "past 600 s" | `gate_kill_tree` (`gate-runner.sh:17-21`) kills the watcher's sleep first (X9) | kill the watcher first | engine-gate-run, TX10 |

No retry exists anywhere: Playwright `retries: 0` (`playwright.config.ts:38`), vitest has none, and the only re-run is the KD base re-run. Two historical loosenings are recorded, not changed here. The Python per-test bound went from 60 s to 600 s for the toolchain bootstrap (`c4d8e02b7`). Integration tests use 60 s test and hook timeouts, justified by "load ~16" (`apps/web/vitest.config.ts:99`).

## 6. Local feedback (class e)

- **The pre-push hook today.** `scripts/cloud/env.sh:42-46` installs `core.hooksPath=.githooks`, and `.githooks/post-commit:5` pushes every commit. `.githooks/pre-push` runs `commit_check.py --local --stdin-refs` with the registry `config/registry/local-checks.json`: 6 checks, a 30 s total budget, and a check over its budget moves to the gate. Measured: 76–84 ms on a small diff, 570 ms on a 53-file range, but **10.3 s cold**. The cold cost is the first `config.get` reading the GitHub change store, which no budget counts; with `OU_CONFIG_STORE=file` it is about 40 ms. The `structure_fast` check runs only decisions, queue, links, postmortems and premises: 44 ms of its 12 s budget.
- **What reached the gate instead.** All 46 errors of #740 (2 unit_check, 44 literal baseline) reproduce locally in **2.0 s**, against **3 min 46 s** for the gate run. The fast checks and their measured times:

  | Check | Time |
  |---|---|
  | `unit_check.check` | 0.66 s |
  | `literal_census.check` | 1.1 s |
  | `gate_script_tests.check` | 0.08 s |
  | `scripts/generate --check` | 0.19 s |
  | `assets.check` | 0.07 s |
  | `config_check` | 1.95 s |

- **Overlap with open PRs.** Nothing warns before a push. `pr.conflicted` is emitted only by the train (`train.py:183, :355`). One REST list of open PRs plus a local `git diff` per head present takes 1.4 s for 50 PRs.
- **Open PR #732.** It adds config_check, the literal census, vendor, unit_check and perf_tests to `local-checks.json` and edits `local_checks.py` and `test_local_checks.py`. TX01 therefore lives in its own files and calls into `.githooks/pre-push`; it does not touch those three files (a collision is not a dependency).
- **Hook environment.** A push started by `post-commit` hands the hook `GIT_INDEX_FILE=.git/index` and `GIT_AUTHOR_*`. A test that runs git in a fixture repository with that environment would write the real index, so TX01 scrubs every `GIT_*` variable from the test children it starts.

## 7. Whole test system census (base `891b835a`)

| Kind | Files | Assertions / cases | Discovery |
|---|---|---|---|
| `scripts/tests/*.test.sh` | 90 | 186 `check "` + 56 `expect`; 66 of the 90 only launch Python files | glob, top level only (`gate_script_tests.py:27`) |
| `scripts/tests/test_*.py` | 106 | 1,806 `def test_`, 4,323 `self.assert*` | **by hand** in a wrapper; 2 files run by nothing (`test_gate_gc.py` 10 tests, `test_text_check.py` 21; X17, TX25) |
| `scripts/tests/*.test.mjs` | 4 | 7 | wrapper |
| web unit `*.test.ts` | 286 (224 in `src`) | 1,257 `it/test(` | glob (`vitest.config.ts:84,97`) |
| `*.int.test.ts` | 46 | 258 | glob |
| e2e `*.spec.ts` / `*.production.ts` | 31 / 4 | 114 / 16 | glob (`playwright.config.ts:34`); dev smoke is a hand list of 40 titles (`gate-smoke.json`, count hard-coded `gate_suite.py:113`) |

The most-edited test files since 24/10 (commits / PRs) are `check-architecture.test.ts` 95/73, `test_train.py` 21/6, `media-gateway.test.ts` 21/20, `admin.test.ts` 19/14, `test_structure.py` 16/11, `gate-local.test.sh` 15/11, `test_forge_events.py` 15/10, `documents.test.ts` 13/11, the `admin-catalog.ts` fixture 13/13 (32 importers), `test_gate_areas.py` 12/9 and `rest_fake.py` 11/7. The most-shared inventories still in use are `DECISIONS.md` 52 PRs, `apps/web/tsconfig.json` 20, `schemas.lock.json` 15, `gate-areas.json` 13 and `units/engine-gate-report/unit.json` 11.

Selection replay over the 346 merges since 24/10, with today's selectors:
- **Script tests:** the whole suite ran in 56 % of 293 planned merges. The reasons were 125 uncovered paths, led by `scripts/check-architecture.mjs` with 68, and 38 selector edits, which include every covers manifest (TX26).
- **Web unit:** the full suite ran in 92 % of 219 merges.
- **Caches:** the unit cache key is the whole tree, and caches are machine-local, so every cloud session starts cold (X20).

Gaps at 1,000 PRs/day, as measured:
- About 470 full script suites a day at 107–270 s each, which is 14–35 machine-hours a day.
- A 0.5 % flake rate on one test gives about 3 false "code" reds a day.
- A red base blames up to 40 PRs an hour.
- Hot shared files serialize merges.
- 176 of 286 unit files can be deleted without any check failing, because the deletion baseline was frozen on 22/10 (open).
