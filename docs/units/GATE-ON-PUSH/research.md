# GATE-ON-PUSH — research

Starts from the real problem of [intake.md](intake.md): a green verdict does not cause a merge; a session re-reads
every open PR once a minute on a shared user token, so latency is the poll plus whatever that loop meets, and the quota
it burns stops the flow.

## Quem já resolveu
- **GitHub merge queue + `merge_group` event** —
  <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue>,
  <https://docs.github.com/en/webhooks/webhook-events-and-payloads#merge_group>: a PR enters the queue when its
  required checks pass; the forge builds a `gh-readonly-queue/…` branch (base + queued PRs ahead + this PR), fires
  `merge_group` `checks_requested`, and merges by itself when the required checks on that branch report success. No
  poller anywhere: the forge is the queue and the merger. Solves: verdict → merge with no external loop.
- **bors-ng / Homu, the "not rocket science rule"** — <https://graydon2.dreamwidth.org/1597.html>,
  <https://github.com/bors-ng/bors-ng> (retired in 2023 in favour of the GitHub merge queue),
  <https://github.com/rust-lang/homu>: a bot driven by webhooks (`r+` comment, status/check events) tests base+PR on a
  staging branch and fast-forwards the base only when green; batches, bisects on red. Solves: the base is always green,
  driven by events, one service identity.
- **Zuul gating** — <https://zuul-ci.org/docs/zuul/latest/gating.html>: an event-driven scheduler (Gerrit/GitHub
  events in, no polling) with a *dependent pipeline* that tests each change speculatively on top of the changes ahead of
  it, in parallel; a failure re-forms the queue behind it. Solves: merges at the rate of approvals, not of serial test
  runs.
- **Mergify / Aviator MergeQueue** — <https://docs.mergify.com/merge-queue/>, <https://docs.aviator.co/mergequeue>:
  hosted GitHub Apps; webhook-triggered queues with speculative checks, batching, and (Aviator) affected-target parallel
  queues. Both run under an installation token. Solves: the same as Zuul, as a service with its own quota.
- **Uber SubmitQueue and Google TAP** — "Keeping master green at scale", EuroSys 2019,
  <https://doi.org/10.1145/3302424.3303970>; "Taming Google-scale continuous testing", ICSE-SEIP 2017,
  <https://doi.org/10.1109/ICSE-SEIP.2017.16>: a central service
  owns the queue and the commit; a model predicts which pending changes conflict and builds only the needed
  speculative combinations; TAP runs presubmit on affected targets, commits, and verifies postsubmit with automatic
  rollback. Solves: thousands of changes/day with sub-hour latency, no human or client process in the merge path.
- **Plumbing patterns.** GitHub REST best practices: "use webhooks instead of polling" and conditional requests (a
  `304` with `If-None-Match` does not count against the primary limit) —
  <https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api>; failed webhook deliveries
  are not retried automatically, they are redelivered through the API within 3 days —
  <https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries>; rate limits per identity
  (user 5,000/h; a GitHub App installation has its own budget, ≥ 5,000/h scaling to 12,500, 15,000/h on Enterprise
  Cloud) — <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api>; transactional outbox and
  idempotent consumer — <https://microservices.io/patterns/data/transactional-outbox.html>,
  <https://microservices.io/patterns/communication-style/idempotent-consumer.html>; git's built-in `union` merge driver
  for line-append files ("use with care", order not kept) — <https://git-scm.com/docs/gitattributes#_built_in_merge_drivers>;
  news fragments, one file per entry assembled later — <https://towncrier.readthedocs.io/>.

## Estado da arte
- **Standard:** the forge's own merge queue (GitHub merge queue, GitLab merge trains). Requires branch protection with
  required status checks, a CI that reports a check or commit status on the `merge_group` branch, and a webhook (or
  Actions) consumer to run that CI. Latency = one CI run on the queue branch; the merge itself is the forge's, seconds
  after the last check.
- **Most advanced:** a central gating service (Zuul, SubmitQueue, TAP, Aviator parallel mode) that receives forge
  events, keeps the queue in its own store, runs speculative combinations only for changes that can interact
  (affected targets/conflict prediction), merges under its own identity, and verifies post-merge with automatic revert.
  Requires: an always-on process with an inbound endpoint, its own credential and quota, a durable queue (outbox +
  idempotent handlers keyed by event id), a reconciliation sweep for lost events, and a build graph precise enough to
  say "these two changes cannot interact".
- Both treat the client (the author, or here the AI session) as text in, text out: it pushes a head and reads verdicts;
  it never merges the base, runs the queue or resolves a mechanical conflict.

### Distance from today's train
| Dimension | Today (29/10, intake) | Reference | Distance |
|---|---|---|---|
| Trigger | a session loops `scripts/train run` ~1/min; `train.trigger_mode` `emit_only` | `merge_group`/webhook wakes the consumer (GitHub queue, Zuul, bors) | the verdict wakes nobody: one poll interval minimum, unbounded when the loop stalls |
| Queue state | rebuilt per process by full replay, `1 + 2 × open PRs` (≥ 135 reads at 67 PRs) | durable queue in the service; webhook updates one entry | O(open PRs) per iteration vs O(1) per event |
| Identity / quota | one user token (5,000/h) shared by train, gates and sessions | own installation token per service (≥ 5,000/h each) | no isolation: any caller can stall the train |
| Executor | an AI cloud session holds the role; a restart (19:40Z) pauses it, an exit stalls it | a service process; clients only push and read | the merge path depends on a session staying alive |
| Admission on a moved tip | strict verdict only if tip unchanged; else resync + cold re-verdict, or tier 2 (all 5 merges of 29/10) | speculative combinations (Zuul, SubmitQueue), merge queue branch | shard admit exists but is `shadow` |
| Mechanical conflicts | `merge=regenerate` for 2 generated files; `DECISIONS.md` goes back to an AI session | deterministic drivers / fragments; the service resolves | every merge can cost an AI session elsewhere |
| Lost events | the loop itself is the only recovery | redelivery + reconciliation sweep with `304`s | safety net exists but is the main path and costs full quota |
| Observability | no event for quota exhaustion; latency readable from `gate.passed` → `pr.merged` | queue SLOs per entry | half of the success metric is not recorded yet |

## Encaixe em nós
- **Copy directly:**
  - the trigger shape of `merge_group`: the green verdict *is* the enqueue, and the consumer is woken by it;
  - idempotent consumer keyed by the event id (`pr.ready` already has a natural key repo/pr/sha, EVENTS.md);
  - conditional requests (`ETag`/`If-None-Match`) for the safety-net sweep, so an idle sweep costs ~0 quota;
  - one identity per role, already the 10x row of EVENTS.md "Scale".
- **Adapt:**
  - Zuul/SubmitQueue speculation → our `train.shard_admit` (P-54, units+dependents keys) is the same idea at unit
    granularity; it is in `shadow` today;
  - the bors staging branch → our tier-2 combined head; keep it only as the fallback, not the main path;
  - TAP postsubmit + revert → the battery on the tip and `git revert -m 1` of `s-` merges (train.md);
  - `union`/news fragments for append-only files such as `docs/domain/DECISIONS.md`, owned jointly with DOCS-API (#811),
    since "one file per decision" already failed once.
- **Does not fit:**
  - the GitHub merge queue as is: it needs required checks reported as statuses/check-runs, and the cloud proxy refuses
    those writes (train.md), there are no GitHub Actions or third-party CI here (AGENTS.md), and the destination forge
    is Cursor Origin (EVENTS.md), so a GitHub-only feature would be a dead end;
  - Mergify/Aviator as hosted services: third-party CI is out, and they would re-implement admission rules we already
    hold (D-075, D-079);
  - a full build-graph conflict predictor (SubmitQueue): our unit manifests are the coarse version; finer is not needed
    at 67 open PRs.

## Escada de ambição
1. **Minimum useful now:** the green verdict's own producer (the `pr.ready` hook after `gate.passed`) wakes the train
   with that one PR instead of the train discovering it: an incremental admission of that head (its log, its head, the
   tip) in the order of tens of calls, and the per-minute loop becomes a slow safety-net sweep with conditional
   requests. No new host, no new identity.
2. Next: a train identity of its own (GitHub App installation token) so the train's budget is separate from gates and
   sessions; record quota exhaustion as an event so "zero stalls from quota" is measurable.
3. Then: a small always-on service that receives forge webhooks into a durable queue (outbox + idempotent handlers,
   redelivery on miss), owns base updates, re-verdicts and merges; sessions only push heads and read events.
4. State of the art: speculative admission (shard admit `on`) so a moved tip does not cost a re-verdict, a
   deterministic merge driver for append-only files, and post-merge verification with automatic revert — on the forge
   adapter that will also serve Origin.

### Success, measured
Each number comes from forge events, read over one working day with the safety-net sweep on:
- **Green verdict to merge:** `pr.merged.occurred_at − gate.passed.occurred_at` for the head the merge names
  (`pr.ready.evidence` links them). Strictly admissible PR (head contains the tip): p50 ≤ 60 s, p95 ≤ 5 min. A PR whose
  tip moved: p95 ≤ one cold re-verdict + 60 s. Baseline #808: 16m51s.
- **API calls per merge:** forge calls of the train (and of any merge service) per `pr.merged`, ≤ 20, and ~0 per hour
  with an empty queue. Baseline: ≥ 135 per iteration × ~60 iterations/h regardless of the queue. The gate already
  counts its own (`cost.rest_calls` on `gate.passed` v4: 19 on #808); the train has no equivalent count yet.
- **Zero stalls from quota:** no admissible PR waits while a rate limit is spent, counted by an event emitted on a
  primary or secondary limit refusal (none exists today; 29/10 had two, reported by hand).
- **Who merged:** share of merges triggered by the verdict event vs found by the sweep; the sweep catching > 0 proves
  the safety net works, a large share means events are being lost.
- **No AI session in the merge path:** count of `pr.conflicted` cause `textual` whose files are all append-only or
  generated: 0.
