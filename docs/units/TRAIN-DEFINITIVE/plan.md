# TRAIN-DEFINITIVE — plan

Reads [audit.md](audit.md) `## Causas raiz` (R1–R7) and [research.md](research.md) `## Escada de ambição`. The
decision is [D-291](../../domain/decisions/D-291.md): one 10 s budget per runner job, everything else derived from it.

## Final status — owner decision, 2026-11-02 22:19 BRT

All eight implementation items are delivered. Daniel explicitly closes acceptance (c) at the measured **10.523 s
ordinary gate (`ea020515d` run) and approximately 16.8 s cold**. Stop further gate-speed optimization now: more time
on it would itself be the bottleneck. This supersedes the earlier requirement to keep this PR open until every
measurement is below ten seconds. The **ten-second VM budget remains enforced and is the performance target for a
later unit**; no runtime limit is relaxed. See [validation.md](validation.md) for exact measurement conditions.

The five required failing test families and both metadata omissions are resolved. The complete script suite passes.
Finish with a full correctness gate, final body/readiness and the coordinator-only [VM/Worker cutover](rollout.md).
The historical alternatives and chronological continuation below remain as the design record.

## Alternativas

### R1 The lock's life is not the job's life
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Shorten `train.lock_lease_margin_s` / `tier2_timeout_s` | remendo | não: still a guess of the longest run, a dead owner still holds it for the whole guess | 5 min | one key | tier 2 longer than the guess loses the lock | 0 |
| A2 Lease = the job's deadline; TERM and the deadline release with `died`; the runner names the owner, releases a killed job's lock and an orphan at its start | corrige a classe | sim: no holder outlives its job, every exit path releases, and expiry bounds the rest at D | ~1 h | revert | a run that needs more than the budget ends `over_budget` | 2 |
| A3 Move the lock into the control plane (the job lease is the lock) | redesenho | sim | ~1 day: engine_role, battery, three forge adapters, status, tests | revert | the train by hand in a session needs the runner token; one more path to prove | 3 |

### R2 No job has a deadline, so no job owes an answer
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Lower `service.job_timeout_s` to 10 | remendo | não: the job is killed but says nothing, its lock stays, the lease re-runs it | 2 min | one key | silent kills | 0 |
| A2 One budget key; deadline from claim; TERM/KILL; `over_budget`/`died` results with a sentence and phase times; refresh before the claim | corrige a classe | sim | ~1 h | revert | jobs over budget become visible negatives | 2 |

### R3 The VM runs work whose cost is fixed overhead, not judgement
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Keep the bypass on | remendo | não: no gate at all | 0 | — | — | 0 |
| A2 The runner's gate job is the fast decision only (bypass or attested proof, D-152); the train drops its lock renewals and its re-read of the queue under `run --pr`; every job prints its phases so the next cut is measured on the VM | corrige a classe | sim for the VM's share: no VM job can start the 2000 s gate; the container gate is the proof | ~1 h | revert | a PR with no session gate gets a definite no from the VM | 2 |
| A3 A gate that is one process with in-memory stages and a content-addressed store, ≤ 10 s in the container | redesenho | sim | days; owned by the gate lane | — | — | 3 |

### R4 The queue keeps work whose subject is gone
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Purge the store by hand | remendo | não | 5 min | — | it grows back | 0 |
| A2 `closed` cancels a PR's queued jobs; an ended lease is a `died` result; expiry on every request | corrige a classe | sim | ~45 min | revert + redeploy | none known | 2 |

### R5 The coordinator's code and its deployment are two sources
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 A runbook line "deploy after merging" | remendo | não | 5 min | — | forgotten again | 0 |
| A2 A base push that changes `services/control-plane/` queues a `deploy` job; the runner uploads the Worker through the Cloudflare API within the budget, with a credential in the inventory | corrige a classe | sim | ~1 h | revert; the previous Worker is redeployed the same way | a wrong upload breaks the control plane until the next deploy (tests pin the request) | 2 |

### R6 Secrets have no consumer inventory and auth failures have no voice
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Document the VM's path | remendo | não | 5 min | — | the next rotation is silent again | 0 |
| A2 `service.token_holders` inventory; the runner checks its variables at start and names a 401 as the rotated secret; the control plane counts and names refused runners; the unit file's secrets file is mandatory | corrige a classe | sim | ~45 min | revert | a missing file now stops the unit loudly (intended) | 2 |

## Escolha
- R1 → A2: every exit path releases and the lease ends at the deadline; A3 is the redesign the budget makes cheap later, but it would add a second lock path for the sessions' hand runs today.
- R2 → A2: the order is literal (10 s), the answer must say why; A1 hides the kill.
- R3 → A2: within this unit's reach and measured on the VM by the phases; A3 is the gate lane's (G1/G2, D-269). Follow-up: the container's real gate (39–71 s, audit F5) to ≤ 10 s, owned by the gate lane; this unit records the measured cuts (structure check 13 s, pre-stage 13 s, publish 8.7 s).
- R4 → A2.
- R5 → A2.
- R6 → A2.
- R7 (bug local): validate the runner name and forget a runner silent for `RUNNER_FORGET_S`.

## Commits
Dependency graph (`→` = needs). Item 3 (this file) and D-291 are the preparation: the names every worker uses
(`service.job_budget_s`, `TOWER_JOB_DEADLINE`, `TOWER_JOB_OWNER`, outcomes `over_budget`/`died`, job kind `deploy`,
`LEASE_S`) are fixed here, so items 4–8 run in parallel on separate files.

- [x] 1. Unit docs: intake, research (and the retro at the end). Owns `docs/units/TRAIN-DEFINITIVE/{intake,research,retro}.md`.
- [x] 2. Audit. Owns `audit.md`.
- [x] 3. Plan and D-291. Owns `plan.md`, `docs/domain/decisions/D-291.md`.
- [x] 4. Runner budget (→3): deadline, TERM/KILL, `over_budget`/`died`, `reason`, `phases`, refresh before the claim, orphan recovery, the gate job's real-gate path. Owns `scripts/lib/service_runner.py`, `scripts/lib/service_budget.py`, `scripts/lib/gate_fast.py`, `config/registry/service/service.job_budget_s.json` (replaces `service.job_timeout_s.json`), `service.gate_command.json`, `contracts/service/result.v1.json`, `scripts/tests/test_service_runner.py`, `scripts/tests/test_gate_fast*.py`.
- [x] 5. Lock = the job's deadline (→3, parallel with 4: shares only the env names): `expires = D`, no renewal past it, TERM/alarm release, owner from the runner, `run --pr` stops after its batch. Owns `scripts/lib/engine_role.py`, `scripts/lib/train.py`, `config/registry/train/train.lock_lease_margin_s.json` (removed), `scripts/tests/test_train_role.py`, `scripts/tests/test_engine_role*.py`.
- [x] 6. Control plane (→3, parallel): lease, `died`, expiry on every request, `closed` cancel, runner name and forget, refused-token voice, `deploy` job. Owns `services/control-plane/src/core.js`, `wrangler.toml`, `services/control-plane/test/*.mjs`, `contracts/service/job.v2.json`.
- [x] 7. Credentials and deploy (→3, parallel): `service.token_holders`, the runner's start check and 401 sentence (a function `service_runner` imports), the Cloudflare upload, the unit file and the runbook. Owns `scripts/lib/service_credentials.py`, `scripts/lib/service_deploy.py`, their tests, `config/registry/service/service.token_holders.json`, `services/runner/tower-runner.service.tmpl`, `docs/operations/services.md`.
- [x] 8. Integration (→4,5,6,7): `service_runner` runs `deploy` jobs and calls the credential check, status relays, the measured cut list. Owns the wiring lines only.

Critical path: 3 (15 min) → 4 or 5 (60 min, parallel with 6 and 7) → 8 (30 min) → gate → retro (20 min): about 2 h 15 min.

## Premises
Premises: none. Unverified premises, each with its blast radius:
- The Cloudflare script upload API keeps `secret_text` bindings with `keep_bindings` (radius: the control plane's
  secrets after the first automatic deploy). **CRITICAL** (touches the live control plane): the first deploy of this
  change is the coordinator's, by hand, and the automatic path is proved on the next control-plane change.
- The VM's `runner.env` holds `OU_RUNNER_TOKEN`, `TOWER_EVENTS_TOKEN`, `GH_TOKEN` (radius: the VM's start check refuses
  to start without them; the error names each).
- A train run with the bypass on fits 10 s on the VM (radius: every merge). Not measurable from a session (D-269);
  the phases in each result measure it from the first run. If it does not fit, the answer is `over_budget at <phase>`,
  a definite no, and the next cut is named by the phase.

## Tests
- 4: `scripts/tests/test_service_runner.py`, `test_gate_fast*.py`, `scripts/schema-compat`.
- 5: `scripts/tests/test_train_role.py` (known base failure: RestBudget), `test_engine_role*.py`, `test_train.py`.
- 6: `node --test services/control-plane/test/`.
- 7: the new tests of `runner_credentials` and `control_deploy`, `scripts/config check`.
- Final: one `scripts/gate-dev --pr <n>`.

## Codex continuation (2026-11-02)

The commits through `b6ece232` deliver all eight original plan items, but do not prove the intake's six outcomes.
The intake is completed in place; this is continuation, not a replacement unit. In particular R3 → A2's follow-up
does not discharge outcome (c). A bypassed gate or an attested lookup must never be reported as the measured real gate.

Remaining execution, using the existing PR plan items:

- Item 4: include claim latency, head checks, process cleanup and reporting in the budget; kill descendants even if
  their leader has exited; recover the previous job before claiming anything after restart. Test with real processes.
- Item 6: derive the lease from the same budget, persist expiry, and preserve bounded terminal history and runner ownership.
- Item 7/8: keep failed deploys retryable and surface refused result/heartbeat credentials, not only refused claims.
- Item 8: run every touched suite by hand, measure the real gate, document exact VM/Worker rollout and unresolved
  evidence. Do not declare (c) satisfied from the fast decision path. Gate and train handoff use this same PR.

## Required failure families — resolved
The train-role accounting failure, planner concurrency, defect-lifecycle, lessons, plan-tick and PR creation-path
failures were fixed in this PR. Registry readers and operation call-site metadata are complete; no base-defect
handoff remains. The chronological audit and validation retain their original failing observations.

## Cheapest useful effort
Action: the runner and lock changes (items 4 and 5) with their tests.
Cost: the existing session and VM; no paid service.
Requirement: the coordinator, who must see every VM job end within 10 s with a reason and the lock free after it.
Cheaper rejected: lowering the three timeouts (A1 of R1/R2) leaves dead owners silent and jobs without an answer; a
runbook for deploys and rotations repeats the two incidents of today.

## Owner continuation: real gate, end to end (02/11)

Daniel requires every red suite to be repaired, regardless of origin, and the actual end-to-end gate to fit ten
seconds. R3's former deferral is replaced by A3: one run context with shared immutable syntax facts, one identity
and metadata snapshot, one decision/preflight, and one batched result publication. The checks and affected tests
remain mandatory; neither the D-151 bypass nor a single attested-proof lookup counts as this measurement.

The structure profile shows 2,063 parses and 3.75 million repeated AST visits per tree check. Immutable text-keyed
syntax facts are shared only during the run and discarded afterward; editing source always changes the key.
The five red areas are in this unit's scope: complete strict fixture interfaces, observe remote ref state to classify
a planner race, and derive creation adapters from the existing vendor catalog instead of a GitHub-specific list.

The owner continuation replaces the proof-only VM command with the actual gate. Pinned tooling is selected before
one preflight; the normal entry no longer probes whole-gate attestations at several layers. Independent stage
scheduling, shared immutable Python syntax, parallel metadata reads and acknowledged-verdict reuse remove fixed
cost without weakening checks. Content-addressed test reuse remains bound to source, tooling and toolchain.

The authoritative status is the journal, not a synchronous PR-comment panel. The existing optional panel defaults
off and does no ETA/network work when disabled. Deterministic generation and schema checks reuse exact content
keys (all source inputs, base scope for compatibility, tooling and toolchain); metadata always runs. The script
proof store is read remotely only when a local input key is missing. The dependency graph now reflects independent
checks rather than an unnecessary serial barrier before script tests.

The full graph continuation repairs every newly exposed fixture: copied repositories retain JSON adapter evidence;
missing-compatibility tests explicitly remove the proof instead of assuming Origin lacks a now-implemented operation;
rate and event logs are private; real deadline tests assert the executor's measured result rather than introducing
uncontrolled clock reads. A detached subject binds the judge's installed toolchain rather than installing a second one.
The fresh metadata observation is handed to the result publisher with its PR/head binding, eliminating duplicate PR
reads while still checking current metadata on every run. UID 0 integration runs in an isolated local root profile.

The superseded proof-only runner mode is removed, including its CLI flag and service-unit dependency. It cannot
serve as an alternate job path. The root-profile proof declares all scripts, services and configuration its static
checks read, so a source change cannot accidentally reuse evidence over a narrower input set.

The gate publisher no longer issues a second git wake or detached train after pr.ready: the acknowledged control-plane
journal append queues that exact job. Existing control-plane event tests prove queueing and deduplication; the gate hook
now proves it does not start the legacy trigger. This removes remote configuration and git round trips from publication.

### R10 alternatives and choice
- A1 Ignore dirty state inside the cache: rejected; it could reuse a proof over untracked source.
- A2 Declare the installed tool name as ignored for both directories and links: chosen. A regression proves that the
  real toolchain link permits reuse and that an unrelated untracked source file still refuses reuse.
- A3 Copy an installed toolchain per worktree: rejected; it adds installation, storage and startup work.

The Linux progress clock reads `/proc/uptime` directly in Bash; epoch binding uses Bash `EPOCHREALTIME`. Progress
measurement starts no Python process. The runner's independent hard deadline remains the authority. Gate phase marks
cover preparation, stages, publication and the answer. Read-only entrypoints share one configuration-read context.

### R11 alternatives and choice
- A1 Skip compatibility checks on configuration reads: rejected; every actual flow must remain checked.
- A2 Bind observed absolute origins to loaded code objects and classify the current consumers' complete active flows:
  chosen. Weak references release unloaded code; relative synthetic code retains its current-directory semantics.
- A3 Cache arbitrary whole ports and their mutable state: rejected; adapter, clock and schema changes would need a
  second invalidation protocol.

The same nine profiled cases fell from 5.484 s to 2.736 s while retaining all 4,840 preflights. Regression tests cover
stable loaded origins, new code after a link changes and relative synthetic origins. The full forge, planner and
service suites retain complete before-effect compatibility enforcement.

The Claude session integration proof also declares its complete source/configuration/contract corpus. Its CLI and
root-profile assertions transitively execute those modules; they cannot reuse a proof that omits the runtime boundary.

### R12 alternatives and choice
- A1 Suppress incidents in tests: rejected; actual refusals still need their durable record.
- A2 Pass the affected checkout through reporting and resolve its git root: chosen; the existing real-hook refusal
  test asserts that its own repository receives exactly one incident.
- A3 Ignore incident paths when checking cleanliness: rejected; untracked source must continue to invalidate reuse.

### R13 alternatives and choice
- A1 Cache an already-lifted success: rejected; later enforcement could lose the original errors.
- A2 Store complete immutable diagnostics and apply current policy every time: chosen. A regression reads the same
  errors twice, first under the lifted regime and then enforced, and proves the second invocation fails.
- A3 Repeat identical static analysis forever: rejected; it spends the VM budget without observing new inputs.

### R14 alternatives and choice
- A1 Ignore documentation changes in the complete tree key: rejected; links, intake and audit checks read them.
- A2 Reuse the four source-only diagnostics by their own input set: chosen. Every tracked filename is covered, as
  are all non-Markdown contents and any Markdown read by configured scans, manifests, production analysis, the
  vendor catalog or the decision register. Dirty, missing or symlinked source inputs fail closed to fresh analysis.
- A3 Split into separately launched commands: rejected; it adds Python startup without improving input binding.

Regressions cover dirty state, changed source, changed filenames, unchanged unread prose, configured Markdown
inputs, and retention of all errors. The remaining tree checks still run after a prose-only commit.

### R15 alternatives and choice
- A1 Disable branch-age evaluation during gates: rejected; pr.ready is a real trigger and must retain the rule.
- A2 Classify triggers before I/O and read once for a batch that has triggers: chosen. Non-triggers read no history;
  the current injected time and earliest event still determine staleness. The emitted stale event cannot recurse
  into another history read. Both properties have real-port regressions.
- A3 Cache history indefinitely in the port: rejected; another publisher may have appended new observations.

R14 also covers hermetic source analysis. Its inputs are the configured test roots, source and registry, already
covered conservatively by the source key. It runs with the other syntax checks on a miss and retains its errors.

### R16 alternatives and choice
- A1 Reuse arbitrary journal ports: rejected; mutable adapter, clock and validation state have another lifetime.
- A2 Consult the existing folded-value memo against the current exact local-file identity before port construction:
  chosen. A miss still constructs the normal checked port and reads/validates the log. The adapter, repository,
  directory and forge-configuration fingerprint remain in the key; only that fingerprint's serialization is memoized.
- A3 Suppress compatibility checks on every local read: rejected; changed input still crosses the complete boundary.

The file identity covers device, inode, mtime, ctime and size. Regressions prove unchanged folds construct one store,
changed logs construct a new checked store, and a same-size rewrite with restored mtime still invalidates the fold.

### R17 alternatives and choice
- A1 Batch every recursive git-show read: rejected; faster reads would still judge fragments as independent owners.
- A2 Match the reader's owner-document boundary: chosen. Compare direct registry JSON documents, which include all
  effective split parameters after generation. The generated-drift check still judges fragment/aggregate agreement.
- A3 Rely exclusively on cached stage passes: rejected; a cold compatibility check must use the right semantics too.

A regression proves nested object properties in a split fragment are not independent registry parameters; existing
owner-removal and live-reader refusal tests remain. Repository hygiene's syntax check joins the exact source inputs,
while its address, image and conflict-marker checks run on the current text tree.

### R18 alternatives and choice
- A1 Avoid source prewarming: rejected; children would reconstruct the shared indexes independently.
- A2 Build the indexes once and return the canonical walk for an all-node selection: chosen. A regression compares
  standard breadth-first ordering, subtype selection and overlapping requested types without duplicate nodes.

### R19 alternatives and choice
- A1 Launch only metadata earlier: rejected; classification would still wait for independent input hashing.
- A2 Compute the exact input key inside the launched cached stage: chosen. Start metadata immediately after the
  tree stage has inherited its tree-only marker, then launch independent key work and classification.
- A3 Stop hashing stage inputs: rejected; exact-key correctness is required.

A FIFO barrier regression requires an independent producer to launch while key generation waits for its event.
The original cache lookup, execution and storage paths remain the same.

### R20 alternatives and choice
- A1 Trust a caller's inherited snapshot: rejected; a new run must observe its own tooling and toolchain.
- A2 Write the result-key snapshot from the successful proof-binding process: chosen. The driver receives both
  observations from its own hook, and a regression proves one attestation and matching toolchain identities.
- A3 Keep the second attestation: rejected; it adds latency and a disagreement window.

An unbound working-tree run still creates its own result-key snapshot once; a binding/export failure retains the
existing fail-closed unbound behavior. The temporary transfer file is removed on success and failure.

### R21 alternatives and choice
- A1 Reuse configuration forever: rejected; a later phase must observe rewritten declarations.
- A2 Scope registry observation to key construction/lookups and to classification: chosen. The key scope ends before
  any test process runs. Content hashes, file-type checks, key material and effect-boundary validation are unchanged.
- A3 Remove configuration from the key: rejected; effective configuration is part of the proof.

Existing configuration-snapshot and key conformance/invalidation suites exercise these contracts; no timing-only
assertion or test that mirrors the implementation is added.
