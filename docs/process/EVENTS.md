# Event contract (D-065)

Every step of the delivery flow is triggered by an event; nothing runs on a clock. Since **D-314** (14/11/2026), the
live source-of-truth forge is GitHub `openuniversity-si/open-university` (`main`, GitHub merge queue, the `tower/gate`
and `web` GitHub Actions checks, and `.github/workflows/deploy-doorbell.yml` for the engine's AWS deploy); Cursor Origin
is only a one-way mirror of `main`. The Origin-era event port (`scripts/lib/forge_events.py`, M2), merge train
(`scripts/train`) and battery role documented below remain in the tree as dormant tooling (`D-314`), and the
Cloudflare Worker control plane was retired (`D-323`). The original event-contract decision is
[D-065](../domain/DECISIONS.md); production stays protected by [D-054](RELEASES.md).
Events use the envelope and the metrics event of the [shared contract](principles/D-069.md#event-envelope-owner-m2)
(D-069).

The unit of parallelism is the *unit* (`units/<id>/unit.json`, a versioned contract, its own battery) and the *lane*, one long session that exclusively owns a set of units. Until the unit manifests exist (U0), a
lane owns the old front paths.

Transport v0: the producer writes the event to the forge. When the consumer is a locked role (train, battery), the
producer tries to take the lock and, if it gets it, runs that role until its queue is empty.

## Sessions and lanes (D-065 (4), amends D-007)

One lane is one long session. A lane's session starts once, through `work.assigned`, and stays for the lane's PRs; it
is not a fresh session per PR. The PRs of a unit are serial inside its lane, one lane owns a unit at a time, and lanes
run in parallel. Until the unit manifests exist (U0), a lane owns the old front paths.

The setup a lane pays once is what the event contract measures as `session.cold` (toolchain, install, test database).
Tier-1 results of a lane are reused in its session through the content-keyed cache (local gate); tiers 2 and 3 never use it.

A session acts on events, never on a fixed interval: a gate ends when its process exits, and the next PR of a lane
starts on the event that makes it ready. The live gate status comment and the gate lifecycle it follows are described in gate status.

## Events

| Event | Producer → consumer | Minimal payload | Triggers |
|---|---|---|---|
| `work.assigned` | maestro → lane session | `lane_id`, `units[]`, `item`, `base_sha` | The lane's session starts, or continues with its next PR. |
| `pr.opened` | forge → maestro | `pr`, `head`, `base`, `lane_id` and `units[]` (from the body) | Records ownership through the ownership check (every changed file belongs to a unit the lane owns). |
| `pr.pushed` | forge → train, maestro | `pr`, `head_sha` | The PR leaves the train queue until a new `pr.ready`. |
| `ref.updated` | forge (control plane) → its own `/v1/events` journal | `repo`, `ref`, `before`, `after`, `created`, `forced` | A ref of the repository moved, as `repository.pushed` reported it. Written on the repository channel only; no engine reader since the D-300 addendum (the Origin adapter answers `pushes` and `force_pushes` from the clone's reflog, in the same shape). |
| `branch.stale` | `forge_events` port (on a trigger) → maestro | `pr`, `opened_at`, `age_h`, `max_age_h` | A branch older than `process.branch_max_age_h`, evaluated when `pr.pushed` or `pr.ready` is appended, never on a clock (P-32, D-069 item 11). |
| `gate.passed` / `gate.failed` (tier 1) | session, through `gate_report` → train on pass, session on fail | `pr`, `sha`, `tier`, `plan`, per-stage time, class (`code`, `env`, `contract`), input hash (v4: `input_digest`), `unit`, `premises` | A pass with a valid body emits `pr.ready`; an `env` failure emits `env.drift`. |
| `pr.checked` | `structure-check --metadata` (GX-15) → pr.ready, session | `pr`, `sha`, `base_sha`, `result`, `errors[]` | The PR-metadata verdict for a head; pr.ready needs `pass` for the same `sha`. |
| `gate.started` | `gate_status begin` (GX-25, driven by `gate-local` at `begin`; switch `gate-eta.started_enabled`; stored in the local file log, `forge-events.file_kinds`, so per-stage timing does not spend forge requests) → session, coordinator | `pr` or null, `sha`, `tier`, `plan`, `expected_wall_s`, `critical_path[]` | The ETA. The verdict is the wake; there is no `gate.finished`. |
| `base.red` / `base.green` | battery role (tier 3, GX-32) → adjudication, train | `base_sha`, `tests[]` and `since` / `cleared[]` | Adjudication excuses a listed test for the proof's `base_sha`; re-gate asks pause while red. |
| `lock.lifted` | any lock, through `regime.lift` (D-260) → `gate-noite`, the exit review of the regime | `lock`, `lane`, `time` | A lock did not refuse because the exception regime was active; one event per passage, never silent. |
| `pr.ready` | session → train | `pr`, `head_sha`, `lane_id`, `unit`, `premises`, evidence | Tries the train lock, queues the PR, starts a batch if the train is free. |
| `train.batch.started` | train → maestro | `batch_id`, `tip_sha`, `prs[]` | Records the batch. |
| `train.batch.shards` | train (SH-1, `train.shard_shadow`) → maestro | `batch_id`, `base_sha`, `shard_key`, `members[]` (`pr`, `key[]`), `union_key[]`, `shards[]`, `collisions[]` (`prs`, `key`, `files`) | Shadow data for the sharded tier 2 (GX-34): the key each member and the batch would take, the shards it would form and where two members collide. Never read by the verdict or the merge. |
| `pr.conflicted` | train (local merge failed, a refused merge that really conflicts with the tip, or in verdict mode a textual conflict of the train's own resync; D-075, D-078) → lane session | `pr`, `files`, `tip_sha`; v2 `cause` always `textual` with at least one file (`train_verdict.conflicted` raises without one, D-078; past events may carry the retired `not-admitted`, `unpushable`, `forge-refused` with none) and `detail` | The lane resolves it and re-emits `pr.ready`. In verdict mode a base that merges cleanly is merged into the head by the train itself (`Train-Resync` trailer), never sent back. |
| `pr.refused` | train (ownership check, D-069 item 8) → lane session | `pr`, `reason`, `units`, `files` | The head changes another lane's unit without its owner's approval: the lane asks the owner or splits the change. A no-op until U0's manifests exist. |
| `train.batch.green` → `pr.merged` | train → lane session, maestro | `batch_id`, `prs[]`, `merge_shas`, validated tree | The batch merges; each lane moves on. |
| `pr.merged` (REC-1) | train → program, SLO, lane session | `pr`, `sha`, `unit`, `merge_sha`, `batch_id` (`b-…` a batch; `v-…` a PR merged alone on its verdict, `s-…` admitted on disjoint shards, D-075); one event per merged PR | Now also on the repository channel (the same event id, in the same write), with the unit when the change names one: the one unit manifest covering the changed files, taken from `pr.ready`. `unit` null stays legal (a change spanning units, or touching none). |
| `train.batch.red` → `pr.ejected` | train (bisection; in verdict mode also a red re-verdict of the train's resync, `batch_id` `r-…`) → lane session | `pr`, `stage`, `test`, `log`, culprit or flake | The culprit leaves the batch; the rest is retried. |
| `train.queue.empty` | train → train | none | Releases the lock. |
| `train.queue.growing` | train, when the queue at batch end exceeds `train.queue_growing_batches` batches of `train.batch_size` → engine lane | queue size, tier-2 time | A PR that speeds up tier 2. |
| `integration.advanced` | train → battery role | `tip_sha`, `batch_id`, `prs[]`, PRs since the last release | Tier 3 on the newest tip (coalescing). |
| `battery.green` / `battery.red` | battery → release controller, maestro | `tip_sha`, result | Red: batch bisection, then a fix or a revert. Green: evaluate the release criterion. |
| `battery.culprit` | battery (batch bisection) → lane session, maestro | `tip_sha`, `good_sha`, `culprit_sha`, `batch_id`, `prs[]`, candidates still in doubt | The lane fixes or reverts the culprit batch; the battery never reverts or pushes code. |
| `release.ready` | release controller → release pipeline (roadmap step 8) | `tip_sha`, PRs since the last release | Today it is only recorded (production is frozen, D-054). |
| `selection.escape` | train → engine lane | `pr`, test | Tier 2 failed a test tier 1 did not select: a PR widens the selection map. |
| `test.flaked` | train or battery → owner of the test's unit | test, `sha`, log | Quarantine with an owner and a stabilizing PR; no retry in the gate (D-025). |
| `test.quarantined` | train or battery, after `test.flaked` (`scripts/lib/quarantine.py`) → owner of the test's unit | test, `sha` it flaked on, `owner` (the unit manifest's, or `quarantine.unknown_owner`), `flaked_event` | The owner opens a stabilizing PR whose body names the test on a `Stabilizes:` line. The test stays blocking in every tier; the open quarantines are a replay of the repository log (M7). |
| `test.unquarantined` | train, when the stabilizing PR merges → owner, maestro | test, `owner`, `quarantined_event`, `stabilizing_pr`, merge `sha` | The quarantine ends. |
| `defect.detected` | `gate_report`, when a PR's failing test fails on the integration base with the same signature (`scripts/lib/defect_detect.py`) → registry, router | `defect`, `test`, `signature`, `owner`, `stage`, `base_sha`, `run` | The verdict lists the test under `known_defects` and does not block the PR; the router records and routes the defect (known defects). |
| `defect.registered` | `scripts/defects record` → router | `defect`, `test`, `signature`, `owner` (from the unit map), `area` | The defect is open; the router prices it by queue impact. |
| `defect.routed` | router → owner lane, units touching the area | `defect`, `priority`, `class`, `fix_item`, `work_event`, `touching[]`, `dependents[]`, `masked` | A fix unit is open for the owner (`work.assigned`); `dependents` wait for it, the other PRs proceed. |
| `defect.resolved` | `scripts/defects resolve` (the fix unit's merge) → gate | `defect`, `fix_pr`, `merge_sha` | The next gate that sees the test pass on the base verifies it. |
| `defect.verified` | `gate_report`, when a resolved defect's test passes on the base → maestro | `defect`, `base_sha`, `run` | The defect is closed; nothing waits on it. |
| `defect.reopened` | `gate_report`, when a resolved defect's test still fails on the base → router | `defect`, `base_sha`, `observed_signature`, `run` | The fix did not hold; the defect is open again and routes again. |
| `lesson.recorded` | `scripts/lessons add` / `ingest` (`docs/operations/lessons-guide.md`) → aggregator | `lesson`, `class`, `kind`, `owner`, `source_unit` | A unit retro's lesson is in the registry as `proposed`; the aggregator counts it under its class. |
| `lesson.applied` | `scripts/lessons apply` → aggregator, effect | `lesson`, `class`, `kind`, `owner`, `applied_pr`, `ref` | The change the lesson asks for is in the engine; `lessons effect` measures its class before and after this moment. |
| `lesson.retired` | `scripts/lessons retire` → aggregator | `lesson`, `class`, `why` | The lesson no longer applies; it leaves the brief query and the open counts. |
| `budget.measured` | `scripts/train run` (`train.rest_calls_per_run_max`) → `scripts/service metrics` | `metric`, `value` | A budgeted metric that is not a duration was measured: today the REST calls of one train run. The web bundle and page latency producers left with Open University (D-111, VAZÃO F44); `scripts/budgets` folds only `engine.step.measured`. |
| `forge.rate.limited` | Retired GitHub producer (D-293); the immutable event schema remains readable in historical journals | `kind`, `method`, `endpoint`, `at`, `blocked_s` | No live producer after the GitHub client and limiter were removed. |
| `lessons.reported` | `scripts/lessons report` → maestro | `digest`, `lessons`, `classes`, `top_class`, `top_lost_ms` | The generated lessons report (`docs/process/lessons.md`) changed; the top class is the next engine fix by queue impact. |
| `gate.slow` | `gate_status final` on each tier-1 verdict (GX-25; `forge_events.gate_slow`, then `slo.run`), when the tier-1 median of the last `gate.slow_window_events` verdicts exceeds `gate.slow_median_s` → engine lane | median, slowest stages | A PR that makes tier 1 faster. `slo.run` runs on the same verdict (event-driven, P-32). |
| `session.cold` | session → engine lane | session, setup time | A PR that makes session start faster. |
| `contract.question` | session → A Torre | the two conflicting rules, the failing proof | A Torre decides. |
| `common-key.requested` | session → kernel lane | value, areas | The kernel lane adds the common key. |
| `env.drift` | gate `env` class → env lane | stage, tool, versions | An env patch PR. Producers: the gate (class `env`) and, from GX-02, the train when tier 2 halts on an `env` or `contract` class (it halts and never ejects). |
| `session.ended` / `session.failed` | platform or session → maestro | session, `lane_id`, last `sha` | The maestro reassigns the lane. |
| `engine.session.heartbeat` | the push guard's hook (`.githooks`, `scripts/lib/push_guard.py`) → the session's own log (`push-guard.heartbeat_adapter`) | `branch`, `result` (ok, failed), the commits `pushed` one per push, `detail` | Nothing while ok; a failed push is retried by the next commit, never batched (X1, D-022). A gate verdict is the gate's own sign of life. |
| `engine.session.stalled` | `scripts/stall-report --emit`, on demand → orchestrator | `pr`, `branch`, `reason` (no_push, red_gate, owner_wait), `since`, last push and gate | The orchestrator acts without anyone asking: a red gate or an owner wait gets a decision, a quiet branch gets its lane checked (DECIDE, THEN REPORT). |
| `unit.addressable` | address scan → owning lane | `unit`, `sha` | Every importer already uses the unit's address; the unit may move. No producer since the address scan left with Open University's TypeScript project (D-111). |
| `unit.migrated` | train (at merge) → maestro | `unit`, `merge_sha` | The unit lives in `units/<id>/` with its contract, a battery ≤ 10 s and zero literals; counts the migration's progress. |
| `contract.changed` | gate (diff of the contract `.d.ts`) → train | `unit`, old and new version, additive or breaking | Additive: proceeds. Breaking: tier 2 runs the consumers' contract tests and expand→contract is required. |
| `contract.deprecated` / `contract.retired` | owning lane → consuming lanes | `unit`, symbol, version | Opens a migration item in each consuming lane; the last consumer releases the removal. |
| `unit.hot` / `unit.oversize` | maestro (the unit's queue exceeds its lane's capacity) / checker (budget exceeded) → engine lane | `unit`, queue or size | A PR that splits the unit. |
| `engine.step.measured` | every engine step (first: each gate stage, through `gate_report`) → dashboard, `gate.slow` | `step`, `duration_ms`, `tokens_in`, `tokens_out`, `model`, `provider`, `result` (`ok`, `fail`, `blocked`), `retries` | Observability (D-069 item 6); the dashboard and SLOs are derived from the log. The train's verdict branch (D-075) measures `train:admit` (ok: merged alone), `train:shard-admit` (ok: would admit under `train.shard_admit` shadow, or admitted under on; blocked: refused) and `train:reverdict` (the resync's gate API call: ok PASSED, fail handed back, blocked halted). |
| `slo.breached` | `scripts/slo evaluate` (run by the producer of `pr.merged` or `gate.*`, or by the maestro, on that event) → engine lane, maestro | `slo` (a `config/registry/slo.json` name), `value`, `limit`, `bound`, `samples`, `evidence` ([schema](../../contracts/events/slo.breached.v1.json)); `pr` is null | A tuning PR for the breached SLO (plan v3.1 wave 4). The entries live only in the registry; `scripts/dashboard` renders every SLO from the log. |
| `premise.classified`, `premise.blocked`, `premise.batch.ready`, `premise.answered`, `premise.review.due` | see plan v3 §8.4 | see `contracts/events/premise.*.v1.json` | The premise register (D-066); the events `scripts/premises` already prints are in the next section. |
| `config.changed` | `scripts/config` (set, set --default, revert) → the change store, through the `forge_events` port (adapter `config.store_adapter`); any reader of the parameter | `name`, `old`, `new`, `actor`, `reason`, `at`, `reverts` ([schema](../../contracts/events/config.changed.v1.json)); `pr` is null (repository level) | The effective value changes without a code change ([D-068](../domain/DECISIONS.md)); replaying the log rebuilds every override, and a revert is a new `config.changed`. |
| `config.snapshot` | `scripts/config` (set, set --default, revert), after `config.store_snapshot_after_events` changes since the newest snapshot, on a remote store only → the change store | `overrides`, `through`, `count`, `at` ([schema](../../contracts/events/config.snapshot.v1.json)); `pr` is null | A reader of the store reads back only to its newest snapshot, so the log can outgrow the shared journal window. A derived view: replaying the log without it gives the same overrides. A window with no snapshot over an older log is an error, never a truncated read. |

The `premise.*` events are defined by D-066 (the premise register, PR P1); their payload schemas live with the others.
Every payload also carries the subject `repo`, `pr`, `sha`, the `unit` (null until U0) and the `premises` (the PR's
`Premises:` ids); the schemas in `contracts/events/` are the source of truth for every field. The four v1 payloads
`scripts/premises` prints (below) predate the port and carry no subject: they are listed in
`forge-events.subject_exempt_schemas`, and their v2 with the subject replaces them when the register publishes through
the port (expand→contract).

The field reference of every event is rendered on demand from these schemas by `scripts/generate docs`, and their
Python types by `scripts/generate python-types` (G1, D-069 items 1 and 2); a committed
type that differs from its schema fails the `generated drift` stage. A locked event schema never changes
(`scripts/lib/event_contracts.py`); every other contract may change only additively within its version, which the
`schema compat` stage checks against the PR base.

## Premise events (D-066)

The premise register (`docs/process/premises/<slug>.yml`, [D-066](../domain/DECISIONS.md)) produces four events. Each is an
envelope `contracts/events/envelope.v1.json` (owner M2) whose payload follows its own schema,
`contracts/events/<type>.v1.json`. The `event_id` is the idempotency key, the sha256 of producer, type and natural key, so
re-emitting is a no-op; `occurred_at` comes from the injected clock. The producer is `premises` (`premises.producer`).

| Event | Producer → consumer | Payload (`contracts/events/…v1.json`) | Natural key | Triggers |
|---|---|---|---|---|
| `premise.proposed` | `scripts/premises propose` → maestro | `id`, `slug`, `statement`, `kind`, `scope`, `source`, `radius`, `reasons` | `id` | A high radius joins the next question batch (at most 7, Daniel); medium goes to A Torre; low to the unit owner. |
| `premise.confirmed` | `scripts/premises answer` → dependents | `id`, `status` (`confirmed` or `validated`), `by`, `at`, `quote` or `where` or `evidence` | `id`, `status`, `at` | Unblocks every open PR whose `Premises:` line cites it. |
| `premise.refuted` | `scripts/premises answer` → dependents | `id`, `by`, `at`, `quote` or `where`, `dependents` | `id`, `at` | Every dependent plan and PR goes to review: open ones fail `premises check`, merged ones become fix items ordered by radius. |
| `premise.blast` | `scripts/premises blast` → maestro | `id`, `radius`, `reasons`, `dependents`, `blocking` | `id`, digest of the dependents | The maestro sees which work a premise reaches and whether it blocks. |

Until `scripts/premises` publishes through the `forge_events` port (M2), it prints each event as one JSON line (`event: {…}`) and
publishes nothing. Publishing the result of `premises check` as the commit status `tower/premises` on the PR head, and
re-judging the open heads on `premise.confirmed` and `premise.refuted`, wait for that port; nothing here calls the forge
directly.


## Plan events (D-071)

The live-planning program ([design](../programs/live-planning/design.md)) owns four event contracts, the only ones for the
live plan (no other program locks a `plan.changed`). Each payload carries the subject fields with `pr`, `sha` and `unit`
null (a plan event is about a program, not a PR). Hand runbook: live-planning.

| Event | Producer → consumer | Payload (`contracts/events/…v1.json`) | Natural key | Triggers |
|---|---|---|---|---|
| `plan.changed` | the planner, or A Torre by hand → coordinator, launcher | `program`, `version`, `parent`, `ops`, `inputs`, `judgment`, `intention`, `expected_effect`, `decided_by`, `reversible`, `escalated`, `digest` | `program`, `version` | The next launch reads the folded plan; one line of `plan-log.jsonl` on `plan/live`. |
| `plan.note` | `scripts/plan note` (a running session) → triage | `program`, `from_unit`, `affects`, `kind`, `evidence`, `text` | `program`, `from_unit`, `kind`, `evidence`, `text` | Triage computes the affected set; the session keeps going. |
| `plan.input` | `scripts/plan input` (Daniel or A Torre's ruling) → triage | `program`, `by`, `at`, `text`, `ref` | `program`, `by`, `at`, `text` | An owner ruling is always promoted to a candidate. |
| `plan.candidate` | `scripts/lib/plan_triage.py` → planner role | `program`, `signature`, `disposition`, `reason`, `source`, `inputs`, `sightings`, `affected`, `partition` | `program`, `signature` | The planner judges it with the design 2.1 questions; `seen` is recorded only. |

## The port: `scripts/lib/forge_events.py`

Callers build a payload (a plain dict) and call `ForgeEvents.emit(type, payload)`; consumers call
`ForgeEvents.read(repo, pr)` and `replay(events)`. No caller touches a forge type, URL or client.

- **Contract.** One schema language, JSON Schema draft 2020-12 (SHARED CONTRACT v3). The envelope is
  `contracts/events/envelope.v1.json`: `event_id`, `type`, `version`, `occurred_at` (RFC 3339 UTC from the injected clock),
  `producer`, `correlation_id`, `payload`. Each payload is `contracts/events/<type>.v<N>.json`; shared fields are in
  `defs.v1.json`. Every payload requires `repo`, `pr` (null for an integration-branch event), `sha` (the head it judges,
  or the integration tip), `unit` (null until U0) and `premises`. `scripts/lib/json_schema.py` validates the 2020-12 subset
  the contracts use and refuses any other keyword, so no rule is silently unchecked.
- **Validation** on emit (nothing invalid is written) and on read (a forged, edited or corrupt entry is rejected and
  reported, never replayed).
- **Idempotency.** `event_id` = sha256 of producer, type and the payload's natural key (`x-natural-key`, JSON pointers
  into the envelope). Re-emitting the same fact is a no-op: the port appends only ids the channel does not hold, and
  `dedupe()` drops duplicates a race or a retried write left in the log. A gate verdict's key is repo, PR, head, plan and
  input hash; a step measurement's key includes the run's `correlation_id`, so each run measures again.
- **Ordering.** A channel's log is append-ordered; `ordering_violations()` shows where `occurred_at` goes backwards.
- **Append-only log and replay.** Adapters append and never rewrite. `replay(events)` rebuilds the per-PR state (gate
  verdict per head and plan, ready, merged, conflicted, ejected) from the log alone; `gate_evidence(state, pr, sha,
  plan)` answers "did this exact head pass this plan" (D-069 item 4).
- **Observability.** `measured(port, step, subject)` (a context manager or decorator) times a step with the injected
  clock and emits `engine.step.measured`; an exception records `fail` and still emits (D-069 item 6).
- **Configuration.** Every parameter (adapter, clock, repository, id algorithm, comment marker and size, trusted
  authors, page size, timeouts, gate producer, tier-1 modes) is an entry of `config/registry/forge-events.json`, read
  with `config.get` (D-068). Shell and `.mjs` producers use `python3 scripts/lib/forge_events.py emit <type> --payload
  JSON --producer NAME --correlation-id ID`.

### Versioning and evolution (P-07, D-029)

A schema file is immutable once it is in `contracts/events/schemas.lock.json`. `scripts/lib/event_contracts.py check`
(run by the script tests) refuses a changed or removed locked schema, an unlocked file, a gap in a type's versions and a
natural key that is not `/correlation_id` or a required payload field; `lock` only adds entries. A change is
expand→contract: add `<type>.v<N+1>.json` (expand), teach readers to accept both versions, move producers to the new
version (`emit` uses the newest unless a version is passed), and retire the old file only when no producer emits it
and replay no longer needs its events (contract). Envelope changes follow the same rule with `envelope.v<N+1>.json`.

### Adapter interface (Origin-era dormant port, D-314)

An adapter implements three methods; payloads and callers never change when the adapter does.

| Method | Contract |
|---|---|
| `append(channel, envelopes)` | Append the envelopes, in order, to the channel's log. Never rewrite or delete. |
| `read(channel)` | Every stored envelope of the channel, in append order, unvalidated (the port validates). |
| `change(repo, number)` | `{head, base, body}` of a change, for the subject and its `Premises:` line. |

A channel is `(repo, pr)`: one log per change, plus the repository log (`pr` null) for integration, train and release
events. `MemoryAdapter` (tests) and `FileAdapter` (append-only JSON Lines under `.gate/events/`, offline runs) live in
the port; the Origin adapter (`scripts/lib/forge_origin.py`) is dormant under D-314.

## Storage: the dormant Origin-era journal (v0, retired control plane D-323)

- **Events: the journal.** `forge-events.log_adapter` is `git-ref` for good (D-296 made permanent by D-300, VAZÃO
  F61): every kind not routed elsewhere, the diary (`scripts/plan note`) and the gate proof with it, went to the
  `train/events` branch on Origin (EVENTS-REF, D-273; dormant since D-314). The engine does not depend on Cloudflare
  for what is its own: on 03/11 the control plane's journal went down with the free plan's read allowance (I-5102f4e9).
  `control` (D-282, CANALE7) left the enum (D-300, SEMENTE §6: no double path): `ControlAdapter`
  (`scripts/lib/forge_control.py`, dormant since D-323 retired the Cloudflare Worker) kept only the `POST /v1/check-run`
  client (D-299). The Origin adapter's journal left it too (D-300 addendum): the `forge.status` trail is the git-ref
  log, and push history is this clone's reflog of the branch's remote-tracking ref, proven against Origin's head
  (`scripts/lib/forge_origin_history.py`). The client sent `Authorization: Bearer $TOWER_EVENTS_TOKEN` (the variable
  named by `forge-events.control_token_env`, never read from a file and never printed) plus
  `content-type: application/json` and `service.user_agent` (D-091: the edge refused urllib's default). Its `append`,
  `read` and `recent` methods on `/v1/events` had no engine reader left and were removed (D-300).
- **Retired control plane (D-323).** The Cloudflare Worker behind `service.control_url` (previously
  `services/control-plane`) was retired by D-323 and is no longer deployed; live delivery runs on GitHub Actions
  (`tower/gate`) and GitHub's merge queue (D-314).
- **A read does not go back to the forge.** With `log_adapter` set, `RoutingAdapter.read` returns the routed logs only:
  the forge's PR comment history is not read again as part of the channel.
- **A broken transport is a broken environment.** No token raises `ControlError('no events token: set
  $TOWER_EVENTS_TOKEN')` before a request is made, a refused call `control plane /v1/check-run answered <code>`, a dead
  host `control plane unreachable: <error>`. None of the three is a reason to fall back to comments: a session that
  meets one records it as a blocker (`scripts/plan note … --kind blocker`) and says so, and the gate fails on
  `FAIL gate evidence: … (class env)` rather than pass without a verdict (D-065).
- **Offline journal.** `file` is the append-only JSON Lines adapter under `forge-events.local_log_dir`. D-293 retired
  the old GitHub event-port adapter, client and tuning keys; selecting it is refused. Live merges and checks now run
  natively on GitHub (D-314), while the dormant Origin-era event port keeps `git-ref` (D-300) and `file`.

### Gate evidence and `.dev.pass`

`gate_report` (end of every `gate-local` run with `--pr` and a commit) publishes, in one append, one
`engine.step.measured` per stage (`gate:<stage>`) and the verdict `gate.passed` or `gate.failed` (tier, plan, per-stage
time and D-027 class, missing stages, input hash, unit, premises; v2, GS1: `cached_tests` [{id, key, source}] for script tests reported
as cached PASS, and on `gate.failed` `failing_tests` [{id, stage, signature}] with `failing_tests_total`, so a failure is
classified and compared with the base's without a session). That event is the gate evidence (D-065); a verdict
that cannot be recorded fails the gate (class `env`). `gate-local` still writes `<sha>.dev.pass` for the local record;
the train (M3) consumes `gate.passed`.

There is no clock anywhere: every consumer is invoked by the producer or by whoever takes the lock.

Defaults, changed only by an event (`config.changed`); each is a registry entry of [D-068](../domain/DECISIONS.md),
read and changed with `scripts/config` (`train.batch_size`, `gate.tier1_target_s`, `gate.slow_window_events`,
`gate.slow_median_s`, `train.queue_growing_batches`, `release.merged_prs_per_release`; the unit limits that
`unit.oversize` and the unit battery judge are `units.size_target`, `units.size_ceiling`, `units.context_budget` and
`battery.unit_time_limit`). Their deprecated `slo.*` aliases left with VAZÃO F44 (one value, one name, D-069 item 1). The registry is the single source of each value (`scripts/config describe <name>`); this
table names the entry and never restates its number. The train (`scripts/lib/train.py`) and the battery role
(`scripts/lib/battery.py`) read their own; until the unit tools read theirs, this contract is their reader:

| Value | Registry entry |
|---|---|
| Batch size B | `train.batch_size` (`config/registry/train.json`) |
| Tier-1 target | `gate.tier1_target_s` in `config/registry/gate.json` |
| `gate.slow` | median of the last `gate.slow_window_events` tier-1 verdicts > `gate.slow_median_s` (`config/registry/gate.json`; `forge_events.gate_slow`) |
| `train.queue.growing` | queue at batch end > `train.queue_growing_batches` × `train.batch_size` |
| Release | `release.merged_prs_per_release` merged PRs (`config/registry/release.json`), or a milestone |

## Program events and the v4 verdict (GX-37, D-070)

GX-37 locks the gate contracts the gate-excellence program needs at once (`plan.changed` is LP2's), so later units add producers and readers, not
schemas; a unit that needs another field adds a new version. Readers accept every locked version (v3 and v4 of the
verdicts). All are additive; nothing emits them yet: `forge_events.default_version` emits the registry pin
`gate-contracts.<type>_version` (3 for `gate.passed` and `gate.failed`) when the caller names no version, so a newly locked
version changes no producer until that entry moves (GX-09 sets 4).

### `gate.passed` / `gate.failed` v4
Additive over v3: `tier` (explicit 1..3, never derived from the mode), `head_tree`, `base_sha` (recorded by the producer:
`baseRefOid` for tier 1, the batch base for tier 2, the tip for tier 3; never resolved from a local ref), `base_tree`,
`gate_version` (id of the tooling that judged: the base tip's gate), `toolchain_id`, `observed_versions`,
`selection {kind, units, tests, digest}`, `input_digest`, per-stage `started_at`, `raw_result`, `cached`,
`carried_from`, `inputs_digest`, a top-level `carried_from {event_id, sha, delta_files[]}` (absent when everything
ran), `cost {wall_s, cpu_s, rest_calls, queue_wait_s, cache_hits, cache_misses}` and `lane_id`. `pr` is null for tier-2
and tier-3 verdicts, which go to the repository channel. The natural key is (`repo`, `pr`, `sha`, `plan`, `input_digest`).

**The `input_digest` recipe (GA2 Q14).** `sha256` over the canonical JSON array
`[head_tree, base_sha, plan, selection.digest, toolchain_id, gate_version]` (sorted keys, no spaces, UTF-8, this order),
implemented once in `scripts/lib/gate_digest.py`. A verifier recomputes it from git (`head_tree`, `base_sha`) and the
toolchain manifest (`toolchain_id`) without trusting the producer's arithmetic; the head sha is the pointer and the
digest is the key.

### `pr.checked` v1
`{repo, pr, sha, base_sha, result: pass|fail, errors[]}`: the PR-metadata verdict (commit plan, pushes, comments,
premises line). It changes without a new head, so it is its own event, bound to the same `sha` as the gate verdict.

### `gate.started` v1
`{repo, pr|null, sha, tier, plan, expected_wall_s, critical_path[]}`: published when a gate begins. The verdict event is
the wake; there is no `gate.finished`.

### `base.red` / `base.green` v1
`base.red {base_sha, since, tests[{id, stage, signature}]}` lists the tests red on the base tip, of any stage kind;
`base.green {base_sha, cleared[]}` clears them. Adjudication excuses a listed test only for the proof's `base_sha` and
only when the PR touched neither its file nor its covers.

## The merge train (M3)

`scripts/train` (`scripts/lib/train.py`, D-065 V3) is the consumer of `pr.ready`. Everything it knows comes from the
logs through the port, so replaying them rebuilds its queue (D-069 item 4); every tunable is a `train.*` entry of
`config/registry/train.json`.

1. **Queue.** Every open change on `train.base_branch` whose latest `pr.ready` names its current head and rests on a
   `gate.passed` of that head (its `evidence`), with no `pr.conflicted`, `pr.ejected`, `pr.refused` or `pr.merged` for
   that head. Oldest `pr.ready` first. A push leaves the queue until the next `pr.ready`; a head the train turned away
   comes back only as a new head (`pr.ready` is idempotent per head).
2. **Lock.** `scripts/train run` takes `train.lock_ref` through the port (leased `train.lock_lease_s`, renewed before
   every batch and tier-2 run; an expired lock may be taken over), runs batches until the queue is empty, emits
   `train.queue.empty`, releases, and looks once more so a `pr.ready` that found the lock taken is not stranded.
3. **Batch.** The first `train.batch_size` PRs. The ownership check (U0's manifests at the tip; a no-op until they
   exist) emits `pr.refused`; the combined head is one merge commit per PR on the tip (`git merge-tree`, no checkout),
   and a PR that does not merge leaves with `pr.conflicted`. Then `train.batch.started`.
4. **Tier 2.** `train.tier2_command` (the full dev plan, `scripts/gate-dev --sha`, no PR scope, a fresh build cache:
   never cached) on the combined head.
5. **Green.** Each PR merges through the port as a merge commit with `--match-head-commit`, only if the tip is still
   the tested base. The tree proof: the merged tip's tree equals the tested combined tree, or the train halts.
   `pr.merged`, `train.batch.green`, `integration.advanced`.
6. **Red.** `train.batch.red`, then bisection over the prefixes of the combined head (at most ceil(log2 B) runs,
   bounded by `train.bisection_max_runs`): the first red prefix's PR leaves with `pr.ejected` (cause `culprit`) and
   the rest is retried in the next batch. No run is retried (D-025). A red verdict that rests on a proven flake ejects
   nobody (next section).
7. **Measures.** `engine.step.measured` for `train:batch`, `train:build`, `train:tier2`, `train:merge` and
   `train:bisect`, from the injected clock (D-069 item 6).

**Switching it on.** The train ships off: `train.enabled` is an `x-flag` entry, default false, and while it is false
`scripts/train run` does nothing and the per-session merge rule of AGENTS.md holds. Its shared value is its registry
file, so the train is switched on for every session by a PR to that file; a machine switches it for itself through its
change store (TR1):

- *Where it lives.* `config.store_adapter` is `file` (D-300, VAZÃO F61: the engine does not depend on Cloudflare for
  what is its own): `config.changed` events live in this checkout's log (`config.store_dir`), a machine-local override
  over the registry. The shared, versioned value of every key is its registry file in git on Origin, changed by a PR.
  `control` (the control plane's event log, `/v1/events`, the events token) stays an explicit choice, never a default:
  on 03/11 its reads exceeded the free plan and took the store down (I-5102f4e9). A store key is changed only in its
  registry file, never through the store.
- *How it is read.* `config.get` replays this checkout's log over the registry. A remote store (an explicit
  `control`) is read at most once per `config.store_cache_ttl_s` per checkout, from the newest `config.snapshot`, which
  a change appends after `config.store_snapshot_after_events` changes; a window with no snapshot over an older log is
  an error, never a truncated read. `config.shared` reads the registry's store whatever `OU_CONFIG_STORE` pins.
- *The pin.* `OU_CONFIG_STORE=file` names this checkout's log for a process tree whatever the registry says: the gate
  exports it (its verdict depends on the head alone) and so do the git hooks and an offline run.
- *On, off, back.* `scripts/config set train.enabled true --actor <who> --reason "<why>"` records a `config.changed`
  with its actor and reason; `scripts/config history train.enabled` lists the changes; `scripts/config revert
  <change-id-prefix> --actor <who> --reason "<why>"` switches it off (a new change, history is never edited), and
  reverting that revert switches it on again. From then on the producer of `pr.ready` runs `scripts/train run`
  (D-065 V3).

**Who emits `pr.ready` and who runs the train.** A dev `gate.passed` on the exact head of a PR whose plan is fully
ticked emits `pr.ready` from `gate_report` (`pr_ready.ready_after_gate`; `scripts/pr-ready` is the manual entry). The
producer then starts `scripts/train run` detached (`scripts/lib/train_trigger.py`, output in `train.trigger_log_dir`);
the run takes the lock or ends `busy`, and does nothing while `train.enabled` is off. The Origin-era train is dormant
(D-314): pull requests now land on GitHub `main` through GitHub's merge queue once `tower/gate`, `web`, and
`gate pinned to the base` are green (AGENTS.md, Delivery flow). What to do on `pr.refused`, `pr.conflicted` and
`pr.ejected`: running the merge train.

## The quarantine (M7)

`scripts/lib/quarantine.py` (D-065 V7, D-069 item 5) turns a flaky test into events; the train uses it today; the
battery role (M6) has its seam at `Battery.red` and feeds it no runs yet. Every tunable is a `quarantine.*` entry of `config/registry/quarantine.json`.

1. **Evidence, never an extra run (D-025).** A flake is a test that failed and passed on the same sha. A green tier-2
   run means every test passed on that content, so a red run on a sha that also has a green run is a proven flake.
   The train's evidence is its batch and bisection runs plus the green runs the repository log records
   (`engine.step.measured` `train:tier2` and `train:bisect` with result `ok`). Combined-head commits are dated from
   their parents, so a later batch that rebuilds content the train already judged runs it on the same sha.
2. **The red batch.** When the combined head or a bisection probe is a proven flake, the bisection stops and nobody is
   ejected: `test.flaked` and `test.quarantined` follow `train.batch.red`, `train:batch` is measured `blocked`, the
   members stay queued and `scripts/train run` ends with `flaked` (no `train.queue.empty`), so the same content is not
   run again in that invocation; the next `pr.ready` runs the next batch. A red verdict without same-sha evidence
   still names its culprit (`pr.ejected`, cause `culprit`, with the failing test files in `test`).
3. **Owner.** The owner of the test's unit: U0's `units/<id>/unit.json` at the flaked commit, through the train's
   ownership interface (`train_ownership.UnitOwnership.owner_of`, trying each `quarantine.test_roots` prefix), or
   `quarantine.unknown_owner` while no manifest covers the test. The owner owes a stabilizing PR.
4. **The test stays blocking.** Quarantine records the flake, its owner and the obligation; it never skips the test,
   retries it or loosens a threshold, and `gate_suite`'s retention rule is unchanged.
5. **Release.** A merged PR whose body names the test on a `Stabilizes: <test>` line, from the owner's lane (or any
   lane while the owner is `quarantine.unknown_owner`), emits `test.unquarantined`.
6. **State.** Every quarantine event is on the repository channel; the open quarantines are a replay of that log
   (`quarantine.state`, D-069 item 4). `scripts/quarantine list` prints them and marks those older than
   `quarantine.max_age_s` overdue, for the maestro to escalate. `quarantine:flaked` and `quarantine:release` are
   measured.

## The battery role (M6)

`scripts/battery` (`scripts/lib/battery.py`, D-065 (5)) is the consumer of `integration.advanced`. Everything it knows
comes from the repository log through the port, so replaying it rebuilds what is pending (D-069 item 4); every tunable
is a `battery.*` entry of `config/registry/battery.json`. The lock loop, the measured run, the prefix bisection and the
fresh-cache command gate are `scripts/lib/engine_role.py`, shared with the train.

1. **Pending tip.** The newest `integration.advanced` whose tip has no `battery.green` or `battery.red`. Coalescing: an
   older advance that a newer one supersedes is never run; tier 3 on the newer tip covers it.
2. **Lock.** `scripts/battery run` takes `battery.lock_ref` (its own lock, apart from the train's, so tier 3 never holds
   up a merge), leased `battery.lock_lease_s` (longer than `battery.tier3_timeout_s`) and renewed before every run,
   runs until no newer tip is pending, releases, and looks once more.
3. **Tier 3.** `battery.tier3_command` (`scripts/gate-local --tier3 --sha <tip>`): every stage of the full plan with a
   fresh build cache, never cached (plan v3 §7.3). Verdict `battery.green` or `battery.red` (duration, failing stages). No run is retried (D-025).
4. **Red.** Bisection over the tips advanced since the last green tip (commits that already exist), at most
   `battery.bisection_max_runs` tier-3 runs: `battery.culprit` names the first red tip, its batch and PRs, or the
   batches still in doubt when the runs run out. The lane fixes or reverts in its next PR; the battery never reverts,
   pushes or merges. Telling a flake from a culprit is the quarantine's (M7, `test.flaked`); its seam is
   `Battery.red`.
5. **Green.** The PRs merged after the last tip a `release.ready` recorded, up to this tip (counted from the advances,
   never from an advance's own `prs_since_release`, which a release in between makes stale), against
   `release.merged_prs_per_release`. When reached, `release.ready` records the tip and those PRs; it only records (no
   deploy, no preview, nothing in production, D-054).
6. **Measures.** `engine.step.measured` for `battery:run` (per tip), `battery:tier3`, `battery:bisect` (per probe) and
   `battery:bisection`, from the injected clock (D-069 item 6).

**Switching it on.** The role ships off: `battery.enabled` is an `x-flag` entry, default false, and while it is false
`scripts/battery run` does nothing. It needs the repository channel (`forge-events.github_log_issue`, as the train
does) and is switched on by a `config.changed`: `scripts/config set battery.enabled true` with its actor and reason;
`scripts/config revert` switches it off. From then on the session that emitted `integration.advanced` (the train's
holder) runs `scripts/battery run` after `scripts/train run` returns (Transport v0), and `scripts/battery pending`
shows the tip it would run.

## Scale

| Piece | 1x | 10x | 100x |
|---|---|---|---|
| Event schema | this table | additive changes only | additive changes only |
| Transport | forge, the producer invokes the consumer | webhook receiver with a queue | partitioned bus |
| Forge writes | about 4 per PR (after PR8) | batch push, one identity per role | own forge (Origin) |
| Train | one | tier 2 in shards | one train per partition, feeding the trunk |
| Battery | one, coalescing to the newest tip | tier 3 in shards | one battery per trunk partition |
| Sequential ids (D-NNN, migrations) | allocated by the author | allocated at merge by the train | allocated at merge by the train |

## Program coordinator (CO1)

D-069. `scripts/coordinator` adds no event type. A launch is a `work.assigned` (item `program/unit#attempt`, `unit` the lower-case id from `docs/programs/<program>/plan.md`); a program's status and the coordinator's decisions are folds of `work.assigned`, `pr.opened`, `pr.ready`, `pr.merged`, `session.ended`, `session.failed`, `gate.passed` and `defect.routed`. The program goal is measured from `pr.merged`. See coordinator.

## Hermetic tests (H1)

D-069 item 5. Script tests run with `scripts/lib/hermetic/` on `PYTHONPATH` (`scripts/gate-local`): the network is denied outside `tests.loopback_hosts` while `tests.network_allowed` is false, random sources are seeded from `tests.random_seed`, a test takes its time from `hermetic.clock()` / `clock` (`tests.clock_start`), and timeouts come from `tests.timeout_ms`, `tests.script_timeout_ms`, `tests.int_timeout_ms` and `tests.hook_timeout_ms`. `scripts/lib/hermetic_check.py` (a structure-check module) fails a wall-clock read, an unseeded random source or an outside socket in a unit test; files that predate it are in `tests.unhermetic_sites`, which only shrinks.

A test that turns flaky under the harness is never retried and never skipped: it goes through the quarantine above (`test.flaked` → `test.quarantined`, owner from the unit manifests) until its owner's stabilizing PR merges.
