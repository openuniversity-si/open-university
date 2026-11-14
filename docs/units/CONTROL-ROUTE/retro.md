# CONTROL-ROUTE — retro

Unit: the control plane is the runner's only route; the git transport is deleted (D-290). PR #1083, branch
`mod/control-route`, base `mod/roadmap-integration` @ `fab6e204d`. Launch 11:37 BRT (first commit 11:38).

## 1. Brief quality
- **Wrong about the environment, twice.** The brief says this cloud environment "HAS $TOWER_EVENTS_TOKEN and reaches
  the control plane". Neither holds: `env` has no `TOWER_EVENTS_TOKEN` (every diary note, the gate's verdict and
  `scripts/pr-ready` fail with `no events token`), and the proxy answers 403 to `forge-webhook.the-owner.workers.dev`
  (policy denial, `__agentproxy/status`). Both are in [status.md](status.md) B1-B3. The brief named the fallback
  correctly (write status.md, keep working), so no time was lost waiting.
- **Under-scoped by one consequence.** "Delete GitTransport" also deletes the only reader of `service.control_ref`, so
  `scripts/service requeue|cancel` would have written to a ref no one reads, and `--dry-run` would have started leasing
  real jobs. The brief's file list did not name `scripts/lib/service.py`, the registry, the operation declarations or
  `docs/operations/services.md`; all were own dependencies (OWN DEPENDENCIES ARE IN SCOPE) and were changed.
- **Missing: the activation is a production-route change.** After merge a runner without `OU_RUNNER_TOKEN`, or with the
  shared store still holding `service.transport git`, stops with a named error instead of merging through git. The brief
  says provisioning is a separate operator step but not that the train stops until it happens. Recorded as the CRITICAL
  premise in plan.md.
- Accurate: the line reference (`service_runner.py:461`), the four PRs (all `closed merged=false` on 01/11), the cause.

## 2. Audit and plan
- Held: F1-F8 as written. The control plane already turns `pr.ready` from the journal into a train job
  (`core.js:85-96`), so deleting the runner's `train/wake` read loses no wake.
- Found beyond the brief: two registry keys left with no reader (`service.gate_drafts`, `service.control_ref`), which
  D-289 removes in the same change; the runner was declared as a consumer of the forge's `change` in three operation
  files and `PORTS.md`.
- Plan change: none in structure. R3 (admin channel) was added by the audit, not the brief.

## 3. Execution (timeline, BRT)
| Time | Commit | What |
|---|---|---|
| 11:38 | d7f797f5 | step 0: audit skeleton, draft PR #1083 |
| 11:39-11:41 | 92588947, 565ca6e4 | status.md B1 (no events token), B2 (proxy refuses the Worker) |
| 11:42-11:46 | e2012dca, 53c6dc37, 8f772eb5 | intake, research, audit, plan + D-290 |
| 11:46-11:51 | ebb21b22 | runner: control only, RouteError, service.py, registry, docs (meter delegated to a forked sub-agent in parallel) |
| 11:52 | 5b23c44f | meter: control queue minus closed PRs |
| 11:54 | 334298e9 | route test stops spelling removed keys (schema-compat) |
| 11:57 | e49f55bd | D-290 as a record; runner leaves the operation declarations |

Failures, each with its class:
- **Commit refused by the structure check: a `|` inside the D-290 table row** (`requeue|cancel` split a column). Class:
  regra faltando at authoring time — the row is meant to be rendered from a record (`scripts/decision-record`), and I
  wrote it by hand. A second test (`decision-handwritten`) later refused the hand row itself. Same cause, fixed once by
  writing `docs/domain/decisions/D-290.md` and rendering the row with `decision_table.row`.
- **`git commit --amend` landed on the already-pushed audit commit** because the refused commit had not been created.
  Caught before any push (the push guard refused the non-fast-forward and opened `I-373f635f`); fixed with
  `git reset --soft origin/<branch>` and a fresh commit, no force push. Class: bug local (my sequence), but the guard
  worked as designed.
- **schema-compat: a negative test spelled the removed keys** and so counted as their reader. Class: regra faltando in
  my test design; the absence is the registry's to prove, not a string search in a test.
- **operation-relations / operation-config: stale declarations of the runner as a `change` consumer.** Class:
  mecanismo faltando — the declarations are hand-kept, so removing a call site requires editing three JSON files and a
  table by hand.
- Waits: none on people. Time went mostly to reading the runner, its tests and the Worker's routes (~8 min) and to the
  registry/declaration fallout (~6 min).

## 4. Gate
- `scripts/gate-dev --pr 1083` on `e49f55bd`: bypass D-151, 8/8 stages PASS without running, then
  `FAIL gate evidence: … no events token (class env)` → GATE: FAILED (status.md B3).
- Real gate, `GATE_BYPASS=0 scripts/gate-quiet` (11:59-12:10 BRT, 658 s): 7 stages PASS, `shellcheck` FAIL (env: not
  installed), script tests 132 PASS / 13 FAIL. All 13, rerun side by side on the base `fab6e204d` and on the head, fail the
  same way on both: base defects, not this change. Cost: 11 min of gate plus ~6 min of comparison, which a recorded base
  battery (`gate-noite`) would have answered in one read.
- The push-guard tests of that run wrote two incident files (`claude/z`, `claude/f` refusals) into this checkout's
  `docs/operations/incidents/`: a test that leaks into the real tree (owner: engine-lane, push-guard).
- Base defects hit (reproduced identically on `fab6e204d` in a throwaway worktree): `plan-tick.test.sh`,
  `pr-creation-path.test.sh`, `train-role.test.sh`, `defect-lifecycle.test.sh`, `forge-rate.test.sh` (the last needs
  the events token).

## 5. Lessons (change → owner)
- The environment line of a brief should be checked by the launcher, not asserted: `scripts/cloud/preflight` should
  report `TOWER_EVENTS_TOKEN` and the control plane's `/healthz` through the proxy, and the launcher refuse to claim
  them otherwise. Owner: A Torre (launcher/brief template).
- A decision is a record: the brief template and AGENTS.md should name `scripts/decision-record` (or, when a PR already
  cites the number, writing the record file) instead of "a new decision gets an entry". Owner: A Torre (AGENTS.md).
- Operation declarations (`operation_relations.json`, `operation_demands.json`, `operation_config_relations.json`,
  `PORTS.md` table) should be regenerated by `scripts/generate` from the measured call sites, with only the
  classification hand-kept. Owner: engine-lane (FORGE-PORT).
- A route removal checklist: every reader of the removed route's refs/keys (`rg` of the registry keys it reads) is part
  of the same change. Owner: A Torre (brief template).

## 6. The step that should have descended
| Work done by an AI today, identical tomorrow | Should descend to | Cost this time | Owner |
|---|---|---|---|
| Updating 4 operation declarations by hand after deleting one call site | deterministic script (`scripts/generate operations`) | ~4 min, 3 test runs | engine-lane |
| Rendering a decision row by hand, then converting it to a record | deterministic script (`scripts/decision-record --number` for a PR's own claim) | ~4 min, 2 refused commits | A Torre |
| Finding which registry keys lose their last reader | rule in the engine (schema-compat already measures absence; `generate` could drop the key file and say so) | ~3 min | engine-lane |
| Proving the four tests fail on the base too (worktree + rerun) | rule in the engine (the gate already classifies base status with `--why`; prepush could print "fails on base" from the base's last battery) | ~3 min | engine-lane |
| Deciding "environment broken → status.md, keep working" | already a rule (the brief); it should be a preflight refusal at launch instead | 0 decision time, 3 status entries | A Torre |

## 7. Continuation (CONTROL-ROUTE-2, 02/11 ~12:26–12:50 BRT)
- Brief: it said #1083 was still a draft; it was already out of draft since B4 (REST route). Harmless, but a
  continuation brief should be generated from the PR's live state, not from the dead session's last plan. Owner: A Torre.
- Environment: `$TOWER_EVENTS_TOKEN` present, `forge-webhook` reachable (status.md "environment"). The five diary notes
  session 1 parked in status.md were replayed, exit 0 each.
- Gate: 2 runs on 081e5ad6e. Run 1 failed recording the verdict (`control plane unreachable: The read operation timed
  out`, 10 s budget) although `GET /status` answered in ~1 s; run 2 passed and emitted `pr.ready` itself. Then one
  run on the final head after the fix below.
- Defect of this branch, found only now: e49f55bdc dropped `service_runner.py` from `operation_demands.json` but
  `test_forge_events.py` kept it in `EXPECTED_CONSUMERS`. Root cause: session 1 compared `forge-events.test.sh` exit codes
  base vs head, and both exit 1 because of the base's `test_operation_integration.py` import error, so a second,
  branch-made failure in the same suite was hidden behind the first. Lesson: compare base vs head per test case
  (`FAIL:`/`ERROR:` names), never per suite exit code. Descent: rule in the engine — `gate-dev --why` / prepush
  print the failing test names that the base does not fail (engine-lane). Cost here: ~6 min, 1 extra worktree.
- Also hit: my own edit to the expected list trimmed a trailing space and fused two names (`traintrain_queue`);
  caught by the same test on the next run. Lesson: edit word lists as data, not with string splicing.

| Work done by an AI today, identical tomorrow | Should descend to | Cost this time | Owner |
|---|---|---|---|
| Replaying parked diary notes from status.md after the environment is fixed | deterministic script (`scripts/plan note --replay status.md`) | ~2 min | A Torre |
| Per-test-case base/head comparison by hand in a worktree | rule in the engine (`gate-dev --why` names cases new on the head) | ~6 min | engine-lane |
| Retrying a gate whose only failure is a timeout writing the verdict | rule in the engine (`forge_events` retries the verdict write once before classing env) | ~1 min, one rerun | engine-lane |
