# TRAIN-DEFINITIVE — audit

Measured by this session (cloud container behind the GitHub proxy), 2026-11-02 19:00–19:20 UTC, base `98cf1db5d`.
The VM is not reachable from a session; what it did is read from outside: `train/lock` (git), the control plane's
`GET /status` and `GET /events` (its own log of claims and results), and the engine journal (`/v1/events`).

## Entradas
- [intake.md](intake.md): Daniel's order, as given (10 s per VM job, either outcome frees the runner and the lock).
- [research.md](research.md): leases tied to the job's deadline, deadlines enforced outside the job, orphan recovery,
  secret consumer inventories, continuous deploy of the coordinator.

## Findings

### Time per phase, before any change

F1. **VM jobs take 9–25 s each, and gate jobs run through the bypass.** Control plane `GET /events` (19:05Z), claim →
result of the runner `the-tower-runner`: `gate:1086#2f4d163f` 9.4 s, `gate:1087#6f7cc58e` 25.3 s, `gate:1082#5194b8f6`
25.3 s, `gate:1085#8ad0053d` 13.8 s, `gate:876` 16.5 s, `gate:877` 12.9 s, `gate:878` 15.1 s; sweeps 9.9, 11.0, 13.4,
15.3, 20.3 s. The gate verdicts carry `bypass=D-151` (`scripts/config get gate.bypass` → `true`): no stage runs. Each
job's window includes `train_serve.refresh` (a `git fetch` and `merge --ff-only` of the base) because
`Executor.run` refreshes inside the job (`scripts/lib/service_runner.py:199`), then a fresh Python process.

F2. **The VM has never merged a PR.** `train/lock` since 18:00Z (`git log refs/tt/lock`): every VM take is followed by
its release 4–7 s later with no merge in between (18:58:45→18:58:51, 18:59:02→18:59:09, 18:59:34→18:59:39,
18:59:44→18:59:49, 18:59:55→19:00:02). #1082 was merged by `train@grok-bot-vm-301145804:977759` (take 18:48:41Z,
release 18:49:48Z: **67 s**), #1085 by a cloud session (18:09:11Z → 18:09:47Z: **36 s**), #1084 + #1083 by a cloud
session (17:32:22Z → 17:33:16Z: **54 s**).

F3. **The #1082 merge run, per phase** (journal `occurred_at`, repository channel, and `train/lock`): lock take
18:48:41 → `train.batch.started` 18:48:59.6 (**18.6 s**: queue read, unit map, owners, build, combined ref push, two
lock renewals at 18:48:51 and 18:49:08) → `train.batch.shards` 18:49:00.1 → `lock.lifted` (tier 2 by the regime)
18:49:05.1 (**5.0 s**) → `pr.merged` 18:49:27.3 (**22.2 s**: tip read, behind lines, REST merge) →
`train.batch.green` 18:49:33.6 (**6.3 s**: fetch, tree proof, quarantine) → `integration.advanced` 18:49:39.4
(**5.8 s**: a window read of the whole repository log) → `train.queue.empty` 18:49:45.6 (**6.3 s**: the queue read
again) → release 18:49:48 (**2.4 s**). Total 67 s; no phase is the gate.

F4. **A no-op train run costs 13 s in a session** (`cProfile` of `train.main(['run'])`, queue empty, 19:12Z): lock
take 2.9 s and release 2.7 s (each a `git fetch` + `git push`, 2.2 s per push through the proxy), queue read 2.6 s
twice (`train.py:174`, the second from `pending()` after the release), port construction 2.0 s (five ports), emits
1.1 s. 6 REST calls. The VM does the same no-op in 4–7 s of lock window (F2): its network is faster, its CPU slower.

F5. **The real gate (bypass off) on a docs-only PR takes 39–71 s in this container.** `GATE_BYPASS=0 scripts/gate-dev
--pr 1086`: head `2f4d163f` **71.0 s**, head `6d46d8fe` **38.9 s** (`.gate/records/reports/<sha>/dev-*/`, file
mtimes against the stage `started_at`). Run 2, per phase: start → first stage **13.0 s** (the attested decision
twice, 1.2 s + 1.4 s, `gate_fast.py` and again in `gate-local:108`; preflight twice; pin; worktree; live status
begin); stages **13.3 s** in parallel, of which the structure check alone is 13.2 s (the next is pr metadata, 5.7 s);
classify 1.6 s; report 0.3 s; publish **8.7 s** (verdict events, a second PR read, pr.ready, the final status
comment). Run 1 spent 36 s more between the database sweep and `stages.json`, not reproduced in run 2.

F6. **The bypassed gate takes 11 s here**, `scripts/gate-dev --pr 1086` with `gate.bypass` on (19:16Z): no stage, but
the verdict, its binding, the evidence publish and the pr.ready hook. So neither the real gate nor the bypass fits 10 s
today, here or on the VM (F1).

F7. **The structure check is 18.6 s wall and 14.5 s CPU alone** (`scripts/structure-check --base 98cf1db5 --pr 1086`);
its main process accounts for 4.65 s (3.35 s of it the 6 REST calls of `commit_check.fetch`), the other ~10 s of CPU
is in child processes.

F8. **The VM CPU is about 12.3 times slower than the container** (D-149, D-152, D-171): the session container's real
gate is the one the design trusts (D-152: the attested exact proof), and D-269 records that a VM job's wall per phase
is not measurable from any session because results carry no phase times and the VM's log stays on the VM.

### The lock and the runner

F9. **A dead owner keeps `train/lock` for the whole lease, 35 minutes.** `train.py:151`: `lock_lease_s =
train.tier2_timeout_s (1800) + train.lock_lease_margin_s (300)` = 2100 s; `forge_github.py:600` refuses another owner
while `expires > now`. At 18:18:35Z a take by pid 740296 expiring 18:53:34Z was never released (the
`systemctl --user restart` at 18:19Z killed it); the next release is the hand-written one at 18:44:32Z
(`357651ec2`, `died: process killed by a service restart at 18:19Z`). 26 minutes of no train.

F10. **Nothing releases the lock when the job is killed.** `engine_role.py:157–169` releases in `finally`, which runs
for an exception but not for SIGKILL, and not for SIGTERM (Python's default action for SIGTERM ends the process
without unwinding). The runner stops a job with `os.killpg(SIGTERM)` (`service_runner.py:241`); systemd stops it with
`KillMode=control-group` and `TimeoutStopSec=60` (`services/runner/tower-runner.service.tmpl`). The lock owner is
`train@<host>:<pid>` (`engine_role.py:81`): a restarted runner cannot name the lock its dead job held.

F11. **Two leases, sized to the longest job, guard one job.** The control plane leases a job for `LEASE_S` = 900 s
(`wrangler.toml`), the train lock for 2100 s, the runner waits `service.job_timeout_s` = 3600 s
(`service_runner.py:212`). None of them is the 10 s the order sets, and none is derived from another.

F12. **An expired lease puts the job back in the queue, silently.** `core.js:553` (`tick`) and `core.js:473` (`claim`
takes a leased job whose lease ended) re-run the job with no result, no reason and no count.

### The backlog

F13. **Leased jobs escape the TTL forever.** `expire()` (`core.js:459–466`) drops only `queued` jobs; `claim()`
(`core.js:472–473`) takes any `leased` job whose lease ended. Measured: the VM claimed `gate:876`, `gate:877`,
`gate:878`, `gate:879` at 18:57Z and published `gate.passed` and a `ready` fact for #876 and #878, PRs merged on
2026-10-31 (REST: `closed`, `merged=true`, `closed_at` 23:44Z and 23:53Z). Counters at 19:05Z: `jobs_expired_total`
780, `jobs_queued_total` 1278, `jobs_claimed_total` 1530.

F14. **A closed or merged PR keeps its queued jobs.** `jobsOf` (`core.js:108–140`) reads `pull_request` only for
`opened`, `synchronize`, `reopened`, `ready_for_review`; `closed` makes nothing. Supersession (`enqueue`, #1084)
drops older heads of the same kind and PR only when a newer head arrives.

F15. **`expire()` runs only inside a claim and the 15-minute cron** (`core.js:470`, `core.js:551`): `GET /status`
counts expired jobs as live until one of those runs.

### Deployment and secrets

F16. **Nothing deploys the control plane after a merge.** `wrangler.toml:1–3`: "Deploy (Daniel, D-088): `npx wrangler
deploy` from this directory". `rg wrangler scripts/ services/runner` finds no caller. The Worker in production predated
#1084 (supersession, TTL) until it was deployed by hand at 18:52Z (brief).

F17. **A rotated secret breaks its holder silently.** `ControlTransport.poll` (`service_runner.py:160–161`) turns a 401
into `OSError('the control plane answered the claim with 401')`, logged as `poll-failed` on the VM and retried every
15 s forever; the control plane counts nothing for a refused runner (`core.js:782`) and its health shows the runner's
last good heartbeat only. The VM's claims got 401 from 2026-11-01 00:14Z (heartbeat frozen, TRAIN-TEMP-FIX F10) until
the hand fix at ~18:15Z: ~42 h. No file says which runner holds which secret: `missingSecrets` (`core.js:630`) lists
the Worker's own three; `service.runner_token_env` names one variable on the runner side.

F18. **The unit reads its secrets from a path that may not exist, silently.** `tower-runner.service.tmpl:12`:
`EnvironmentFile=-%h/.config/the-tower/runner.env` (the `-` makes a missing file no error). The brief: the VM's file is
`~/.config/tower/runner.env` and the user `atorre`; `docs/operations/services.md:38` says `the-tower` and user `train`.

F19. **A runner name that is not a string is stored as `[object Object]`.** `core.js:786` checks `runner.name` is
truthy; `beat()` keys `runners` by it. `GET /status` 19:05Z: `{"name": {"name": "probe", "kind": "other"}, "heartbeat":
"2026-10-30T12:51:52.519Z"}` and the health check `runner [object Object]: beat 281655 s ago` (warn, forever: no runner
entry ever leaves).

## Causas raiz

### R1. The lock's life is not the job's life
Cadeia de porquês:
1. Por que a restart at 18:19Z stopped the train for 26 minutes? The killed run's lock record said `expires 18:53Z`, and
   every later run found it held (F9).
2. Por que the record outlived the process? The lease is sized to the longest run anyone imagined (tier 2 timeout +
   margin, 2100 s), not to the job that holds it, and the release lives only in a `finally` that SIGTERM and SIGKILL
   never reach (F10).
3. Por que nobody released it after the process died? The owner is `host:pid`, unknown to the restarted runner, and
   the runner keeps no record of which lock its job held (F10).
4. Por que three timeouts (900, 2100, 3600 s) instead of one? Each layer was built on its own and nothing derives them
   from a single budget (F11).
Classe: arquitetura/desenho
Evidência: `scripts/lib/train.py:151`, `scripts/lib/engine_role.py:77–81,157–169`, `scripts/lib/service_runner.py:212,241`,
`services/control-plane/wrangler.toml` (`LEASE_S`), `train/lock` `6d87e13d8` → `357651ec2`.

### R2. No job has a deadline, so no job owes an answer
Cadeia de porquês:
1. Por que VM jobs take 9–25 s and a session merge 36–67 s with no one noticing the order's 10 s? Nothing measures a job
   against a budget (F1, F2, F3).
2. Por que nothing measures it? The runner waits up to `service.job_timeout_s` (3600 s) and the result says only
   `passed`/`failed`/`error` and a log tail; it has no phase times and no sentence (F11, `service_runner.py:221–234`).
3. Por que not phase times? The result contract was written for "did it pass", and the VM's log never leaves the VM
   (F8, D-269), so the time per phase was invisible by construction.
4. Por que is a job that never ends possible at all? An expired lease re-runs it silently (F12).
Classe: mecanismo faltando
Evidência: `scripts/lib/service_runner.py:197–234`, `contracts/service/result.v1.json`, `core.js:473,553`.

### R3. The VM runs work whose cost is fixed overhead, not judgement
Cadeia de porquês:
1. Por que does even a bypassed gate take 9–25 s on the VM and 11 s here? The job is a refresh, a cold Python start,
   the verdict binding, several forge reads and writes (F1, F6).
2. Por que does a train merge take 36–67 s when no gate runs in it? Every step is its own network round trip: two lock
   pushes and two renewals, the queue read twice, a combined ref push, a whole-log window read for one counter, one POST
   per event, a REST merge (F3, F4).
3. Por que would the real gate never fit on the VM? It costs 39–71 s in a container 12.3 times faster in CPU (F5, F8),
   most of it fixed: 13 s before the first stage, a 13 s structure check (14.5 s CPU, F7), 8.7 s of publishing.
4. Por que does the VM run a gate at all? The design already says the container's real gate is the proof (D-152), but
   the runner's gate command falls through to the full gate when no proof exists (`gate_fast.py` → `normal`), so the
   VM can start a ~2000 s job (D-269's estimate).
Classe: arquitetura/desenho
Evidência: F1–F8; `scripts/lib/gate_fast.py:24–48`, `config/registry/service/service.gate_command.json`.

### R4. The queue keeps work whose subject is gone
Cadeia de porquês:
1. Por que did the VM gate PRs merged two days earlier? Their jobs were `leased` by a dead runner and came back (F13).
2. Por que did they come back? The TTL drops only `queued` jobs, and claim treats an ended lease as free (F13).
3. Por que were they not dropped when the PRs closed? The control plane ignores `pull_request closed` (F14).
4. Por que is the backlog read wrong between ticks? Expiry runs only on claim and on the cron (F15).
Classe: mecanismo faltando
Evidência: `services/control-plane/src/core.js:108–140,459–481,548–561`; counters F13.

### R5. The coordinator's code and the coordinator's deployment are two sources
Cadeia de porquês:
1. Por que did production run a Worker without #1084 for hours? Nobody deployed it after the merge (F16).
2. Por que nobody? Deploying is a hand step by one person (D-088), outside the train that merges the code.
3. Por que is it a hand step? The deploy credential was never given to a machine role, so no runner can deploy.
Classe: mecanismo faltando
Evidência: `services/control-plane/wrangler.toml:1–3`, `rg wrangler scripts services/runner` (no caller).

### R6. Secrets have no consumer inventory and auth failures have no voice
Cadeia de porquês:
1. Por que did a rotation of `RUNNER_TOKEN` stop the VM for ~42 h? Its holder (`runner.env` on the VM) was not updated
   and nothing said so (F17).
2. Por que nothing? The runner logs a 401 as a failed poll on the VM only; the control plane counts no refusal and
   keeps the last good heartbeat as "the runner" (F17, F19).
3. Por que was the holder not updated? No record says which machine holds which secret: the rotation had no list of
   consumers to update (F17).
4. Por que can a missing file go unseen? The unit's `EnvironmentFile=-` ignores a missing file, and its path differs
   from the VM's real one (F18).
Classe: mecanismo faltando
Evidência: `scripts/lib/service_runner.py:132–166`, `core.js:630,782`, `services/runner/tower-runner.service.tmpl:12`.

### R7. The control plane trusts the runner's identity shape
Cadeia de porquês:
1. Por que does health warn forever about `runner [object Object]`? A claim sent `runner.name` as an object (F19).
2. Por que was it stored? Only truthiness is checked, and no runner entry ever leaves the map.
3. Por que never leaves? No rule retires a runner that stopped beating.
Classe: bug local
Evidência: `services/control-plane/src/core.js:483–486,786`.

## Distância do estado da arte
Against research.md: we have leases but sized to the longest job and not tied to it (rung 0); no deadline enforced
outside the job and no result for a deadline (rung 0); orphan recovery absent; supersession at enqueue (rung 1 of 3 for
a queue that drops dead work); no continuous deploy of the coordinator; no consumer inventory of secrets. The gate is
built the state-of-the-art way in principle (content-addressed proofs, D-152, shared results D-195/D-210) but its
fixed cost is an order of magnitude above the budget.

## Base defects expected
From TRAIN-TEMP-FIX F12: `test_train_role.py` `RestBudget.test_the_run_publishes_its_rest_calls_against_the_budget`
fails on the base; `test_planner_role.py` raises `ForgeCompatibilityError` on the base. Owners: engine-train (lane of
the train) and the planner's lane. Not in this unit's scope.

### R10 — Installed tool links invalidate every tree proof (regra faltando)
1. A repeated real gate still ran the structure tree for 11–13 s: its log explicitly said `no cache key`.
2. The detached subject contains the judge's `.toolchain` symlink; Git reports that link as untracked.
3. The repository ignores `.toolchain/`, which matches directories but not the installed link. Tooling artifacts and
   source cleanliness therefore have different boundaries in the main, subject and pinned tool checkouts.

The gate also starts an interpreter for every progress timestamp. This is fixed orchestration cost on the small VM,
independent of how much validation work the job actually owes. Publication profiling now measures 1.427 s, rather
than the original 8.7 s; the remaining repeated structure analysis is the dominant incremental critical path.

### R11 — Compatibility work repeats per parameter read (arquitetura/desenho)
1. Nine train verdict cases made 4,840 compatibility preflights and 47,059 canonical-path resolutions.
2. Every configuration read constructs a journal port; each port resolves the same loaded stack frames again.
3. The boundary recomputes code-origin identity and expands the declarations of every consumer, although one call
   stack owns the flow being validated. Immutable identity and per-call flow validation have no separate lifetimes.

### R12 — Fixture refusals dirty the judging checkout (bug local)
1. A full script run leaves synthetic push-refusal incidents in the real checkout.
2. The hook uses code linked from the judge, and the incident destination follows that code's resolved filename.
3. The report boundary receives the result but loses the affected repository identity; code location substitutes
   for the repository that owns the event. This contaminates source state and defeats structure reuse.

### R13 — Successful policy verdicts repeat failed raw analysis (arquitetura/desenho)
1. Clean ordinary gates still run the 10.8-second tree analysis after their prior successful verdict.
2. The result store refuses raw errors, although the existing exception regime later turns those same errors into warnings.
3. Reusable immutable diagnostics and the current enforcement verdict have one storage policy. Their lifetimes differ:
   the diagnostics depend on source inputs; enforcement must be applied afresh on each invocation.

### R14 — Prose-only commits invalidate source analysis (arquitetura/desenho)
1. Publishing each measured result changes the tree and repeats every source-only check.
2. Those checks share the complete tree cache key with prose checks, despite reading different content.
3. Cache granularity follows the combined command instead of the actual input sets; independent observations have
   no reusable boundary. The tracked filename set still matters to ownership even when prose contents do not.

### R15 — Every append reads branch history before checking its trigger (arquitetura/desenho)
1. Fresh gate publication spends 7.772 seconds evaluating branch age, with ten full channel reads.
2. The port obtains history separately for every appended event before the rule tests the registered trigger types.
3. Observation is eager and per-envelope rather than conditional and per-batch. Non-trigger events consume history
   I/O and validation even though their branch-age answer cannot depend on that history.

### R16 — Pure configuration hits reconstruct their effect boundary (arquitetura/desenho)
1. A configuration lookup constructs and preflights a journal port before returning an unchanged local replay memo.
2. The memo is consulted only after store construction, although its source file identity is available without a read.
3. The effectful observation and the pure folded-value lookup have no separate lifetimes; repeated hits redo boundary
   construction and serialize the same forge configuration fingerprint. The log identity also omits ctime/device.

### R17 — Parameter fragments are judged as registry owners (bug local)
1. A compatibility stage launches 1,066 git-show reads; the fresh profile spends 4.208 seconds obtaining base files.
2. Recursive listing includes split parameter fragments, even though the registry reader loads generated owner
   documents directly under config/registry. An object parameter's nested properties are mistaken for registry keys.
3. Compatibility traversal follows storage layout rather than the registry's actual document boundary.

### R18 — Prewarming reorders an already ordered syntax walk (bug local)
1. Cold source prewarming requests every AST node and merges all typed indexes.
2. Those indexes were just built from the canonical breadth-first walk, whose order is already the required result.
3. General filtered-selection machinery is reused for an unfiltered traversal without recognizing the identity case.

### R19 — Cache-key arguments serialize independent stage launch (bug local)
1. Metadata begins roughly a second after other independent prerequisites, and classification starts later too.
2. Shell command substitution computes two whole-input hashes before launch backgrounds each cached stage.
3. The graph expresses independence, but argument evaluation happens outside its task boundary.

### R20 — Proof and result keys observe the toolchain twice (arquitetura/desenho)
1. Preparation starts separate Python processes that attest the installed toolchain for proof binding and result keys.
2. Their in-process attestation memo cannot cross that process boundary.
3. Two representations of the same run's toolchain observation have separate observation lifetimes, adding fixed
   work and permitting them to disagree if an installation changes between the probes.

### R21 — Immutable key/classification phases re-stat the registry per parameter (bug local)
1. Full-stage timing still spends 4.200 seconds judging already-validated script keys under parallel load.
2. Every key parameter and cache lookup reopens a registry-read scope, observing every owner file's metadata again.
3. The batch and classifier are immutable observations, but do not use the existing phase-scoped registry reader
   already used by structure and publication. Their read boundary is narrower than their actual input lifetime.
