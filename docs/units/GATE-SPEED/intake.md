# GATE-SPEED — intake

Unit, stage 1 of the unit flow (D-077, Padrão v7). Complete on its own; the research, the audit and the plan are
separate products.

## Pedido
Daniel (CEO), chat, 30/10/2026 10:43 BRT, top priority, critical (English, literal excerpts):

- "make A Torre's whole test suite run in <= 10 s on A Torre's own runner, and the whole gate fast end to end."
- "The whole test suite runs in <= 10 s wall on A Torre's runner: the Google Cloud VM `the-tower-runner` (e2-micro,
  us-central1: 2 shared vCPUs, 953 MB RAM, 2 GB swap, pd-standard disk; kind `vm`; always on, so it can stay warm).
  'Whole' means every test, not only a selected subset. Ideal <= 1 s. Over 1 s is a WARNING only (report it, keep it
  visible); over 10 s fails the goal."
- "The whole gate end to end is fast: Daniel accepts about 1 min from push to verdict, overhead included; ideally much
  less. A docs-only change must not pay for unrelated suites."
- "The tests themselves must run in parallel (processes, workers, shards, whatever the research and the audit show is
  best on 2 vCPUs and 953 MB). The WORK of this program is serial."
- "Measure on the actual e2-micro, through A Torre's runner/gate service (scripts/service runner, gate jobs), not on
  the session's container; the container's numbers are context only."
- Two runner blockers to fix early in their own commit: control-plane requests answered 403 for urllib's default
  User-Agent, and the runner's `git push origin …:refs/heads/train/lock` over its 120 s timeout.
- "Total autonomy … Two things stay fixed: (a) checks keep their meaning: never 'pass' by deleting, skipping or
  quarantining coverage … (b) never loosen a threshold or timeout to make something pass." "If some category
  physically cannot fit 10 s on an e2-micro (e.g. a browser e2e or a production build), measure it, record a D-xxx with
  the numbers and the choice … and report it as a goal miss, never hide it."
- "Free tiers only, nothing that costs money: the e2-micro is the Always Free VM; no bigger machines."

## Intenção
The gate is the factory's clock: every PR waits for it, and the train waits for it again after every merge. At 36 min
for a docs-only change on the machine that is meant to run it without any AI session, the services built in
GATE-TRAIN-SERVICES cannot keep up with one PR an hour, let alone the lanes. Daniel wants feedback as fast as a
developer's own test run: the verdict arrives while the author still has the change in mind, the train merges within a
minute of green, and the free VM is enough for the whole factory. "Whole suite in seconds" is how the fast shops
(Google TAP, Bazel users) keep that promise: nothing that did not change is run again, and what runs is cheap.

## Contexto
State on 30/10/2026 10:49 BRT, base `mod/roadmap-integration` at `bdbdbb83` (#810):

- **The runner.** `the-tower-runner`, a GCP e2-micro (Always Free): 2 shared vCPUs (a shared-core machine: GCP documents
  0.25 vCPU sustained in total, bursting to both vCPUs for short periods), 953 MB RAM, 2 GB swap, pd-standard disk. It runs `scripts/service runner` (ADR-41, D-086); its
  `service.transport` was set to `control` at 09:42 BRT (`config.changed` on #548, actor `the-tower-runner`). This
  session has no shell on it: its numbers reach us only as the gate's own events and comments (`gate.passed` and
  `gate.failed` carry stage times; the gate-status comment carries "Finished in" and the GitHub calls).
- **The baseline Daniel measured on the VM** (30/10 09:57–10:34 BRT, `scripts/gate-dev --pr 811`, a docs-only change,
  head `41e75520`): wall 36 min 47 s. Stages about 16 min: script tests 704 s, secret scan (history) 191 s, structure
  check 154 s, PR metadata 111 s, secret scan (tree) 94 s, schema compat 39 s, generated drift 4 s, no GitHub Actions
  workflows 1 s. The report about 17 min: it reran the failing stages on the base and made 128 GitHub calls, 98 of them
  GETs of the PR's comment list. Peak memory 460 of 953 MB, largest process 258 MB, no swap pressure. The three red
  stages were the PR's own (84 commits behind its base).
- **The same gate on this session's container** (4 vCPUs, 16 GB): this PR's first head (one line of
  `DECISIONS.md`) took 162 s, with structure check 21 s, script tests 11 s (three tests), PR metadata 7 s, history
  scan 8 s; the second head (a registry key, a hook, two tests) ran the web stages too. Context only.
- **The runner blockers**, confirmed in this session before any measurement: urllib's default agent on every
  control-plane request; and `.githooks/pre-push` running commit_check, three script tests and the open-PR overlap on
  a one-file record commit pushed to `train/lock` (26 s here). Fixed in commit 2 (D-091); they reach the VM when this
  PR merges (the runner works from the base).
- **What "the whole test suite" counts today** (this checkout, `bdbdbb83`):

  | Category | Unit of count | Count | Runs in |
  |---|---|---:|---|
  | Script tests | `scripts/tests/*.test.sh` (each runs Python `unittest` files and shell cases) | 111 scripts, 159 Python test files, 2,262 `def test_` | `script tests` |
  | Web unit | `apps/web/src/**/*.test.ts(x)` outside int/perf/heavy | 234 files | `unit tests` |
  | Web integration | `*.int.test.ts` (PostgreSQL) | 7 files | `integration tests` |
  | Web performance | `*.perf*.test.ts`, `*.heavy.test.ts` | 2 files | `performance tests` |
  | Browser | `apps/web/e2e/*.spec.ts` (Chromium smoke S01–S40 in dev; three projects at night) | 31 files | `e2e` |
  | Service | `services/**` `node --test` | 2 files | `script tests` (control-plane.test.sh) |
  | Static checks | structure check, generated drift, schema compat, literal census, secret scans, lint, typecheck, shellcheck | 1 each | their stages |
  | Builds | test engine build, production build | 2 | their stages |

  The plan counts each category separately: "whole suite" in T1 is every test of every category that is a test (the
  first five rows plus services); the static checks and builds are gate stages, measured in T2/T3, and a category that
  cannot fit 10 s is a recorded miss, never left out of the count.
- **Prior units this one builds on:** GATE-FAST (D-076: content-keyed results, the script-test map, two slots per box;
  its retro left "the report reads GitHub 156 times" as the largest slice); GS1/D-064 (f) (parallel lanes, the 180 s
  ceiling); GATE-ON-PUSH and GATE-TRAIN-SERVICES (the gate on push, the runner, the windowed #548 read, D-085);
  test-excellence (TX01, the pre-push check); gate-excellence (the pinned gate, carry-over GX-20, sharded tier 2).
- **Open drafts in the same area, not edited:** #796 (RULE-AUDIT-GATE-EXECUTION-AND-TESTS), #793
  (RULE-AUDIT-GATE-SELECTION-PROOF-AND-STATUS).

## Regras
- D-077 and D-081 (the unit flow, Padrão v7: root causes by a chain of whys, weighed alternatives), D-084 (intake and
  research share a commit), D-083 (a draft is judged on delivered items), D-090 (this unit's STEP 0), D-091 (runner
  blockers).
- D-054 (production frozen), D-055 (no review step), D-065 (events, never a clock; push every commit), D-022/D-025
  (3–8 item plan, one commit per push, a gate change cites a D-NNN), D-064 (f) (the 180 s ceiling: a warning, never a
  failure), D-068/D-069 (registry values, no literals), D-070/P-46 (the pinned gate judges with the base's tooling),
  D-076/P-56 (content-keyed results), D-086 (the runner), ADR-34 (no 3-browser battery before merge).
- Daniel's fixed rules for this unit: no coverage removed, skipped or quarantined (a merged test keeps an equivalent
  assertion, counts before and after); no threshold or timeout loosened; free tiers only; production untouched;
  nothing Cloudflare-specific; no secret anywhere; save REST quota (check `rate_limit` before each gate, never poll).

## Problema real
On the free e2-micro the gate takes 36 min for a docs-only change because it re-runs work that did not change (the
whole script suite, a full-history secret scan, the whole structure check), pays a subprocess, an interpreter and a
temporary git repository per test case, and then spends as long again re-running red stages on the base and reading
GitHub; so the runner cannot keep up with the factory.

Resolved when, measured on the e2-micro through the runner's gate jobs (cold and warm, p50/p95 over several runs, peak
memory), with the numbers quoted in the retro:
- **T1 whole suite:** every test of every category above, warm, ≤ 10 s wall (warning above 1 s); a category that
  physically cannot is measured and recorded as a D-xxx miss with its own tier.
- **T2 push → verdict:** p50 ≤ 60 s for an ordinary PR, overhead included (today 36 min 47 s).
- **T3 docs-only:** a change of documents alone runs no script, web or browser suite; its gate ≤ 30 s.
- **T4 GitHub reads per gate:** ≤ 30 (today 128 on the VM, 30 on this container's docs-only head).
- **T5 memory:** peak ≤ 600 MB of 953 MB (today 460 MB), no swap pressure.
- **T6 counts:** the number of tests and assertions before and after, per category, never lower.

## Lacunas
Daniel asked not to be asked; each gap is decided and recorded:
- **Shell on the VM.** This session cannot reach the VM (no `gcloud` credential, no SSH). The VM's numbers come from
  its runner's gate jobs on this PR's heads and their events; until the runner takes jobs, the container's numbers
  stand in, labelled as context. If the runner never gates a head of this PR, the VM measurement is Daniel's step,
  with the exact command, recorded as a D-xxx.
- **The runner's code is loaded once.** `scripts/service runner` refreshes its checkout but keeps the Python it
  started with, so a merged fix to the runner itself reaches the VM only after a restart (`Restart=always` restarts it
  only when it exits). Whether that needs Daniel is for the audit and the plan.
- **Burst credits.** An e2-micro's two vCPUs sustain a fraction of a core; how long a warm run can burst is measured,
  not assumed.
