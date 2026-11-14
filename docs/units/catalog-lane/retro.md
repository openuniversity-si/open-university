# U3b catalog lane: retro

Whole-unit retro (brief to accepted gate), per the RETRO rule. Times are UTC on 2026-10-27, approximate: commit times and gate report stamps, the rest read off the session.

## 1. Brief quality

- **Branch name conflict.** The brief names `mod/u3b-catalog-addresses`; the harness designates
  `claude/u3b-catalog-addresses-m02diu`. The designated branch was used (the system instruction wins). Fix: the brief
  template takes the branch from the launcher, never from prose.
- **Missing node-run caveat.** The brief and UNITS.md say `@ou/` is resolved by tsc, Next, vitest and the architecture
  checker. Nothing says plain `node` (postinstall, the catalog CLI, lint and perf scripts) cannot read tsconfig `paths`.
  That caveat decided the outcome of this unit: 424 of 500 specifiers stay relative until a loader exists.
- **Format of the dispatch.** The brief carried 8 superseded blocks (DECIDE, AGENT TREE, RETRO, parallel-session lists).
  The current rules were findable only by reading to the end. Fix: the launcher sends one current block.

## 2. Audit and plan

- Premise P-03 (address resolves to the file under the unit's home) **held** for every typed, tested and bundled path
  (`scripts/units addresses`, zero gaps, 500 specifiers planned, every battery `ok`).
- The audit's "no premise is critical" **was wrong**. The audit checked the typed graph, not the runtime graph: the
  `postinstall` (`node scripts/catalog-bake.ts`) and the catalog CLI load lane files with plain Node. The plan had no
  row for this; its risk table listed only tsc and tests.
- The plan changed twice: commits 2 to 4 as planned, then commit 6 (catalog-bake closure, 30 files) and commit 7
  (node-run fixed point, 53 more files). The plan file was not updated for 6 and 7; the PR body was.

## 3. Execution (timeline, UTC)

| time | event | class of any failure |
|---|---|---|
| 06:45 | audit and plan committed (`dff8042e`), draft PR #579 opened | |
| 06:45 | baseline batteries on the untouched base: 9 ok, `catalog-ship-server` fail (int step about 13 s > 10 s limit) | base defect |
| 06:48 | commit 2 (domain layer, 53 files), 3 (application and core, 32 files), 4 (server, 23 files), each with its batteries | |
| 06:50 | census: first version counted 125 unit tests; the census script filtered manifest globs and missed files | code (my script) |
| 06:51 | probe of `vitest list --json <files>` overwrote `batch-convert.test.ts` (`--json` takes an output path); the census diff (21 vs 18 tests) found it; restored from HEAD, no commit held it | process (flag probe without `--help`) |
| 06:52 | census corrected through the battery's own file lists (`unit_battery.plan`): 181 unit and 12 int tests, identical | |
| 06:52 | commit 5 (census). Gate run 0 started on the pre-merge head and was killed (base had moved to c0e748c8) | wasted run |
| 06:53 | base merged (`1f600e5d`), gate run 1 | |
| 06:55 | gate run 1 **FAIL at install**: postinstall `node scripts/catalog-bake.ts` could not resolve `@ou/catalog-hierarchy` | **code, caused by this PR**. The gate printed `class: env`. |
| 06:58 | commit 6: closure of catalog-bake restored to relative (30 files) | |
| 06:59 | gate run 2 **FAIL** in unit tests, lint and performance (catalog CLI and lint run plain node on the catalog domain) | the same class, wider |
| 07:04 | commit 7: fixed point over every node-run entrypoint (53 more files) | |
| 07:05 | gate run 3 **PASS** on `784ef886`, 274 s (ceiling 180 s: warning only, D-064 f) | |

Waits: gate runs 2 and 3 took 283 s and 275 s; the first gate run was killed after about 4 minutes of wasted time.

## 4. Gate

- Runs: 3 complete, 1 killed. Failures: run 1 install (node-run resolution), run 2 unit, lint and performance (the same
  class). Run 3 green.
- Known base defect hit: `catalog-ship-server` battery over its time limit on the base (int step about 13 s). Not
  changed (no loosening, no skipping). Its unit's owner is the catalog lane; a fix is a faster int step, out of this PR.
- Gate time: 274 s on this 4 vCPU cloud, above the 180 s ceiling (warning only).

## 5. Lessons

| problem | concrete change that prevents it | owner |
|---|---|---|
| node-run TypeScript cannot resolve `@ou/` | a resolve hook for node-run TS that reads the generated `paths`; `units check` flags an `@ou/` specifier in the node-run closure | tooling lane (apps/web/package.json scripts, scripts/lib/catalog-cli) and the units owner for the check |
| the gate called a code failure `env` | the classifier treats `ERR_MODULE_NOT_FOUND` for an `@ou/` specifier in a diff that touched imports as `code`; add a fixture | engine gate-report owner (scripts/lib/gate_classify.py) |
| the audit missed the runtime graph | the audit template gets a row "runtime entrypoints (node, postinstall, CLI) and their closure", checked with the same resolver | brief template owner (the coordinator, CO1 docs) |
| census script missed glob-based tests | census takes the battery's file lists (`unit_battery.plan`), never manifest globs | this lane (done in the PR's census) |
| a CLI probe overwrote a source file | probe CLI arity with `--help` before any run that writes; never pass a file list after an optional-value flag | session practice; the brief template's "safe commands" list |
| stale-base gate run | the gate is started only after `git merge origin/<base>` at the same head; the launcher checks the base before the run | gate launcher (engine-gate-run owner) |
| brief branch vs harness branch | the launcher writes the branch once, in the header, and the session uses it | launcher owner |
| base battery red (ship-server int step) | the owner of `catalog-ship-server` speeds the int step or splits it; the limit stays | catalog lane |
