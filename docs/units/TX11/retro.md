# TX11 retro: flake attribution on the PR's own head

PR #743, branch `mod/tx-flake`, base `891b835ae`, lane engine-lane.

## Brief quality

- The evidence held on the base: every cited file and line was where the brief said (first STATUS comment).
- Clear on the boundary (gate_test_cache, gate-runner and defect_detect stay untouched, called only through their public
  API) and on the two fixtures. That made the design quick: the re-run is `gate_test_cache.run` with a throwaway store.
- One gap: "ONE call site in gate_adjudicate.py". The quarantine events need the forge port, which only
  `defect_events` holds, so the seam is two one-line calls in that one file (`adjudicate` and `defect_events`).
  Decided and reported in the PR rather than adding a port to `adjudicate` or editing gate_report (not owned).
- "a defect record through scripts/defects record": the gate only publishes (`defect.detected`) and
  `scripts/defects sync` calls `defects.record`; fixture 2 runs the CLI itself on a throwaway registry to prove the record.
- The harness proposed another branch name; the brief's `mod/tx-flake` was used (one branch, one PR).

## Premises

- P-46 held: the pinned gate on the base tip gives the verdict; this PR's gate code ran as code under test.
- TX11-P1 (CRITICAL, one pass at the same head after one failure is not the change's fault): kept narrow by the
  touched-test rule, one re-run, tier-1 only, the `gate-flake.enabled` switch, and the record/quarantine trail.

## Failures and root-cause class

| Failure | Class | Fix |
|---|---|---|
| Literal census: `parents[2]`, `'a' * 40`, a dated `datetime`, a PR number, `[:2]` in new files | code (mine) | `parent.parent.parent`, hashed shas, a clock derived from the registry window, `PR = 1`, unpacking |
| Hermetic rule `wall_clock` on `datetime.now()` in a unit test | code (mine) | a fixed clock built from the registry window |
| `unit_check`: engine-gate-report imports engine-quarantine without declaring it | code (mine) | `"engine-quarantine": "^1"` in requires |
| `scripts/generate --check`: the generated registry type was missing | code (mine) | `scripts/generate python-types` |
| `test.flaked` needs `log` (contract) in a test helper | code (mine) | the helper passes one |

## Gate runs

| Head | Gate | Result | Time |
|---|---|---|---|
| `d0bc8f12` (items 1-6) | pinned gate (base-tip tooling), `scripts/gate-dev --pr 743` | PASSED, gate.passed `076a3d3c9427`; pr.ready waited for item 7 | 165 s (ceiling 180 s) |
| `d0bc8f12` | advisory run of the head tooling (report-only) | PASSED | 138 s |
| RETRO head (item 7) | pinned gate | see the MERGE-READY comment | - |

Targeted tests while working: gate-flake, gate-classify, defect-detect, gate-report-skips, gate-status, quarantine,
defects: all PASS. No red gate run.

## Lessons

- A new registry file always needs `scripts/generate python-types` in the same commit; the fast checks name it, so run
  `scripts/generate --check` before the first commit that adds a registry file. Owner: engine-lane (prepush, TX01).
- New unit tests must build shas and times without literals or the wall clock: a small shared helper
  (`hermetic` fake sha and fixed clock) would save every unit the same three edits. Owner: engine-lane.
- Next for flakes: a re-run API for vitest and browser tests (the vitest `Test timed out` case of tonight) is the
  follow-up that lets `gate-flake.stages` grow; until then those stages stay the PR's.
