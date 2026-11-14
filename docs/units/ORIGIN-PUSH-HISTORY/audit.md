# ORIGIN-PUSH-HISTORY — audit

## Entradas
Read: the brief; `docs/units/ORIGIN-PUSH-HISTORY/intake.md` and `research.md`; `scripts/lib/forge_origin.py`, `forge_origin_client.py`, `forge_control.py`, `forge_github.py` (pushes, force_pushes); `scripts/lib/operation_demands.json`; `scripts/lib/commit_check.py` (push_errors, force_push_errors); `scripts/lib/stall_report.py`; `services/control-plane/src/core.js` (originOf, EventLog, originEnvelope); `contracts/events/pr.pushed.v1.json`; `scripts/tests/forge_events/test_forge_contract.py` (GitHubContract and OriginContract); `services/control-plane/test/origin.test.mjs`. No suite was run.

## Findings at base 018ecf6b1. Evidence is file:line on that base. No suite was run (per the brief: cheap evidence only).

## Brief facts, checked

| # | Fact | Status | Evidence |
|---|---|---|---|
| 1 | Origin API has no push-history route | carried, not re-verified | the repo holds no OpenAPI file (`git ls-files` finds none); no code path in the repo calls such a route |
| 2 | `repository.pushed` carries `refUpdates[]` {ref, before, after, created, deleted, forced}, plus `pushedAt` | confirmed by the repo's own fixture | `services/control-plane/test/origin.test.mjs:158-159` |
| 3 | `pull_request.head_ref.pushed` carries the new head sha only | confirmed | `services/control-plane/src/core.js:341-349`: the handler journals `pr.pushed` from `head.sha` and nothing else |
| 4 | The control plane keeps two ref updates, drops the rest | confirmed | `core.js:364-375`: base ref queues `sweep`, wake ref queues `train`; the loop `continue`s on deleted; every other ref is dropped without a journal write |

## Mechanism facts (each one tested against the code, not the brief)

- **M1. The adapter refuses by omission and by hand.** `scripts/lib/forge_origin.py:69-71` raises on `pushes` in `__getattr__`. `forge_origin.py:89` is a comment saying there is no `force_pushes`. `scripts/lib/operation_demands.json` has `pushes` and `force_pushes` as consumers of origin (commit_check, stall_report) but no origin proof for either. The GitHub proofs point at `test_push_history_preserves_edges_order_and_branch` and `test_force_push_history_preserves_evidence`.
- **M2. The journal writes no ref record.** `originOf` (`core.js:320-377`) journals only `pr.*` envelopes for a `pull_request.*` delivery and only the sweep/train jobs for `repository.pushed`. Nothing is appended to the log for a ref move. The read side has therefore nothing to read: a missing record is indistinguishable from a branch nobody pushed.
- **M3. A windowed read cannot prove completeness.** `ControlAdapter.recent()` (`scripts/lib/forge_control.py:67-70`) reads the newest `forge-events.git_ref_window` (2000) records of the whole log and returns `complete = found.size < tail`. That flag is computed over the whole log, not over the channel or the branch, so once the log holds more than 2000 records it is `false` on every read. `EventLog.read` (`core.js:164-173`) is per-channel but also capped: `KEEP_EVENTS` 50000, the oldest records deleted on append (`core.js:153-161`).
- **M4. There is no dedupe on the event log.** `EventLog.append` (`core.js:153-161`) never checks `event_id`. The only "handled once" guard is the webhook-id ring in the handler (`core.js:18`, `:645-655`), and it guards jobs, not log records. `originEnvelope` (`core.js:216-222`) does derive `event_id` from the natural key, so an identical record has an identical id, but nothing reads that id to collapse duplicates.
- **M5. Consumers judge by commit position.** `commit_check.push_errors` (`scripts/lib/commit_check.py:74-89`) maps each push's `before` and `after` to the PR's commit index. A `before` that is not in the PR's commit list maps to -1. A branch's creation push carries `before` = 40 zeros, so it is judged as `after + 1` commits brought at once. This is a pre-existing consumer behavior for GitHub too, not introduced here.
- **M6. The coverage test pins the gap.** `test_forge_contract.py:546-554` asserts the refusal messages and that `{'pushes', 'force_pushes'}` is the set of missing names. Those tests encode the gap as the contract.

## Causas raiz

### R1 — the engine never journals a ref move
Cadeia de porquês:
1. Why does origin refuse `pushes`? The adapter has no `pushes` method and no proof (M1).
2. Why no method? The adapter was built against the vendor's API surface, which has no push route, so there was nothing to call.
3. Why was the vendor surface the only source? The webhook's `refUpdates` was read for two branches (base, wake) and nothing else; the ref triple was never written anywhere (M2).
4. Why was the triple not written? The journal's contracts cover PR events only (`contracts/events/`: `pr.*`, `branch.stale`, `train.*`); there is no event type for a ref move, so the handler had no envelope to write.
Classe: mecanismo faltando

### R2 — a windowed read cannot say "complete" for one branch
Cadeia de porquês:
1. Why could a truncated read look like "no force push"? `pushes`/`force_pushes` return a bare list; an empty list means "nothing found" to every consumer.
2. Why does the list carry no completeness? The port operations were specified against GitHub's activity route, which pages the full history for a ref.
3. Why does the Origin reader window? `recent()` reads the newest 2000 records of the whole log, for speed, and `read()` is capped by `KEEP_EVENTS` (M3).
4. Why is there no branch-level completeness proof? `complete` is computed over the whole log, not over the branch, and is therefore always `false` on any busy log (M3).
Classe: arquitetura/desenho

### R3 — the coverage test encodes the gap as the contract
Cadeia de porquês:
1. Why do the refusal tests pass today? They assert the refusal text and the missing-name set (M6).
2. Why was that the chosen assertion? The gap was known, and pinning it was the cheapest way to keep the operation check honest.
3. Why is there no test that flips when the gap closes? The operation check (`unit_check --operations`) measures demands, not whether a pinned refusal is still true.
Classe: mecanismo faltando

## Findings (what the audit adds to the brief)

1. Fact 2 holds, so the triple exists in the webhook. The only place it is recorded today is nowhere.
2. Fact 3 holds: `pr.pushed` carries no before, no forced. It must not be the ref-record source.
3. The duplicate-count risk (one push, two deliveries) is avoided by construction if the ref record is written only from `repository.pushed`. `pull_request.head_ref.pushed` keeps writing `pr.pushed` only. A test must prove the pair yields one record.
4. Truncation (M3) is real on any busy log: `complete` is `false` on the window. A branch-level proof is needed. The available one is the branch's creation record (`created: true`, `before` = 40 zeros): if the window reaches it, every push of the branch is in the window.
5. M5 is a pre-existing consumer issue for the creation push. It is not fixed here; the port keeps GitHub's shape so the consumer behaves the same on both adapters. Owner: commit-check (scripts/lib/commit_check.py).
6. The event contract needs more than the JSON file: `schemas.lock.json`, the generated TypeScript and Python files, the `ORIGIN_NATURAL_KEY` map in `core.js`, and the EVENTS.md row. The `scripts/generate` step produces the generated files.

## Distância do estado da arte
The chosen mechanism (journal ref moves from the webhook at the source, read back under a per-branch completeness rule) is rung 1 of the research's ladder. A per-branch channel (rung 3) would remove the shared-window limit; it is deferred until live refusals show whether that limit is reached (see research.md, Escada de ambição).

## Base defects expected
- A5 (commit-check creation-push judgement, plan.md): pre-existing, owner commit-check; not changed here.
