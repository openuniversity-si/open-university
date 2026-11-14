# GATE-TRAIN-SERVICES — intake

Unit, stage 1 of the unit flow (D-077). Complete on its own; the research, the audit and the plan are separate products.

## Pedido
Daniel (CEO), chat, in five messages (English, literal excerpts):

- 29/10 23:56 BRT, top priority: "in ONE single PR, turn A Torre's Gate and Train into world-class microservices, so
  that all gate and train management is instant, automatic and manageable (observable, controllable, with
  status/health/metrics and admin controls) and NO LONGER depends on AI sessions to run." Stage 1 asks "what 'instant,
  automatic, manageable, session-independent' means as measurable targets (e.g. push -> verdict latency, green ->
  merge latency <= 60 s as in GATE-ON-PUSH, gate wall time vs the 180 s ceiling, GitHub reads per gate vs 60, uptime,
  zero manual restarts)". Stage 4 asks for "a clear split: repo + GitHub = source of truth; AI sessions only write code;
  gate and train = services triggered by webhooks with no AI in the loop", with status/health/metrics endpoints, admin
  controls (pause/resume, requeue, cancel, trigger_mode) and "structured session-independent logging/monitoring of
  every event". Known items to fold in: one shared windowed read of #548 so the page-cap stopgap can go, gate time
  278-345 s vs 180 s, 96 vs 60 GitHub reads per gate, the pre-existing `test_battery.py` failure, the Cloudflare
  webhook receiver and Durable Object queue plan.
- 29/10 23:59 BRT, infrastructure: "Control plane (brain): Cloudflare Workers free tier ... GitHub App webhook
  receiver, Durable Object queue/lock/state, status/health/metrics endpoints and a small admin view. Workers cannot run
  the gate ... Execution plane (arm): GitHub Actions hosted runners dispatched by the control plane ... design the
  runner as swappable (self-hosted runner on a free VM such as Oracle Cloud Always Free later) without touching the
  control plane."
- 30/10 00:01 BRT: "Keep everything on free tiers for now ... If something truly requires a paid tier, do not adopt
  it; record it in a D-xxx with cost, the free alternative and the trade-off."
- 30/10 00:04 BRT: "This PR must not stop for anything ... make the most pertinent decision yourself, change the code
  or rule, remove the obstacle and keep going."
- 30/10 01:07 BRT: #804 and #809 merged, #810 red on GX-23 only; the first serial commit is GX-23's deterministic fix;
  the self-host leg's cause was lost to its last line; `train.trigger_mode` is `wake` and `scripts/train serve` runs in
  the merge session.

## Intenção
Daniel wants to stop being, and stop paying for, the scheduler of his own delivery flow. Today a verdict exists only
because an AI session ran the gate, and a merge happens only while an AI session keeps the train alive; when a session
stalls, expires or runs out of weekly quota, the flow stops and someone has to notice and wake it. The intent is the
split every mature delivery system has: the forge holds the truth, a small always-on control plane reacts to its
events, disposable runners do the heavy work, and people (or AI sessions) only change code. "World-class" here means
the same properties as GitHub's merge queue, Zuul or Bors (event-driven, serialized, idempotent, observable), built
from free parts.

## Contexto
State on 30/10/2026 01:18 BRT, base `mod/roadmap-integration` at `e45624c7` (#809):

- **Who runs the gate.** `scripts/gate-dev --pr N` runs in the author's Claude Code session after it pushes; nothing
  runs it on a push. The verdict is a forge event (`gate.passed`/`gate.failed` v4 on the PR's comments), then
  `pr.ready`, which fast-forwards `train/wake` (`train.trigger_mode` `wake`, GATE-ON-PUSH).
- **Who runs the train.** One Claude Code cloud session (the merge session) keeps `scripts/train serve` in its
  background: it waits on `train/wake` with `git ls-remote`, runs `scripts/train run --pr N` per wake and a sweep, and
  exits after `train.serve_max_s` (below the 2 h background limit, P-55) so the session restarts it. A stalled,
  expired or quota-limited session stops every merge.
- **Measured latency (forge events).** #809: `gate.passed` 03:19:48Z, `pr.merged` 03:38:36Z, 18 min 48 s; #804:
  02:49:02Z to 03:13:24Z, 24 min 22 s. Both merged through tier-2 batches (8 min 48 s and 4 min 41 s of tier 2), not on
  their verdict. #804 took six green verdicts and four `pr.conflicted` round trips over 7 h 25 min before it merged.
- **Measured cost.** The train's last run spent 130 REST calls (`budget.measured`, 30/10 04:07:25Z) against
  `train.rest_calls_per_run_max` 20. This PR's first gate (`4cd47abe`, 30/10 04:31Z) made 204 GitHub reads against the
  gate's own bound of 60 (Daniel measured 96 on earlier gates); its wall time is in the audit. Daniel measured gate
  wall times of 278–345 s against the 180 s ceiling (D-064 (f)).
- **The repository channel.** #548 holds 2,062 comments (21 pages of 100); `forge-events.github_max_pages` went from
  20 to 200 as a stopgap (D-072 incident of 30/10), so a windowed read now reads the whole channel. 106 of the newest
  ~160 events are `slo.breached`.
- **Red without a code cause.** #810's train tier 2 went red only on GX-23 (`gate-result-cache.test.sh`, a flake);
  the train's self-host leg exited 1 on #804, #809 and #810 with the cause lost (only the last output line was kept);
  this PR's first gate went red on `gate-isolation.test.sh` (expectations stale since #804 changed
  `gate.slots_per_vcpu`); `test_battery.py` fails outside the gate because it asserts the live shared store's
  `battery.enabled`. Fixed in this PR's first three commits (D-082, D-083).
- **Platform constraints measured from this session.** The egress proxy refuses GraphQL, the Actions REST paths
  (`actions/permissions`: 403 "Access to this GitHub Actions path is not permitted through this proxy"), REST git-data,
  `statuses` and `check-runs` writes; it permits REST reads, issue comments, `PUT pulls/<n>/merge` and ref
  create/fast-forward over git. `developers.cloudflare.com` does not resolve here, so this session cannot reach
  Cloudflare. The repository is private (REST `visibility: private`), so GitHub Actions minutes count against the
  owner's free quota. The `rate_limit` of this session's token is 15,000/h; Daniel's user token is 5,000/h.
- **Rules in the way.** AGENTS.md says "No GitHub Actions or third-party CI" and the gate's stage `no GitHub Actions
  workflows` refuses any `.github/workflows/*` file; Daniel's 23:59 message makes GitHub Actions the execution plane.
- **Prior art in the repo.** GATE-ON-PUSH (#812, #813) named this unit as its rung 3 ("a webhook receiver on an
  always-on host with a durable queue ... and its own App identity"); [EVENTS.md](../../process/EVENTS.md) names the
  10x transport as "webhook receiver with a queue" and "one identity per role"; #810 (D-081, open) asks the audit for
  a chain of whys to a structural root and the plan for weighed alternatives.

## Regras
- D-077 (unit flow, Padrão v6 intake-and-research); #810's intent (D-081, open: root-cause chain, weighed
  alternatives); D-082 (this unit's STEP 0); D-083 (draft heads judged on delivered items).
- D-054 (production frozen; no deploy, promote, migration or data rewrite), D-065 (events, never a clock; the train is
  the only merger; push every commit), D-069 (engineering standard: registry values, no literals, switches in the
  shared store, recovery path), D-072 (a blocking event gets an evaluation; a loosening carries it), D-025/D-022
  (commit plan, one commit per push, a gate change cites a D-NNN), D-055 (no review step).
- Admission: D-075, D-076, D-078, D-079, D-080; premises P-18 (the train is the only merger), P-46 (the pinned gate
  judges), P-53, P-55 (a background process lives up to 2 h), P-56 (content-keyed results).
- Daniel's constraints for this unit: free tiers only (a paid need becomes a D-xxx with cost, free alternative and
  trade-off); no new token, App or webhook that affects anyone else or costs anything; no secret in the repo, a
  commit, a comment or the chat; never `OU_CONFIG_STORE=file` for the shared switches; save REST quota (check
  `rate_limit` before each gate or train run, sleep under 300 remaining, never exit on quota or network errors);
  `scripts/train run` only as the last step, to merge this PR through the train.

## Problema real
Every verdict and every merge needs an AI session that is alive, awake and within its quota: the gate runs only when
the author session runs it and the train only while one Claude Code session keeps `scripts/train serve` alive, so the
flow's latency, uptime and cost are those of the sessions, and nobody can see or steer it without opening one.

Resolved when, measured from forge events and the services' own metrics over a working day:
- **T1 automatic:** 0 AI-session actions on the path push → verdict → merge (every gate and train run is started by
  an event, counted by its trigger); 0 manual restarts.
- **T2 push → verdict:** p50 ≤ the gate's wall time + 60 s from the push, with no session; a lost trigger is caught
  by a sweep within 15 min.
- **T3 green → merged:** p50 ≤ 60 s for a strictly admissible PR, p95 ≤ 5 min (GATE-ON-PUSH's targets; today 18–24 min).
- **T4 gate wall time:** p50 ≤ 180 s (D-064 (f)); today 278–345 s.
- **T5 GitHub reads:** ≤ 60 per gate (the gate's own bound; today 96–204) and ≤ 20 REST calls per train run (today 130).
- **T6 manageable:** one status endpoint answers queue, lock, pause state, trigger mode, last events and runner health;
  `/healthz` and `/metrics` answer; pause/resume, requeue, cancel and trigger mode are each one authenticated call that
  is itself recorded as an event; every event the services receive or emit is logged outside any session.
- **T7 uptime and loss:** the control plane answers its health check ≥ 99.9 % of the day; 0 events lost (every forge
  delivery is acknowledged, deduplicated by its delivery id, retried, or visible as dead-lettered).
- **T8 cost:** USD 0: every resource within a free tier, with the Actions minutes per gate and per day projected
  against the private repository's free quota in a D-xxx.

## Lacunas
Daniel asked not to be asked; each gap is decided by the session and recorded, and what only Daniel can do is listed
as an exact step:
- **Cloudflare access.** This session cannot reach Cloudflare (DNS refused) and holds no Cloudflare credential, so it
  cannot deploy the Worker or create its Durable Object; `wrangler` OAuth exists only on Daniel's box. Depends on
  Daniel: one `wrangler deploy` from the repository and the Worker's secrets.
- **The webhook identity.** A GitHub App (or a repository webhook) pointing at the Worker can only be created by the
  repository owner in GitHub's settings. Depends on Daniel.
- **Workflow files.** Whether this session's git credential may push `.github/workflows/*` (GitHub refuses a token
  without the `workflows` permission) is unknown until a push tries it.
- **The owner's plan.** Free (2,000 Actions minutes a month on private repositories) or Pro (3,000) is not readable
  from here; the projection assumes Free.
- **Actions secrets.** Whether the runner needs more than the workflow's own `GITHUB_TOKEN` (1,000 requests/h per
  repository) is for the audit; any repository secret is entered by Daniel.
