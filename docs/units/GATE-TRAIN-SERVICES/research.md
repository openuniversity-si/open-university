# GATE-TRAIN-SERVICES — research

Stage 2 of the unit flow (D-077). Starts from the intake's real problem: verdicts and merges run only while an AI
session is alive. Complete on its own; it raises no questions for the audit.

## Quem já resolveu
- **Bors / Homu (Rust), the "not rocket science rule"** ([Graydon Hoare](https://graydon2.dreamwidth.org/1597.html),
  [bors-ng](https://bors.tech/), [homu](https://github.com/rust-lang/homu)): a bot, not a person, keeps the main branch
  always green. It reacts to forge webhooks, tests the merge result of the queue's head on a staging branch, merges
  only on green, and batches ("rollups") under load. Its state is the forge plus a small database.
- **Zuul (OpenStack)** ([gating](https://zuul-ci.org/docs/zuul/latest/gating.html)): a scheduler driven by forge
  events runs the queue *speculatively*, testing each change on top of the ones ahead of it in parallel and re-forming
  the queue on a failure; executors are disposable nodes, and the scheduler, executors and the database are separate
  services with status pages and metrics.
- **GitHub merge queue** ([docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)):
  the forge itself groups queued PRs with the base into `gh-readonly-queue/<base>/…` branches and emits `merge_group`
  for CI to judge; required checks gate the merge. Available only to organizations (public repos, or private ones on
  Enterprise Cloud) ([GA notice](https://github.blog/changelog/2023-07-12-pull-request-merge-queue-is-now-generally-available/)).
- **Hosted merge queues: Mergify, Aviator, Graphite** ([Mergify](https://docs.mergify.com/merge-queue/),
  [Aviator](https://docs.aviator.co/mergequeue), [Graphite](https://graphite.dev/docs/graphite-merge-queue)): a webhook
  control plane with batching, speculative checks and affected-target ("parallel") queues, a status dashboard and
  admin commands (pause, requeue, cancel); CI stays the customer's runners.
- **Build reuse and pipelines:** Bazel's content-addressed remote cache ([remote caching](https://bazel.build/remote/caching),
  [BuildBuddy](https://www.buildbuddy.io/docs/remote-cache)) makes a re-verification cheap on any runner; Tekton Triggers
  ([EventListener](https://tekton.dev/docs/triggers/)) is the canonical webhook → validate → filter → pipeline run chain.

## Estado da arte
- **Standard.** Forge webhooks reach a small always-on receiver that verifies the signature
  (`X-Hub-Signature-256`), answers 2xx within 10 s, and queues the work; the delivery id (`X-GitHub-Delivery`, the
  same on a redelivery) makes processing idempotent; failed deliveries are redelivered after an outage
  ([GitHub best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)).
  Runners are disposable and dispatched, one queue serializes merges, and the verdict is a check on the head.
- **Most advanced.** Zuul-style speculative gating and affected-target parallel queues (Aviator, Mergify); remote
  content-addressed caches so a runner reuses every unchanged result; a single-writer queue (an actor) with leases and
  alarms instead of polling; health and metrics by convention: liveness/readiness endpoints
  ([Kubernetes](https://kubernetes.io/docs/reference/using-api/health-checks/)), Prometheus text exposition
  ([format](https://prometheus.io/docs/instrumenting/exposition_formats/)), the four golden signals (latency, traffic,
  errors, saturation; [SRE book](https://sre.google/sre-book/monitoring-distributed-systems/)); every admin action an
  audited event; a dead-letter queue for what cannot be processed.
- **What each requires.** A receiver and a durable queue need an always-on host: Cloudflare Workers with a Durable
  Object (single-threaded actor with SQLite storage and alarms) is free with SQLite-backed objects only, 100,000 DO
  requests a day and 5 GB of storage, resetting at 00:00 UTC ([free tier](https://developers.cloudflare.com/changelog/2025-04-07-durable-objects-free-tier/),
  [limits](https://developers.cloudflare.com/durable-objects/platform/limits/)); Cloudflare Queues adds 10,000
  operations a day free with retries and a dead-letter queue ([pricing](https://developers.cloudflare.com/queues/pricing/)).
  Runners need compute: GitHub-hosted runners bill a private repository's minutes against the plan (Free: 2,000 a
  month; [billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions));
  self-hosted runners are free today (the USD 0.002/min platform fee announced for March 2026 was postponed,
  [GitHub](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/),
  [The Register](https://www.theregister.com/2025/12/17/github_charge_dev_own_hardware/)) and can live on an Oracle
  Cloud Always Free VM ([free tier](https://www.oracle.com/cloud/free/)). A workflow's `GITHUB_TOKEN` has its own
  1,000 REST requests/h per repository ([rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)).
  `workflow_dispatch`, `repository_dispatch`, `schedule`, `issue_comment` and `workflow_run` start only workflows on
  the default branch; `pull_request`, `pull_request_target` and `push` start the workflow of the ref or base itself
  ([events](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows)).
  `concurrency` groups serialize runs, keeping one pending run per group
  ([concurrency](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs)).

## Encaixe em nós
- **Copy directly:** the webhook discipline (verify, ack in 10 s, dedupe by delivery id, process asynchronously,
  dead-letter what fails); `/healthz`, `/readyz`, `/metrics` in Prometheus text and a JSON `/status`; admin actions as
  authenticated calls recorded as events; one actor (a Durable Object) as the single writer of the queue, the lease and
  the switches, with an alarm instead of a polling loop; Actions `concurrency` to serialize the train.
- **Adapt:** Bors/Zuul gating, since we already have it: the train's verdict admission (D-075, D-079), resync and
  tier-2 batch stay as they are; only their trigger and their host move out of the AI session. The content-addressed
  result cache (D-076) is per box today; on ephemeral runners it needs a persistent store (the Actions cache, or R2
  under D-073). GitHub's own events replace our polling of comments where they exist (`pull_request`, `push`,
  `issue_comment`), while the forge-events comments stay the record.
- **Does not fit:** GitHub merge queue (organization-only; this repository is a user's private one); Mergify, Aviator
  and Graphite (paid for private repositories past their free tiers, and they would replace our admission rules);
  Tekton (needs a Kubernetes cluster); Cloudflare Containers (paid) to run the gate on the control plane; Workers
  running the gate (no shell, CPU-time limits).

## Escada de ambição
0. Today: the author session runs the gate; the merge session keeps `scripts/train serve` alive (wake over git).
1. **Minimum useful step now (the plan's cheapest useful effort):** one session-independent service entry point
   (vendor-neutral contracts, status/health/metrics computed from the forge record, admin switches through the shared
   store) and runner definitions that start the gate on a push and the train on a verdict with no session; the train
   keeps its git lock and admission rules. What only the owner can do (a deploy, an App, a setting) is a listed step.
2. A control plane on Cloudflare (Worker + Durable Object): verified, deduplicated webhooks, a single-writer queue,
   lock and switches, an alarm as the safety-net sweep, `/status`, `/healthz`, `/metrics`, an admin view, and a
   dispatcher that starts runners within a minutes budget.
3. Swappable runners with a shared result cache: GitHub-hosted within the free minutes, a self-hosted runner on a
   free VM for the rest, both reusing results by content key.
4. The state of the art: speculative, shard-aware queues (P-54) and Zuul-style parallel verdicts of the queue ahead,
   with SLOs on the golden signals and no human or AI turn in the loop.
