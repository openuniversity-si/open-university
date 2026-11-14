# ADR-41 — The gate and the train are services; AI sessions only write code

Date: 2026-10-30 · Status: accepted (Daniel, 29/10 23:56–30/10 01:07 BRT; D-086) · Amends ADR-24 · Unit:
[GATE-TRAIN-SERVICES](../units/GATE-TRAIN-SERVICES/plan.md)

## Context
Every verdict needed the author's AI session to run `scripts/gate-dev`, and every merge needed one Claude Code session
to keep `scripts/train serve` alive (2 h background limit, stalls, weekly quotas, manual restarts). State was spread
over PR comments, #548, git refs and container-local files, so nobody could see or steer the flow without opening a
session ([audit](../units/GATE-TRAIN-SERVICES/audit.md), roots R1–R3). ADR-24 removed GitHub Actions on 14/10 when the
free minutes ran out and merging stopped; nothing took over the *trigger*.

## Decision
Three planes, each replaceable without the others:

1. **Source of truth: the repository and GitHub.** Code, PRs, the forge-events comments (#548 and each PR's channel,
   D-065), `train/lock` and `train/wake`. Nothing else is authoritative; every service can be rebuilt from it.
2. **Control plane: one always-on owner of the operational state.** A Cloudflare Worker (`forge-webhook`) with one
   Durable Object as the single writer of the queue, the leases, the switches and the delivery log: verified webhooks
   (`X-Hub-Signature-256`), deduplicated by `X-GitHub-Delivery`, answered within 10 s; `/healthz`, `/readyz`,
   `/status`, `/metrics` (Prometheus text), `/events`, an admin view, and authenticated admin calls (pause, resume,
   requeue, cancel, transport), each recorded; an alarm as the safety-net sweep. Free tier only (SQLite-backed Durable
   Objects). Its API is `contracts/service/api.v1.json`; any implementation that answers it is a control plane.
3. **Execution plane: Tower runners.** `scripts/service runner` takes jobs (`contracts/service/job.v2.json`: a gate of
   one head, a train run for one woken PR, a sweep), runs `scripts/gate-dev` or `scripts/train run` exactly as a session
   would (the pin, P-46; the train's git lock, P-18), and reports a result (`contracts/service/result.v1.json`). Two
   transports, one job model: **git** (watch `refs/pull/*/head`, the base and `train/wake` with `git ls-remote`: zero
   REST, no deploy) and **control** (claim from the control plane). A runner runs wherever there is free compute: the
   box today, an Oracle Cloud Always Free VM next, a GitHub-hosted Actions job within a minutes budget, or, as the last
   fallback, a Claude Code session. No runner kind is required for merging.

AI sessions write code and push. They never host the gate or the train as a requirement.

Read paths that need no control plane: `scripts/service status|health|metrics` answer from git refs, the shared window
of the repository channel (D-085) and the local runner's state file. Switches stay in the shared store (D-069 item 5):
`service.paused`, `service.transport`, and the train's own.

**ADR-24 amended.** "No GitHub Actions, ever" becomes "never *depend* on GitHub Actions": a hosted runner is one
optional runner kind, its workflow staged under `services/` and allowlisted by name, its minutes budgeted (D-087); the
gate still runs the same `scripts/gate-local` everywhere, and merging never waits on an Actions minute.

## Consequences
- A runner on any free machine removes the AI session from the gate → verdict → merge path (intake T1); the control
  plane adds push-based dispatch, a public status and admin calls once deployed (Daniel's one-time steps, D-088).
- Hosted Actions minutes cannot carry the whole flow for free (audit 11): the default execution is free compute.
- The service's own log (the runner's JSONL, the control plane's delivery log) is not the record; the forge events are.
