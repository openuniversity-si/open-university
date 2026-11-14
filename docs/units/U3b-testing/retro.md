# U3b testing lane: retro

Whole unit, from the launch brief to the accepted gate. Facts with evidence; times are the sandbox clock (UTC, 2026-10-27).

## 1. Brief quality

- **Branch conflict.** The brief names `mod/u3b-testing-addresses` as the work branch; the harness designates
  `claude/u3b-testing-addresses-8ea1lc`. The designated branch was used (it equalled the base head, so no old work was
  reused). Lesson: the brief and the harness must name one branch.
- **Premise status.** The brief lists `P-03, P-13` as premises without their status. P-13 is `inferred` (medium) in the
  register; the audit had to read the register to know that.
- **Instances line.** The template asks for `Instances: <main new file>`; a mechanical lane PR creates no file. The
  plan file was named, which satisfies the line but is not what the template means. Lesson: the template should allow
  `Instances: none (mechanical)`.
- **Ticks.** The brief says to tick the plan by hand with PATCH; AGENTS.md says ticks are derived from `Plan: N`
  trailers (`scripts/plan-tick`, D-065 V4). The body was written with unticked items and not patched afterwards; the
  derived tick is checked after the merge. Lesson: one rule in the brief, the AGENTS.md one.
- **Gate ceiling.** The brief says 180 s is the gate ceiling (D-064 f) and the one gate runs in a 4 vCPU cloud; the
  first run took 960 s. The ceiling is a warning, but no brief says what to do when every stage is slow on this host.

## 2. Audit and plan

- **Held:** the rewrite resolver (`unit_map.Code.resolve_import` with the tsconfig `paths`) and the owner lookup
  (`units.unit_of`) gave one answer per lane specifier: 271 rewritten, 103 same-unit kept, 6 gaps in 4 causes, no
  unresolved specifier. Nothing in the audit had to be redone.
- **Broke:** the audit took the tsconfig `paths` as the truth for `@tower/catalog`. The runtime truth for `vi.mock` is
  the vitest alias (`vitest.config.ts`), which names `src/catalog/testing/fake.ts`. The plan's commit 3 needed one
  exception (the four `vi.mock` specifiers) that plan.md does not record. The commit message and PR body record it.
- **Premises:** P-03 held (the address form works for every lane specifier that has an address); P-13 was not tested
  (no other lane touched these files).
- **Base defects known at audit:** the `testing-e2e` and `testing-support` batteries were not measured before the audit
  (the measurements came after; see 4).

## 3. Execution (failures, root cause, rework, waits)

| # | When | Failure | Root-cause class | Rework |
|---|---|---|---|---|
| 1 | 06:46–06:47 | Baseline `unit-battery testing-e2e` red: 31 s against a 10 s limit (types step, cold). | Battery budget measured cold; the types step has no warm/cold definition. | None. Re-measured after the change: 9.6 s warm. |
| 2 | 06:46–06:51 | Baseline `unit-battery testing-support` red: int tests 164 s (limit 10 s) and perf-int `lists 10,000 courses in under a second` (2549 ms). | DB-backed int tests cannot fit a 10 s tier-1 budget; the perf test is a known timing-sensitive test. | None; both left as they are. |
| 3 | 06:56 | After the test rewrite, 4 int files failed (5 tests): `No "readActiveRelease" export is defined on the "@ou/release-server/server/read.ts" mock`. | Second source of truth for aliases: `vitest.config.ts` aliases `@tower/catalog` to `catalog/testing/fake.ts`, the tsconfig path names `release/server/read.ts`. The `vi.mock` was dead at base (targeted fake.ts) and became live when rewritten to the tsconfig's target. | Re-did the rewrite with the four `vi.mock` specifiers naming the module vitest resolved; rebattery green (int 35 files ok). |
| 4 | 06:57 | The base moved during the session (#597 merged); the first gate was started on the pre-merge head. | Base moved without a notice to the lane. | Gate killed at once (the first kill also killed my own shell, exit 144: a `pkill -f` pattern matched it). Base merged (merge commit, 81547bd0), gate restarted. |

Time and quota: most of the wall time was in the gate (960 s) and the two baseline batteries (about 3.5 min in total). The
rewrite itself is a few seconds.

## 4. Gate

- Runs: 1 (on 81547bd0, after the base merge). Result: PASS, `gate.passed ced420f5287b` on PR #586, recorded as
  `.gate/records/81547bd0….dev.pass`. No gate-db (diff touches no database path; `DB path classification: db=0`).
- Wall time: 960 s against the 180 s ceiling (warning, D-064 f). Stage times: integration 159 s, unit 122 s,
  structure check 73 s, performance 58 s, e2e smoke 58 s, typecheck 20 s, the rest under 10 s each.
- Known defects hit: none in the gate. The perf test `lists 10,000 courses in under a second` failed in the unit
  battery baseline (2549 ms) and passed in the gate (its own stage).
- Census: vitest list before and after, all projects, 1540 tests in 318 files, identical; Playwright list 941 tests in 31
  files, identical.

## 5. Lessons (each with an owner)

1. **Aliases have two sources** (tsconfig `paths` and `vitest.config.ts` `alias`). Class fix: a check that every alias key
   resolves to the same file in both, or one of them is generated from the other. Owner: units (U3a addresses; the
   tsconfig map is generated, the vitest map is not). Proposed gate check: in `scripts/units check`, compare each `@tower/*`
   and `@ou/*` key's target with the vitest alias for the same key.
2. **Tier-1 battery budget for DB-backed tests.** The unit battery times the int tests of a unit; they never fit 10 s.
   Class fix: tier 1 runs unit and types only for a unit, and int tests move to tier 2 (plan v3 §9.3 V5/V7) or
   the battery reports them separately. Owner: M6 (battery role) with U3a. The limit is not loosened here.
3. **Cold and warm measurements.** The types step took 31 s cold and 9.6 s warm. The battery must say which it measured
   (or run once to warm). Owner: U3a (`scripts/unit-battery`).
4. **Vitest mock targets.** A `vi.mock` target must be the module vitest resolves, not the tsconfig path. Class fix:
   the rewrite tool resolves each `vi.mock` through vitest's resolver (done in this PR's tool, not committed) and the
   alias check of lesson 1 covers it. Owner: testing lane.
5. **Base movement.** The lane started a gate on a base that had moved. Class fix: the gate's first stage fails when the
   head is not descended from the current base of its PR, or the coordinator re-bases the lane on every launch. Owner:
   CO1 (coordinator) and the train (M3).
6. **Gate ceiling on this host.** 960 s on the 4 vCPU cloud against 180 s. Owner: O1 (SLOs, D-064 f); not changed here.
7. **Plan and execution.** A deviation from the plan's commit 3 was not written into plan.md. Lesson for the brief
   template: any exception to the plan's rule is a commit to plan.md before the commit that uses it. Owner: the
   coordinator's brief template (CO1).
