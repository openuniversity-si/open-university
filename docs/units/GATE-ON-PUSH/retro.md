# GATE-ON-PUSH retro: the green verdict wakes the train

Stage 6 of the unit flow (D-077). Covers the execution of [plan.md](plan.md): plan commits 1–3 in #812 and 4–7 plus a
stopgap in #813. Written before the merge: the numbers of [research.md](research.md#success-measured) can only be read
after the coordinator switches `train.trigger_mode` to `wake` and the train-role session runs `scripts/train serve`;
section 4 says how to read them.

## 1. Delivered against the plan

| Plan commit | Where | Delivered | Deviation |
|---|---|---|---|
| 1 Shared switches after the verdict (R1) | #812 item 6 | `config.shared`, `train_trigger` reads `train.trigger_mode` from the shared store | none |
| 2 One PR per run (R3) | #812 item 8 | `scripts/train run --pr <n>` | tests in the existing train files, not new ones |
| 3 Bounded post-merge reads (R3) | #812 item 7 | `green_runs`, `quarantine.open`, `prs_since_release` read the newest window | also the live blocker (#548 past 20 pages) |
| 4 The wake (R2) | #813 item 1 | `wake` mode, `train.wake_ref`, `GitRefs.append`, `train_trigger.trigger(root, event)` | `train.wake_attempts` is a registry key, not a hard-coded retry |
| 5 `scripts/train serve` (R2) | #813 item 2 | `train_serve.py`, `GitRefs.tip`/`log`, P-55 | `premises.ForgePort.publish` read #548 whole; fixed in the same commit to register P-55 |
| 6 Conditional reads (R4) | #813 item 4 | `ETagCache`, `If-None-Match`, 304 counted apart | one file per URL with an atomic rename instead of one flock-locked file (bodies of 100-comment pages are large) |
| 7 Budget on the log (R4) | #813 item 5 | `forge.rate.limited` v1; the train's REST count | see below |
| (stopgap) | #813 item 3 | `forge-events.github_max_pages` 20 → 200 (Daniel, 30/10 22:06 BRT) | a loosening: needed D-072's blocking evaluation ([incident](../../process/incidents/2026-10-30-repository-channel-page-cap.md)) |

Commit 7 changed shape twice:
- `forge.rate.limited` is not emitted at the refusal: during the block every call waits, the publish included. The
  refusal is kept in the session's rate state and published by the next successful production call after the block.
- The train's REST count is not on `engine.step.measured`: event contracts are hash-locked, so a new field is a v2 of a
  contract every reader folds. It is a `budget.measured` against the new budget `train.rest_calls_per_run_max` (20),
  and the count reaches the train through the port (`ForgeEvents.calls()`), since the train may not call the vendor
  client (D-069 item 7).

## 2. What the gate taught

- The repository channel (#548) hit the page cap in more places than the audit listed: the gate's own verdict hook
  (`slo.collect`), `scripts/premises`, and the modules Daniel listed. The stopgap reads them all again; the class fix,
  one shared windowed read, is a separate unit.
- A plan checklist with undelivered items keeps `pr metadata` red until the last commit. #813's body lists what the
  commits delivered so far, with the rest under "Next", so each pushed head can be judged.
- Unit boundaries shaped commit 7 three times: the port may not import the vendor client, the client may not import
  the port, and the train may not call the client. The announcer is registered by the GitHub adapter
  (`forge_github`), which owns both sides.
- The literal census refuses any new number literal over the base's count: tests name their values once (or read the
  registry) instead of repeating them.

## 3. Open risk found during execution

The shared store says `train.trigger_mode` = `detached` (since 28/10, audit finding 1). With R1, a gate pinned to
tooling that contains it reads that switch and, on a pass that emits `pr.ready`, starts `scripts/train run` from the
gate's pin directory in the lane's container: the producer-runs-consumer path R2 exists to remove. #813's own gate is
pinned to #812's head, so its pass would do exactly that. The coordinator's switch to `emit_only` (now) or `wake`
(after the merge, with `serve` running) removes it; until then a lane should not record a passing gate on a stack
that contains R1.

## 4. How the success numbers are read (after the switch)

From forge events, over one working day with `serve` running:
- Green verdict to merge: `pr.merged.occurred_at − gate.passed.occurred_at` per head (`pr.ready.evidence`).
- REST calls per merge: `budget.measured` with metric `train.rest_calls_per_run_max`, per `scripts/train run --pr`.
- Quota stalls: count of `forge.rate.limited`.
- Who merged: runs started by a wake (`train serve: wake #<n>` lines) against sweeps.

## 5. Lessons

- (a) A growing append-only log needs one shared reader-side window before it outgrows any cap. Owner: the pending
  repository-channel-window unit.
- (b) A switch that moves work across process trees (R1) is only safe once the work's destination exists; land the
  consumer (`serve`) and the switch value together. Owner: the coordinator.
- (c) A new event field on a locked contract costs a version; reach for an existing contract (`budget.measured`)
  first. Owner: engine-events.
