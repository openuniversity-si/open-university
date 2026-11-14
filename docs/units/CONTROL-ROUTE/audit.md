# CONTROL-ROUTE — audit

Unit: the control plane becomes the only execution route; the git transport and `train/wake` as a wake source are deleted.
Base: `mod/roadmap-integration` @ `fab6e204d`. Branch: `mod/control-route`. PR #1083. Deadline: 02/11 13:40 BRT.

## Entradas
- [intake.md](intake.md): one job channel, loud failure, a meter that tells the truth.
- [research.md](research.md): agents refuse to start without their token and never switch queue; the queue view is the job store.

## Findings

F1. **The git transport is always built and the control transport is optional on two conditions.**
`scripts/lib/service_runner.py:459-462`: `transport = GitTransport(...)`; only `if config.shared('service.transport') ==
'control' and token:` wraps it in `ControlTransport(..., transport)`. A missing `OU_RUNNER_TOKEN` with
`service.transport control` silently stays on git; nothing logs or reports it.

F2. **The control transport falls back to git on any error.** `service_runner.py:222-226`: an `OSError` (network, 5xx,
401) with no job claimed sets `state['transport'] = 'git (control plane: …)'` and returns `self.fallback.poll(state)`.
`scripts/tests/test_service_control.py:98-109` pin that fallback as wanted behaviour
(`test_a_control_plane_that_does_not_answer_is_a_git_poll`, `test_a_refused_token_is_a_git_poll_too`).

F3. **The registry keeps git as the default and documents the fallback.** `config/registry/service/service.transport.json`:
`default "git"`, enum `git|control`, "falls back to git"; `service.runner_token_env.json`: "Without it, or with
service.transport git, a runner uses the git transport." The state file is stamped `transport=GitTransport.label` (`:70`).

F4. **`train/wake` reaches the runner only through `GitTransport.poll`** (`:141-159`), and the admin channel
`service.control_ref` (requeue/cancel) likewise (`:160-163`, `:171-187`); `scripts/lib/service.py:39-42,68-72` is its only
writer. Deleting `GitTransport` leaves `scripts/service requeue|cancel` writing a ref no runner reads: the control plane's
`POST /v1/admin` (`services/control-plane/src/core.js:782-800`, actions pause/resume/requeue/cancel) is the admin route.

F5. **The control plane does not need `train/wake` to wake the train.** `core.js:85-96` (`jobsOfEnvelopes`): a `pr.ready`
posted to `POST /v1/events` (the engine journal) is a train job of its PR and head; `core.js:122-123` also turns a push to
`train/wake` into one (the Worker is out of scope, CONTROL-STORE / its owner). Other `train/wake` consumers outside the
runner, measured with `rg -n "wake_ref|train/wake" scripts services`: `scripts/lib/train_serve.py:125` (`scripts/train
serve`, the train-role session's consumer), `services/runner/github/tower-runner.yml:15` (staged, off), the producer
`scripts/lib/train_trigger.py:51-53`. They are outside this unit's files and are listed in the PR body.

F6. **Git-side helpers the runner still genuinely needs (measured, not transports).** (a) `remote_heads`/`superseded_job`
(`:92-120`, D-141): one `git ls-remote refs/pull/*/head` before spending a gate on a claimed job, because the control plane
queues one job per pushed head (1,058 queued, PR 1058 21 times) and has no supersession yet (CONTROL-STORE). (b)
`train_serve.refresh` (`:260`, D-150): the checkout's fast-forward before each job. (c) the train's own merge and
`train/lock` (`train_git.py`): the merge mechanism, not a job channel. None of them produces a job.

F7. **The meter's queue is the wake log, never the forge.** `scripts/lib/service_status.py:132-137`: every
`(pr, latest sha)` on `train/wake` not in a `pr.merged` of the window and not `landed()` is "waiting". Nothing asks whether
the PR is open. Measured before the change at 11:41 BRT (`scripts/service status --json`, real refs):

```
queue 5 [907, 910, 956, 966, 1066]   queue_depth 5   check queue: warn "5 woken PR(s) not merged; the oldest for 130053 s"
```

and the forge (`gh api repos/openuniversity-si/open-university/pulls/<n>`): 907, 910, 956, 966 are `closed merged=false` (closed
01/11 02:26, 03:19, 13:17, 13:16 UTC); 1066 is `open`. The control-plane queue (`core.js:547-564`, `GET /status` `queue`)
is never read: `status()` hard-codes `control_plane: {runners: 'unknown', jobs: 'unknown'}` (`:162-163`).

F8. **The control-plane queue is itself not a clean queue.** Brief, read 11:34 BRT: 1,058 jobs all `queued`, 780 queue
entries over 233 distinct PRs. `core.js:564` emits one entry per live job, so the meter must collapse by PR and filter by
the forge until CONTROL-STORE fixes retention and supersession.

F9. **Environment.** No `$TOWER_EVENTS_TOKEN` (diary writes fail) and the proxy refuses `*.workers.dev` (status.md B1, B2).

## Causas raiz

### R1. The runner's route is chosen by a silent conjunction with a built-in fallback
Cadeia de porquês:
1. Por que the VM never claimed a control-plane job? Because its runner rides `GitTransport` (F1): the shared store says
   `git` and no `OU_RUNNER_TOKEN` exists on the VM.
2. Por que did nobody see that the control route was not taken? Because every failure to use it (wrong setting, missing
   token, a control plane that does not answer) degrades to git without an error (F1, F2), and git delivers.
3. Por que does the code degrade? Because the control transport was introduced beside the git one as an opt-in with
   the git transport as its `fallback` constructor argument (F2), and the tests assert the fallback (F2).
4. Por que was the fallback kept after the control plane became the target? Because no rule says a migrated route must
   remove the old one in the same change; D-086 framed git as the zero-deploy default.
Classe: arquitetura/desenho
Evidência: `scripts/lib/service_runner.py:190-227,454-463`; `scripts/tests/test_service_control.py:98-109`; F3.

### R2. The meter counts a queue it reconstructs from a side log instead of the job store and the forge
Cadeia de porquês:
1. Por que did the meter show 5 PRs waiting in an empty queue? Because #907 #910 #956 #966 have a wake and no
   `pr.merged`/landed commit (F7).
2. Por que are closed PRs counted? Because the only exits from the queue are "merged" and "landed": "closed" is not an
   exit, and the forge is never asked (F7).
3. Por que is the queue rebuilt from `train/wake`? Because the meter was written when the git transport was the job
   channel; the job store (`GET /status`) was marked "unknown" rather than read (F7).
Classe: arquitetura/desenho
Evidência: `scripts/lib/service_status.py:69-78,132-137,162-163`; measurement in F7.

### R3. An admin channel whose only reader is the transport being deleted
Cadeia de porquês:
1. Por que would `scripts/service requeue|cancel` stop working? Because only `GitTransport.admin` reads
   `service.control_ref` (F4).
2. Por que is there a second admin channel? Because requeue/cancel were built for the git transport, and the control
   plane got its own `POST /v1/admin` (F4) without the CLI being moved.
3. Por que was it not moved? Because no mechanism ties a CLI command to the transport that consumes it.
Classe: mecanismo faltando
Evidência: `scripts/lib/service.py:39-42,68-72`; `core.js:782-800`.

## Distância do estado da arte
We have the standard job API (claim, heartbeat, result, cancel, leases) in the Worker and a runner that can speak it.
Missing: refusing to start without the token and the setting, one route only, and a meter that reads the job store. The
store's own defects (retention, supersession, TTL) keep us one rung below a store whose queue is true by itself.

## Base defects expected
- The control-plane job store keeps closed-PR and superseded jobs (F8): CONTROL-STORE (another session's PR).
- `scripts/train serve` and the staged Actions workflow still read `train/wake` (F5): outside this unit's files; follow-up.
- No `$TOWER_EVENTS_TOKEN`, `*.workers.dev` refused by the proxy (F9): the environment's owner (A Torre).
