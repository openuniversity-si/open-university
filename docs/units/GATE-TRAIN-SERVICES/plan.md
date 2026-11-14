# GATE-TRAIN-SERVICES — plan

Stage 4 of the unit flow (D-077; #810's intent: weighed alternatives per root). Reads [audit.md](audit.md)
(`## Causas raiz` R1–R5) and [research.md](research.md) (`## Escada de ambição`). It decides; the execution is the next
commits of this same PR (#814), one commit per push, each gated.

Goal: a gate and a train that run, are observed and are steered with no AI session in the loop, from free parts, with
today's session path kept as a fallback runner rather than a requirement.

## Alternativas

Criteria: resolve a raiz? (removes the cause, or only today's symptom), custo, reversibilidade, risco, degrau (rung of
research.md's ladder).

### R1 No execution plane outside AI sessions
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 GitHub-hosted Actions run every gate and train (Daniel's 23:59 target) | redesenho | sim, while minutes last | 100–200 gates/day × 5–12 min = 7–36× the 2,000 free minutes (audit 11) | a workflow file | the 14/10 failure (ADR-24): minutes run out and merging stops | 3 |
| A2 A vendor-neutral **Tower runner** (`scripts/service runner`): one process on any machine with the toolchain takes gate and train jobs, runs `gate-dev`/`train run` and reports; free compute first (Daniel's box today, an Oracle Cloud Always Free VM next), hosted Actions as one optional runner kind within a minutes budget, a Claude session as the last fallback | corrige a classe | sim: compute is anyone's; no session, vendor or quota is required | ~4 h + tests | the runner is additive; stop it and sessions work as today | a runner host must be started once by Daniel (no credential reaches it from here) | 1–3 |
| A3 Keep sessions, add a watchdog that restarts them | remendo | não: still AI sessions, weekly limits | 1 h | total | stalls remain | 0 |

### R2 The event's consumer is bound to its host
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Move `train serve` as is to another machine | remendo | não: trains only; gates still need a session | 30 min | total | — | 1 |
| A2 One runner protocol (job, claim, heartbeat, result: `contracts/service/runner-protocol.v1.json`) with two transports: **git** (watch `refs/pull/*/head`, the base and `train/wake` with `git ls-remote`, zero REST, no new infrastructure) and **control** (claim from the control plane over HTTPS); the runner picks control when reachable, else git | corrige a classe | sim: any host consumes the same jobs; the transport is swappable | ~3 h + tests | per runner: `service.transport` | two transports to keep equal (one job model, tested together) | 1–2 |
| A3 Webhooks straight to the runner host | redesenho | sim | an inbound port on the host | medium | exposes the box | 2 |

### R3 No component owns the operational state
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 A dashboard script over #548 | remendo | não: recomputes from the log, no control | 1 h | total | — | 0 |
| A2 The **control plane**: a Cloudflare Worker (`forge-webhook`) with one Durable Object as single writer of the queue, leases, switches and the delivery log; verified, deduplicated webhooks (`X-Hub-Signature-256`, `X-GitHub-Delivery`); `/healthz`, `/readyz`, `/status`, `/metrics` (Prometheus text), `/events`, an admin view and authenticated admin calls (pause/resume, requeue, cancel, trigger mode), each recorded; an alarm as the safety-net sweep. Locally, `scripts/service status|health|metrics` give the same answers from git, the forge window and the runner's state when no control plane is deployed | corrige a classe | sim: one owner of state, two read paths | ~4 h + tests, free tier | the Worker is inert until deployed; the CLI works without it | deploy and secrets are Daniel's (Cloudflare is unreachable from here) | 2 |
| A3 A hosted merge queue (Mergify/Aviator) | redesenho | sim | paid for a private repo; replaces our admission rules | low | rules drift | 3 |

### R4 An append-only log without a shared reader
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Keep `github_max_pages` 200 | remendo | não: 21+ calls a read, ~200 a gate | 0 | — | grows with #548 | 0 |
| A2 One shared windowed read (`ForgeEvents.read_recent`, `forge-events.window_pages`) for every module that read the whole channel, plus a machine-wide cache of the channel's full pages (immutable: a forge-events comment is never edited; a deletion is detected at the page boundary); `github_max_pages` back to 20 | corrige a classe | sim: a read costs the issue and the newest page | ~2 h + tests | `forge-events.github_page_cache` off | state older than the window is not read: quarantines and defects past it stay as they are (the safe direction, as GATE-ON-PUSH found) | 1 |
| A3 The control plane indexes events from webhooks and serves them | redesenho | sim | rides R3 A2 | medium | needs the deploy | 2 |

### R5 Tests and keys bound to mutable ambient state
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Fix each instance (commits 1–3: D-082 and the base defects) | remendo | não: the next ambient read recurs | in this unit | total | another flaky test | 0 |
| A2 Enforce D-069 item 12's hermetic-test rule at the gate (no live store, attestation or registry literal in a unit test) | corrige a classe | sim | a separate unit | total | false refusals while tuned | 1 |

## Escolha
- R1 → A2 with A1 as one runner kind: research.md's "strictly better free option". It honours Daniel's control plane and
  arm split, keeps hosted Actions within its free minutes, and never lets merging depend on Actions minutes again
  (ADR-24's failure). Recorded in D-086, which amends ADR-24.
- R2 → A2: the git transport needs no deploy, so a runner works the day it starts; the control transport is the upgrade.
- R3 → A2: the Worker and Durable Object Daniel named, plus the local CLI that answers the same questions without it.
- R4 → A2, closing the D-072 stopgap (D-085).
- R5 → A1: out of this unit's scope; the class fix is its own unit. Follow-up: D-069 item 12 hermetic-test rule enforced at the gate.

## Architecture (ADR-41)
```
GitHub (source of truth: code, PRs, #548 and PR event comments, train/lock, train/wake)
  │ webhooks (push, pull_request, issue_comment, workflow_run)        │ git ls-remote (zero REST)
  ▼                                                                    ▼
Control plane: Worker + Durable Object ── claim/heartbeat/result ── Tower runner(s): box, free VM, Actions, (session)
  /webhook /healthz /readyz /status /metrics /events /admin/*          gate job → scripts/gate-dev --pr N
  queue · leases · switches · delivery log · alarm sweep               train job → scripts/train run [--pr N]
                                                                       state file · JSONL log · local /healthz /status /metrics
AI sessions: write code and push. Nothing else.
```
- Contracts, versioned and vendor-neutral: `contracts/service/runner-protocol.v1.json` (job, claim, result),
  `contracts/service/control-plane.v1.json` (endpoints and their bodies). The forge-events contracts are unchanged: the
  gate and the train keep emitting `gate.*`, `pr.ready`, `train.*` and `pr.merged` as today.
- Switches stay in the shared store (D-069 item 5): `service.paused`, `service.transport`; the train's own switches are
  unchanged. Requeue and cancel go to the control plane, or, without it, to a `service.control_ref` git log the runner
  reads (zero REST, like the wake).

## Commits
After this plan, one commit per push, each gated green on its exact head:

C7. **One shared read of the repository channel (R4).** `ForgeEvents.read_recent(repo, pr=None, kinds=None)` over
   `forge-events.window_pages`; the GitHub adapter's window uses it and caches full pages machine-wide
   (`forge-events.github_page_cache`, under the ETag cache root); `defects`, `defect_detect`, `slo`, `program`,
   `plan_triage`, `quarantine` (list), `battery`, `gate_flake` and `config`/`quarantine`/`train` windows read through
   it; `forge-events.github_max_pages` 200 → 20 and the D-072 incident's end criterion met (D-085). Files:
   `scripts/lib/forge_events.py`, `scripts/lib/forge_github.py`, the nine readers, `config/registry/forge-events.json`,
   generated types, `docs/process/incidents/2026-10-30-repository-channel-page-cap.md`, tests in
   `test_forge_events*.py`/`test_forge_github*.py` and the readers' tests.
C8. **Service contracts, status, health and metrics (R3, CLI half).** `contracts/service/*.v1.json`, ADR-41,
   `scripts/service status|health|metrics [--json]` from git refs (lock, wake), the forge window and the runner's state
   file; Prometheus text metrics (verdict and merge counts, green → merged and push → verdict latencies, gate wall time,
   reads per gate, train REST per run, queue depth, lock age); D-086. Files: `scripts/service`,
   `scripts/lib/service_status.py`, `config/registry/service.json`, a unit manifest, tests.
C9. **The Tower runner (R1, R2).** `scripts/service runner [--once] [--transport git|control]`: the git transport, the
   job model and dedupe, the executor (`gate-dev`, `train run` in a base-tip checkout, P-46), the state file, the JSONL
   log, an optional localhost HTTP server; admin: `scripts/service pause|resume` (shared store), `requeue|cancel`
   (control ref or control plane); `docs/operations/services.md` (runbook). Files: `scripts/lib/service_runner.py`,
   `scripts/lib/service_jobs.py`, `config/registry/service.json`, tests.
C10. **The control plane (R3, R2 control transport).** `services/control-plane/` (Worker, Durable Object, `wrangler.toml`
   for `forge-webhook` on account `24f3bba6…`, SQLite-backed class as the free plan requires), its node tests run by
   `scripts/tests/control-plane.test.sh`; the runner's control transport. Deploy is Daniel's (D-088).
C11. **Actions as one runner kind (R1 A1, budgeted).** A staged workflow `services/runner/github/tower-runner.yml` (not
    under `.github/workflows`: the pinned gate and `.claude/settings.json` refuse that path, and sessions never write it);
    the gate's `no GitHub Actions workflows` stage and its vitest guard accept only the workflows listed in
    `gate.allowed_workflows` (ADR-24 amended by D-086); D-087 with the minutes projection.
C12. **Retro and the final report** (pt-BR) on #548 and in the PR body; then the PR is marked ready, gated, and merged by
    the train.

C1–C5 are this PR's commits before this plan (plan items 1–5) and C6 is this plan (item 5). C7 ticks plan item 6, C8–C11 item 7 (the services), C12 item 8.

## Premises
Premises: P-18, P-46, P-55, P-56

- P-18 (the train is the only merger): **CRITICAL** — the runner only runs `scripts/train run`; the train keeps its git
  lock, so two runners never merge at once.
- P-46 (the pinned gate judges): kept; the runner runs `gate-dev`, which pins, and runs the train from a base-tip
  checkout.
- P-55 (a session's background process lives up to 2 h): no longer on the merge path once a non-session runner runs.
- Assumption to register at execution: an event comment on a channel is never edited after it is posted, so a full page
  of the channel can be cached by position (blast radius: a stale event until the cache is dropped;
  `forge-events.github_page_cache` off is the rollback).

## Tests
- C7: windowed reads cost the issue plus the newest page on a warm cache; a deleted comment invalidates the cache; every
  former whole-channel reader reads the window; the cap of 20 holds on a 21-page channel.
- C8: status, health and metrics from fixtures of refs, events and a state file; the metrics text parses as Prometheus.
- C9: the git transport turns a new PR head into one gate job and a wake into one train job, never twice; paused claims
  nothing; the executor records outcome, duration and the verdict event id; requeue and cancel through the control ref.
- C10: `node --test`: signature check, dedupe by delivery id, queue and lease, claim and result, pause, metrics text, the
  alarm sweep; a runner's control transport against a fake control plane.
- C11: the stage accepts an allowlisted workflow and refuses any other; the guard test agrees.
- Final gate on the exact head of each commit: `scripts/gate-dev --pr 814`.

## Base defects expected
- #810 (D-081) lands: merge the base, keep both sides of `DECISIONS.md` in order, regenerate.
- The train retries this draft after each green head (audit 12): harmless.

## Daniel's one-time steps (recorded in D-088)
1. On the box (or a free VM): `scripts/service runner --install` starts the runner as a user service (git transport).
2. Cloudflare: `cd services/control-plane && npx wrangler deploy`, then `wrangler secret put` for
   `GITHUB_WEBHOOK_SECRET`, `ADMIN_TOKEN`, `RUNNER_TOKEN` and `GITHUB_TOKEN`.
3. GitHub: a repository webhook (or App) to `https://forge-webhook.example.workers.dev/webhook` with the same
   secret; `scripts/config set service.transport control --reason ...` once `/readyz` answers.
4. Optional: an Oracle Cloud Always Free VM as a second runner; the staged workflow installed for hosted runs.

## Cheapest useful effort
Action: the shared channel read, the service CLI (status, health, metrics, admin), the Tower runner with its git transport, the control plane Worker and Durable Object, Actions as a budgeted runner kind, each gated, then the retro
Cost: about 6 hours of session time over six commits, one gate per commit (~5 min, ~30 reads after commit 6), USD 0
Requirement: Daniel, who wants gate and train management instant, automatic and manageable with no AI session in the loop (29/10 23:56 BRT, top priority)
Cheaper rejected: hosted Actions for every run (7-36x the free minutes, the 14/10 failure); moving `train serve` to another host (gates still need sessions); a dashboard over #548 (no owner of state, no control)
