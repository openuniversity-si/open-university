# GATE-ON-PUSH — audit

Stage 3 of the unit flow (D-077, Padrão v7, D-081). Read-only, cheap evidence: code at base `cf6e8b42`, the shared
store, the `train/lock` ref history over git (no REST), and three REST reads on 29/10 ~22:50Z. Causes only; the plan
weighs the fixes.

## Entradas
- [intake.md](intake.md): the real problem (a green verdict does not cause a merge; a loop re-reads every open PR on a
  shared user token) and the success numbers (p50 ≤ 60 s green to merged, ≤ 20 forge calls per merge, zero quota
  stalls).
- [research.md](research.md): the references (`merge_group`, bors, Zuul, SubmitQueue/TAP, webhooks and conditional
  requests) and the ladder (rung 1: the `pr.ready` producer wakes the train for that one PR; the loop becomes a
  safety-net sweep with conditional requests).

The audit asks its own questions: does the verdict already trigger anything, and if so why does nothing start; what
one train run costs, idle and per merge; where a run would execute; and what is on the merge path besides the trigger.

## Findings

1. **The verdict already has a trigger, and from a gate it never fires.** After `gate.passed`, `gate_report.ready_hook`
   emits `pr.ready` and calls `train_trigger.start` (`scripts/lib/gate_report.py:104-133`, start at `:129`). `start`
   reads `train.trigger_mode` and starts nothing unless it is `detached` (`scripts/lib/train_trigger.py:34-37`). The
   shared store has said `detached` since 2026-10-28T11:35:23Z (`scripts/config history train.trigger_mode`: "no train
   run has ever been logged"). But the gate runs the hook as `env OU_CONFIG_STORE=file … gate_report.py`
   (`scripts/gate-local:134`), and under that pin the switch reads the registry default:
   `OU_CONFIG_STORE=file scripts/config get train.trigger_mode` → `"emit_only"`, and `train_trigger.start()` under the
   pin raises `NotStarted` (run here). The module strips the pin from the *child's* environment
   (`train_trigger.py:8,41`), but it reads the switch under the pin first. Only the manual `scripts/pr-ready`
   (`scripts/lib/pr_ready.py:254-257`, no pin) honours the shared value.
2. **Even when it fires, it runs the train in the wrong place.** `start(root)` runs `scripts/train run` in the
   producer's container and checkout (`gate_report.py:119` `root = pr_ready.ROOT`, the tool checkout of the lane), and
   `Tier2Gate` defaults to that checkout (`scripts/lib/train_git.py:161-162`). Two written rules disagree:
   [EVENTS.md](../../process/EVENTS.md) line 42 (`pr.ready` "tries the train lock, queues the PR, starts a batch") and
   Transport v0 ("the producer invokes the consumer", EVENTS.md "Scale"), against
   train.md "Only in the train-role cloud session" (Daniel 2026-10-27 18:08) and P-46 (the
   pinned gate judges). In verdict mode a lane-started run would execute admission code from the PR's own checkout.
3. **A run has no PR.** `scripts/train run` takes only `--owner` (`scripts/lib/train.py:476-477`) and drains the whole
   queue (`train.py:317-337`). One PR's admission already exists below the queue: `queue_entry(log, head)`
   (`scripts/lib/train_queue.py:34-51`) and `Train.admit(port, entry)` (`scripts/lib/train_verdict.py:144-164`) need
   only that PR's log, its head and the tip.
4. **Every queue build in production is the full replay.** The incremental index needs `adapter.events_since`
   (`train_queue.py:116-126`); only the test fakes have it (`scripts/tests/test_train.py:64`), and the queue test
   asserts the GitHub adapter falls back (`scripts/tests/train/test_queue.py:103`). Measured 29/10 ~22:50Z: 67 open
   PRs, 67 comment pages (largest 43 comments) → `1 + 67 + 67` = **135 REST reads per build** (one
   `issues?state=open` read).
5. **An idle run builds the queue two or three times.** `drain` builds it (`train.py:322`); with `verdict`/`requeue`
   an empty queue runs `bootstrap` → `open_candidates`, another full pass over every open PR
   (`train_verdict.py:171-195`); after releasing the lock, `LockedRole.run` calls `pending()` → a third build
   (`scripts/lib/engine_role.py:162`, `train.py:308-309`). Today's fallback is `tier2` (below), so bootstrap is skipped:
   ≈ 270 reads per idle run, ≈ 405 under `requeue`. On top of that, a new process reads the config store window: one
   issue read plus the newest 20 comment pages of #548 (`scripts/lib/forge_github.py:108-119`), cached 60 s per
   checkout (`scripts/lib/config.py:362`).
6. **Every merge reads the whole repository channel twice, and that read now fails.** After the merge call
   (`train_verdict.py:346`) the train reads #548 in full for `quarantine.open` (`train_verdict.py:357`,
   `scripts/lib/quarantine.py:101-102`) and for `prs_since_release` (`train_verdict.py:361`; the batch path at
   `train.py:419`). `read` pages from page 1 and raises past `forge-events.github_max_pages` = 20
   (`forge_github.py:98-106`). #548 has **2,018 comments** (21 pages, measured): the run raises after the PR has
   merged, before `integration.advanced`. This is the #808 failure the intake quotes, now permanent. When it worked, it
   cost 2 × 20 reads per merge.
7. **No read is conditional.** `github_api._request` sends `Accept`, `User-Agent`, `Authorization` and
   `Content-Type` only (`scripts/lib/github_api.py:122-131`): no `ETag`/`If-None-Match`, so re-reading an unchanged
   page counts against the primary limit, while GitHub does not count a `304`
   ([research.md](research.md#quem-já-resolveu)).
8. **Quota is budgeted for writes only, and its exhaustion leaves no event.** `forge_rate` limits writes and records
   blocks in a per-session state file (`scripts/lib/forge_rate.py:1-16`; `forge_rate.py status` here:
   `refused 1`). There is no rate-limit event type in `contracts/events/` (listed), so the two exhaustions of 29/10
   exist only in Daniel's report.
9. **Who ran the train on 29/10: several sessions, by hand-started runs.** The `train/lock` ref
   (`git log origin/train/lock`, git only) has 106 commits on 29/10: **18 holds by 6 distinct owners** (`train@cse_…`)
   between 16:28Z and 22:46Z, each 1–40 min, gaps of 1–30 min. Lease = `train.tier2_timeout_s` 1800 +
   `train.lock_lease_margin_s` 300 = 35 min: a holder that dies blocks every other run that long. #808: `pr.ready`
   21:19:32Z → a hold from 21:20:50Z (78 s) ended at 21:22:30Z without a merge; it merged under the 21:31:16Z hold
   (`merged_at` 21:36:05Z).
10. **A zero-REST channel to the train already exists.** The lock moves over the git protocol only
    (`scripts/lib/forge_git_ref.py`; train.md):
    create and fast-forward of `refs/heads/*` pass the proxy and cost no REST quota. `git ls-remote` of a ref is the
    same channel, read side.
11. **On the merge path, the verdict is refused today regardless of the trigger.** `train.verdict_fallback` is
    `tier2` in the shared store since 20:48:02Z because "the gate attests the toolchain without the shared store's
    overrides, the train with them: a strict verdict never matches" (`scripts/config history
    train.verdict_fallback`). Every PR then waits for a full tier-2 run (all 5 merges of 29/10, intake). `train.admit_mode`
    is `verdict` (19:12:38Z), `train.shard_admit` is `shadow`.

## Causas raiz

### R1. A switch of the train is read inside the gate's pinned process tree
Cadeia de porquês:
1. Por que nenhum `pr.ready` de um gate iniciou o trem? `train_trigger.start` read `emit_only` (finding 1).
2. Por que `emit_only`, se o store compartilhado diz `detached`? The hook runs under `OU_CONFIG_STORE=file`
   (`scripts/gate-local:134`), which reads the registry default and the checkout's local log.
3. Por que o hook herda o pin? The pin keeps the verdict hermetic and reproducible (`scripts/run:46`,
   `scripts/lib/prepush.py:25`), and the post-verdict hook runs in the gate's own process tree.
4. Por que nada separou os dois? No rule or test tells the verdict's inputs (pinned) from the post-verdict effects
   (shared switches, D-069 item 5); the trigger's tests inject the mode, never the store it is read from.
Classe: regra faltando
Evidência: `scripts/gate-local:134`, `scripts/lib/train_trigger.py:8,34-41`, `scripts/config history train.trigger_mode`,
`OU_CONFIG_STORE=file scripts/config get train.trigger_mode`.

### R2. The only transport makes the producer of the event run its consumer
Cadeia de porquês:
1. Por que um veredito verde não acorda o trem? With `emit_only` nothing wakes; with `detached` the train runs in the
   lane's container on the lane's code (findings 1, 2).
2. Por que só existem essas duas opções? Transport v0 is "the producer invokes the consumer" (EVENTS.md "Scale"):
   events are forge comments, and the only way a consumer learns of one is to read it.
3. Por que isso colide com a regra do trem? The 27/10 rule (only the train-role session runs the train, P-46) changed
   who the consumer is but not the transport: there is no channel for a producer to wake a long-lived consumer in
   another container.
4. Por que então a sessão train-role relê tudo? Without a wake channel, re-reading the world is the only way to find a
   `pr.ready`; `detached` (28/10) went back to the design the 27/10 rule had forbidden, and is dead from the gate (R1).
Classe: arquitetura/desenho
Evidência: EVENTS.md line 42 and "Scale"; train.md "Only in the train-role cloud session"; findings 2, 9, 10.

### R3. The train has no unit of work smaller than the whole queue
Cadeia de porquês:
1. Por que uma rodada sem nada na fila custa ~270–405 leituras? It rebuilds the queue two or three times, each a full
   replay (findings 4, 5).
2. Por que replay completo? The incremental index needs `events_since`, which the GitHub adapter lacks, and a single
   process across builds, while every run is a new process (finding 4).
3. Por que cada rodada relê tudo, mesmo quando um evento nomeia o PR? `scripts/train run` takes no PR (finding 3):
   D-069 item 4 ("replaying the logs rebuilds the queue") was built as the only path, not as the recovery path.
4. Por que o merge também relê tudo? Derived counts (`prs_since_release`, the quarantine state) are recomputed from the
   whole repository channel on every merge, with no bound that holds as the channel grows (finding 6).
Classe: mecanismo faltando
Evidência: `scripts/lib/train.py:308-337,476-477`, `scripts/lib/train_queue.py:116-126`,
`scripts/lib/train_verdict.py:171-195,357-361`, `scripts/lib/forge_github.py:98-106`, `scripts/tests/train/test_queue.py:103`.

### R4. A read costs quota even when nothing changed, and nobody sees the budget run out
Cadeia de porquês:
1. Por que a cota acabou duas vezes em 29/10? Runs of 135+ reads per build, in several processes and sessions, on one
   user token (findings 4, 5, 9).
2. Por que releituras idênticas contam? No request is conditional (finding 7).
3. Por que ninguém viu chegando? The budget covers writes only and its exhaustion is not an event (finding 8).
4. Por que o trem divide o orçamento com gates e sessões? One identity serves every role; "one identity per role" is in
   the 10x column of EVENTS.md "Scale", not in today's.
Classe: mecanismo faltando
Evidência: `scripts/lib/github_api.py:122-131`, `scripts/lib/forge_rate.py:1-16`, `contracts/events/`, EVENTS.md "Scale".

## Distância do estado da arte
Against research.md's reference (`merge_group`: the green verdict *is* the enqueue and wakes the consumer; Zuul and
SubmitQueue: a service that receives events, keeps the queue, merges under its own identity, sweeps for lost events
with `304`s):

- **Have:** an idempotent `pr.ready` with a natural key (repo, pr, sha); a hook at the right moment
  (`gate_report.ready_hook`); one PR's admission (`queue_entry`, `Train.admit`); a single-writer lock and a
  zero-REST git channel (`forge_git_ref`); a write budget (`forge_rate`); the gate counts its own calls
  (`cost.rest_calls` on `gate.passed` v4).
- **Missing:** a wake that reaches the train-role session (R2); a run scoped to one PR (R3); bounded post-merge reads
  (finding 6); conditional reads and a rate-limit event (R4); a train identity of its own; a service host.
- **Rung:** below rung 1. The trigger of rung 1 exists in code but is dead from the gate (R1) and, when alive, lands in
  the wrong container (R2). Rungs 2–4 have nothing yet, except `train.shard_admit` in `shadow` (rung 4's speculation at
  unit granularity).

## Base defects expected
- **The repository channel read raises past 20 pages** (finding 6): every merge since #548 passed 2,000 comments
  raises after the merge call. Owner: the train-role session and the engine-train lane (#689); rung 1 cannot meet
  "≤ 20 calls per merge" with it, so the plan addresses the read.
- **Strict verdicts never match on toolchain** (finding 11): `train.verdict_fallback=tier2` until the toolchain
  identity is a function of committed inputs. Owner: #809 (D-080, per AUDIT-ROOT-CAUSE's plan R4). Until then a woken
  run still takes a tier-2 run, and "seconds" is not reachable by this unit alone.
- **Several sessions hold the train lock** (finding 9). Owner: the coordinator (train.md); this unit does not change who
  is the train-role session.
- `DECISIONS.md` textual conflicts after each merge: DOCS-API (#811), not this unit.
