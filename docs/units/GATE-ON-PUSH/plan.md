# GATE-ON-PUSH — plan

Stage 4 of the unit flow (D-077, Padrão v7, D-081). Reads [audit.md](audit.md) (`## Causas raiz` R1–R4) and
[research.md](research.md) (`## Escada de ambição`). Decides before it executes; the code is the next stage, in its
own PR from `mod/roadmap-integration`. The PR description (#812) mirrors this file.

Goal of this plan: the smallest first rung that takes polling out of the merge path. The green verdict's own
`pr.ready` wakes the train for that one PR; a periodic sweep with conditional requests stays only as the safety net.

## Alternativas

Criteria: resolve a raiz? (removes the cause, or only today's symptom), custo, reversibilidade, risco, degrau (rung of
research.md's ladder).

### R1 A switch of the train is read inside the gate's pinned process tree (regra faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Change the registry default of `train.trigger_mode`, which the pinned gate does read | remendo | não: the next switch flipped in the shared store is invisible to the hook again, and D-069 item 5 says switches go through the shared store | 2 min | total | the pin keeps hiding every other post-verdict switch | 0 |
| A2 A post-verdict hook reads its switches from the shared store even under `OU_CONFIG_STORE=file` (`config.shared(name)`), with a test that pins the store and flips the shared value | corrige a classe | sim: the verdict's inputs stay pinned, its effects read the shared switches | 30 min + tests | one function, revert the commit | a shared-store read after the verdict (one window read, cached 60 s; ~0 with conditional reads) | 1 |
| A3 The gate does nothing after its verdict; a service consumes the events | redesenho | sim: no hook, nothing to pin | rung 3 (host, identity) | high | needs Daniel (intake Lacunas) | 3 |

### R2 The only transport makes the producer of the event run its consumer (arquitetura/desenho)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Fix R1 only, so `detached` really starts `scripts/train run` in the lane's container | remendo | não: the train then runs in every lane container on the PR's own code, against train.md's 27/10 rule and P-46, and every lane run contends for the lock (audit finding 9) | 5 min | one key | a PR's own admission code admits it; 35-min lease held by a lane container that is reclaimed | 0 |
| A2 A wake channel over git: the `pr.ready` producer fast-forwards `train.wake_ref` (`train/wake`) with a commit naming `{pr, sha, event_id}`, the same zero-REST path as the lock; in the train-role container a long `scripts/train serve` process waits on that ref (`git ls-remote`, no REST) and runs one admission per wake; a sweep every `train.sweep_interval_s` is the safety net | corrige a classe | sim, within the cloud constraints: the producer only writes an event, the designated consumer is woken by it; waiting on a git ref is a read, but of git, not of the REST budget, and per wake costs one admission | ~3 h + tests | `train.trigger_mode` back to `emit_only` (one key); the ref is inert when nobody serves | a lost wake (push refused twice) waits for the sweep; the session's background process ends at its 2 h limit and is restarted on its exit event | 1 |
| A3 A webhook receiver on an always-on host with a durable queue (outbox, idempotent handlers, redelivery) and its own App identity | redesenho | sim, and the true push | a host, an App install and a secret | medium | Daniel's call (intake Lacunas: identity, host) | 3 |
| A4 The lane session messages the train-role session after its gate (session-to-session message) | remendo | não: an AI turn per verdict, not a mechanism the gate can call; contradicts "sessions only read and write text" | 0 code | total | a forgotten message is a lost merge | 0 |

### R3 The train has no unit of work smaller than the whole queue (mecanismo faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Raise `forge-events.github_max_pages` and run the loop less often | remendo | não: the replay stays O(open PRs) per run and the merge read O(channel) | 1 min | one key | latency grows with the interval; the read still grows with #548 | 0 |
| A2 `scripts/train run --pr <n>`: the queue is that PR's entry (`queue_entry` over its log and head), no bootstrap and no post-release rebuild under `--pr`; the post-merge reads (`quarantine.open`, `prs_since_release`) use the newest window (`recent`) instead of the whole channel | corrige a classe | sim: a wake costs one PR's reads; the full replay remains the sweep, i.e. the recovery path D-069 item 4 asks for | ~1.5 h + tests | without `--pr` the run is today's | a quarantine older than the window is not released by a merge (it stays open: the safe direction); `prs_since_release` is a lower bound when the window has no `release.ready` (production frozen, none since D-054) | 1 |
| A3 The queue lives in the service's store, fed by webhooks; `events_since` over its own log | redesenho | sim | rung 3 | medium | same as R2 A3 | 3 |

### R4 A read costs quota even when nothing changed, and nobody sees the budget run out (mecanismo faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Longer `config.store_cache_ttl_s` and a slower loop | remendo | não: identical reads still count, exhaustion still silent | 1 min | one key | stale switches | 0 |
| A2 Conditional GETs: `github_api` keeps an `ETag` cache per checkout (flock, like `forge_rate`) and sends `If-None-Match`; a `304` returns the cached body. Plus a `forge.rate.limited` v1 event when GitHub refuses on the primary or secondary limit, and the train's REST count on its `engine.step.measured` | corrige a classe | sim: an unchanged read costs no primary quota; an exhaustion is on the log and measurable | ~1.5 h + tests | a registry switch for the cache; the event is additive | a stale cache entry only if GitHub sends a wrong `ETag` (the body is still the forge's) | 1–2 |
| A3 A GitHub App installation token for the train, its own budget | redesenho | sim, isolation between roles | an App install and a secret | high | Daniel (intake Lacunas: identity) | 2 |

## Escolha
- R1 → A2: the only option that fixes every post-verdict switch, not just this one; A1 leaves the pin hiding the next
  switch, A3 is rung 3.
- R2 → A2: removes the producer-runs-consumer design inside today's constraints (no Actions, no new host, the proxy's
  git path); A1 breaks train.md's rule and P-46, A4 puts an AI turn in the merge path, A3 needs Daniel.
  Follow-up: rung 3 (A3), a new unit once Daniel decides the host and the identity (intake Lacunas).
- R3 → A2: one PR per wake is the unit of work `merge_group` has; the replay stays as the sweep. A3 rides R2's A3.
- R4 → A2: conditional reads are the reference's own advice and need no new identity. Follow-up: rung 2 (A3, the
  train's App token), after Daniel answers the identity gap; the rate event of A2 is its measurement.

## Commits
The execution PR, from `mod/roadmap-integration`, one commit per push, each with its tests (D-025):

1. **Shared switches after the verdict (R1).** `config.shared(name)` reads the registry's shared store whatever
   `OU_CONFIG_STORE` pins; `train_trigger.start` reads `train.trigger_mode` through it. Files:
   `scripts/lib/config.py`, `scripts/lib/train_trigger.py`, `scripts/tests/test_train_trigger.py`.
2. **One PR per run (R3).** `scripts/train run --pr <n>`: the entry from that PR's log and head, admitted
   (`Train.admit`) or a batch of one, no bootstrap, no post-release rebuild. Files: `scripts/lib/train.py`,
   `scripts/lib/train_queue.py`, `scripts/tests/train/test_queue.py`, `scripts/tests/test_train.py`.
3. **Bounded post-merge reads (R3, audit finding 6).** `quarantine.open` and `prs_since_release` read the newest window.
   Files: `scripts/lib/quarantine.py`, `scripts/lib/train_verdict.py`, `scripts/tests/train/test_verdict.py`,
   `scripts/tests/train/test_flakes.py`.
4. **The wake (R2).** `train.trigger_mode` gains `wake` (additive enum value), `train.wake_ref`; the producer
   fast-forwards the ref through `forge_git_ref` (one retry on a refused fast-forward, then the sweep catches it);
   `gate_report.ready_hook` passes the `pr.ready` envelope to `train_trigger.start` (a gate file: the body cites
   D-065 (1), "pr.ready tries the train", for D-025). Files: `scripts/lib/train_trigger.py`,
   `scripts/lib/forge_git_ref.py`, `scripts/lib/gate_report.py`, `config/registry/train.json` and its generated
   module, `scripts/tests/test_forge_git_ref.py`, `scripts/tests/test_train_trigger.py`.
5. **`scripts/train serve` (R2).** In the train-role container: waits on `train.wake_ref` with `git ls-remote` every
   `train.wake_poll_s`, runs `run --pr` for each wake after the last one served (the ref's own history is the wake
   log), a full `run` every `train.sweep_interval_s` and once at start, and exits after `train.serve_max_s` (below the
   session's 2 h background limit) so its exit event wakes the session to restart it. Files: `scripts/lib/train.py`,
   `scripts/lib/train_serve.py`, `config/registry/train.json`, `scripts/tests/train/test_serve.py`,
   `docs/operations/train.md` ("The train-role session").
6. **Conditional reads (R4).** `ETag` cache in `github_api` (`github-client.etag_cache_path`, switch
   `github-client.conditional_reads`), counted and `304` calls reported per process. Files: `scripts/lib/github_api.py`,
   `config/registry/github-client.json` and its generated module, `scripts/tests/test_github_api.py`.
7. **Budget on the log (R4).** `forge.rate.limited` v1 (`contracts/events/`, additive), emitted best effort by
   `forge_rate` on a refusal; the train's counted REST calls on its `engine.step.measured`. Files:
   `contracts/events/forge.rate.limited.v1.json`, `contracts/events/schemas.lock.json`, `scripts/lib/forge_rate.py`,
   `scripts/lib/train.py`, `scripts/tests/test_forge_rate.py`.
8. **Retro.** `docs/units/GATE-ON-PUSH/retro.md` with the numbers of [research.md](research.md#success-measured) over
   the first working day.

Graph: `1 → 4 → 5`, `2 → 3`, `2 → 5`, `6 → 7`, all → 8. Parallel branches: {1, 4}, {2, 3}, {6, 7}; `train.py` is owned
by 2, then 5, then 7 (sequential), `train_trigger.py` by 1 then 4, `config/registry/train.json` by 4 then 5.

After the merge, and not by the executing session: the coordinator sets `scripts/config set train.trigger_mode wake
--reason …` and the train-role session starts `scripts/train serve` in the background. Rollback:
`train.trigger_mode emit_only` and stop `serve`; the train-role session's runs work as today.

## Premises
Premises: P-18, P-46

- P-18 (the train is the only merger): **CRITICAL** — the wake path merges into `mod/roadmap-integration` (the source of
  truth); `serve` runs only in the train-role session, never in a lane container or on the box.
- P-46 (the pinned gate judges): kept; the producer only writes a ref, and admission runs from the train-role checkout
  at the tip.
- Assumption to register at execution (`scripts/premises find` first): a background process of a Claude Code cloud
  session lives up to its 2 h limit and its exit wakes the session. Blast radius: if false, `serve` must be restarted by
  the coordinator's heartbeat; the sweep still merges.

## Tests
- 1: `test_train_trigger.py` — with `OU_CONFIG_STORE=file` and a shared store saying `wake` (or `detached`), the hook
  acts; with the shared store saying `emit_only`, it does not.
- 2: `train/test_queue.py`, `test_train.py` — `run --pr` reads one log and one head (call counts), admits or batches
  that PR only, never bootstraps.
- 3: `train/test_verdict.py`, `train/test_flakes.py` — a merge on a channel longer than `github_max_pages` emits
  `integration.advanced`; the window read count is bounded.
- 4: `test_forge_git_ref.py` (the REST git-data guard still passes), `test_train_trigger.py` — two producers, one
  refused fast-forward retried, both wakes on the ref.
- 5: `train/test_serve.py` — a wake runs one `run --pr`; no wake and no sweep due costs zero forge calls; the sweep runs
  at start and per interval; `serve` exits at `train.serve_max_s`.
- 6: `test_github_api.py` — a `304` returns the cached body and is counted apart; the switch off sends no
  `If-None-Match`.
- 7: `test_forge_rate.py` — a primary and a secondary refusal each emit one `forge.rate.limited`; the contract lock
  test passes.
- Final gate once on the exact head: `scripts/gate-dev --pr <n>`. Success is read from forge events on the first day
  (research.md "Success, measured"): green to merged p50 ≤ 60 s once #809 lets strict verdicts admit; ≤ 20 counted REST
  calls per merge; 0 with an empty queue between sweeps.

## Base defects expected
- Strict verdicts never match on toolchain (`train.verdict_fallback=tier2`), owner #809 (D-080): until it merges, a
  woken PR still takes a tier-2 run, so the trigger is fixed but "seconds" is not.
- The repository channel read past 20 pages (audit finding 6): fixed by commit 3 of this plan; until then every merge
  raises after the merge call. Owner: this unit, with the engine-train lane (#689) informed.
- Several sessions hold the train lock (audit finding 9): the coordinator's, unchanged here.
- `DECISIONS.md` textual conflicts: DOCS-API (#811).

## Cheapest useful effort
Action: the execution PR: the shared switch read, `run --pr`, bounded post-merge reads, the git wake, `scripts/train serve`, conditional reads and the rate event, each with tests, and one gate run
Cost: about 6 hours of session time over 8 commits, one gate run on the final head, and a few hundred REST calls for the gate and the first day's measurement
Requirement: Daniel, who wants a green verdict to merge in seconds without a polling loop or a quota stall (29/10 19:06 BRT, top priority)
Cheaper rejected: fixing the pinned read only (A1 of R2: the train would run in lane containers on the PR's own code, against train.md and P-46); a slower loop or more pages (A1 of R3/R4: latency up, quota unchanged); a webhook service first (rung 3: needs a host and an identity Daniel has not decided, and would leave today's train broken meanwhile)
