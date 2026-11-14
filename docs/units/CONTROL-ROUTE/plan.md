# CONTROL-ROUTE: the control plane is the only execution route

The control plane becomes the Tower runner's only job channel and wake source, and the git transport is deleted in the same
change (Daniel 02/11 11:27/11:28, D-290). The meter reads the control-plane queue and drops PRs the forge reports closed.
Deadline: 02/11 13:40 BRT (launch 11:40 + 120 min). Inputs: [intake](intake.md), [research](research.md), [audit](audit.md).

## Plan
- [ ] 1. Unit docs: intake, research, audit (findings F1-F9, roots R1-R3), status.md (environment blockers)
- [ ] 2. Plan and decision D-290
- [ ] 3. Runner: `ControlTransport` only; `service.transport` ≠ control and a missing `OU_RUNNER_TOKEN` are named errors; `GitTransport`, `train/wake` and `service.control_ref` reading deleted; `scripts/service requeue/cancel` refuse and name `POST /v1/admin`; registry and tests
- [ ] 4. Meter: the queue is the control plane's `GET /status` queue, one entry per PR, minus every PR the forge does not report open; tests
- [ ] 5. Retro

## Alternativas

### R1 The runner's route is chosen by a silent conjunction with a built-in fallback
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 flip the shared store to `control`, keep the code | remendo | não: a missing token or a 5xx still rides git silently | 1 min | `scripts/config revert` | the VM keeps riding git unseen | 0 |
| A2 control only: delete `GitTransport` and the fallback, named errors for the setting and the token | corrige a classe | sim: no code path picks git | ~40 min | revert the commit | no route until the operator provisions the token (intended, D-290) | 1 |
| A3 A2 plus a start-time readiness probe of the Worker (`/readyz`) that refuses to start | redesenho | sim | +30 min, Worker unreachable from here | revert | a Worker hiccup at boot stops the runner | 2 |

### R2 The meter counts a queue it reconstructs from a side log
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 keep `train/wake`, add "closed" as an exit | remendo | não: still a side log the runner no longer reads | 15 min | revert | queue and job channel disagree | 0 |
| A2 read `GET /status` queue, collapse by PR, keep only PRs in one forge `open_pulls` read | corrige a classe | sim | ~30 min | revert | Worker unreachable → a failed check, never a stale number | 1 |
| A3 the Worker filters closed PRs itself (store supersession, TTL) | redesenho | sim | Worker change | revert + deploy | out of scope: CONTROL-STORE | 2 |

### R3 An admin channel whose only reader is the transport being deleted
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 leave `requeue/cancel` writing `service.control_ref` | remendo | não: a silent no-op | 0 | — | an operator believes a requeue happened | 0 |
| A2 `requeue/cancel` refuse with the control plane's `POST /v1/admin` route | corrige a classe | sim: no command writes to a channel nobody reads | 10 min | revert | an admin needs `ADMIN_TOKEN` and curl | 1 |
| A3 `requeue/cancel` call `POST /v1/admin` with an admin-token variable | redesenho | sim | +30 min, a new registry key, Worker unreachable from here to prove it | revert | an untested path made mandatory | 2 |

## Escolha
- R1 → A2: removes every route but one, named errors, reversible by revert; A3 needs the Worker, which this session cannot reach (status.md B2).
- R2 → A2: the job store is the queue and the forge is the only judge of open; a store or forge read that fails is a failed check, not a number.
- R3 → A2: loud and honest now; Follow-up: a CLI client of `POST /v1/admin` once a session can reach the Worker (A3), owner A Torre.

## Commits
Dependency graph (critical path 1 → 2 → {3 ∥ 4} → 5, ~25 + 10 + 40 + 15 min):
1. docs/units/CONTROL-ROUTE/{intake,research,audit,status}.md — done first.
2. docs/units/CONTROL-ROUTE/plan.md, docs/domain/DECISIONS.md (D-290).
3. (parallel with 4) scripts/lib/service_runner.py, scripts/lib/service.py, scripts/tests/test_service_runner.py,
   scripts/tests/test_service_control.py, config/registry/service/service.{transport,runner_token_env,control_ref,poll_s}.json,
   config/registry/service.json (generated aggregate), docs/operations/services.md.
4. (parallel with 3) scripts/lib/service_status.py, scripts/tests/test_service_status.py; the registry reader line of
   `service.control_url` is written by 3's owner (the aggregate is one file) — collision edge removed by giving the
   registry to commit 3 only.
5. docs/units/CONTROL-ROUTE/retro.md.

## Premises
Premises: none (no P-NN applies; the measured facts are in audit.md).
- CRITICAL (production route): once merged, a runner without `OU_RUNNER_TOKEN` or with `service.transport` still `git`
  in the shared store stops with a named error instead of merging through git. That is D-290's intent; activation
  (token on the VM, `scripts/config set service.transport control`) is the operator's step, outside this PR. Safest
  reversible option taken: code only, nothing provisioned, revert restores the old route.
- The Worker's `GET /status` keeps `queue: [{pr, sha, woken_at}]` (`services/control-plane/src/core.js:564`); radius: the meter.

## Tests
- 3: `python3 scripts/tests/test_service_runner.py`, `python3 scripts/tests/test_service_control.py`; grep proof
  `rg -n "GitTransport|wake_ref|control_ref|fallback" scripts/lib/service_runner.py` → empty.
- 4: `python3 scripts/tests/test_service_status.py`; before/after over #907 #910 #956 #966.
- Final: `scripts/run test service` (the covers suite) and one `scripts/gate-dev --pr 1083` (bypassed under D-151, so the
  hand-run counts are the proof).

## Base defects expected
- Control-plane job store retention and supersession (CONTROL-STORE).
- `scripts/train serve` and `services/runner/github/tower-runner.yml` still read `train/wake` (outside this unit's files).
- Environment: no `$TOWER_EVENTS_TOKEN`, `*.workers.dev` refused by the proxy, no `shellcheck` on PATH (status.md).
- Met and reproduced identically on the base `fab6e204d` (throwaway worktree): `plan-tick.test.sh`,
  `pr-creation-path.test.sh`, `train-role.test.sh`, `defect-lifecycle.test.sh`, `forge-rate.test.sh`.

## Acceptance (evidence)
1. **No code path reaches git as a transport.**
   ```
   $ rg -n "GitTransport|fallback|train\.wake_ref|service\.control_ref|wake_last|refs\.log" scripts/lib/service_runner.py scripts/lib/service.py
   $ echo $?
   1
   ```
   Empty. `rg -l "service\.control_ref|service\.gate_drafts|GitTransport" scripts services contracts config units docs/operations` is empty too.
2. **A missing token fails loudly naming the variable; the git path cannot be selected.**
   `scripts/tests/test_service_runner.py` `Route`: `test_a_missing_token_is_an_error_that_names_the_variable_not_a_fallback`
   (`RouteError … set $OU_RUNNER_TOKEN`), `test_the_git_route_cannot_be_selected` (`git`, `''`, `None`, `GIT` → `RouteError`
   naming `service.transport`), `test_the_module_has_no_git_transport_and_no_fallback`,
   `test_the_registry_offers_only_the_control_route` (default `control`, enum `[control]`),
   `test_build_refuses_before_any_state_is_written`, `test_the_command_prints_the_route_error_and_exits_2`;
   `scripts/tests/test_service_control.py`: `test_no_token_is_refused_at_construction_naming_the_variable`,
   `test_a_control_plane_that_does_not_answer_is_a_failed_poll_not_another_route`.
3. **The meter no longer counts a closed PR** (`scripts/service status --json`, real git refs and forge):
   | | queue | #907 | #910 | #956 | #966 |
   |---|---|---|---|---|---|
   | before (base code, 11:41 BRT) | 5: 907, 910, 956, 966, 1066 | counted | counted | counted | counted |
   | after, same five fed to the new filter with the live forge read | 1: 1066 | dropped | dropped | dropped | dropped |
   | after, this session's real run | unknown (control plane unreachable, check `control` FAIL) | not counted | not counted | not counted | not counted |
   Forge: 907, 910, 956, 966 `closed merged=false` (01/11); 1066 `open`. Test:
   `test_service_status.py` closed-PR case, `queue_depth` 5 → 1.
4. **Touched suites, run by hand** (all OK): `test_service_runner.py` 31, `test_service_control.py` 9,
   `test_service_status.py` 20, `test_machine_refs.py` 9, `test_config.py` 30, `test_schema_compat.py` 14;
   `operation-config.test.sh`, `operation-relations.test.sh`, `decision-handwritten.test.sh` OK;
   `scripts/run test service` 63 tests, 0 failed; `scripts/schema-compat --base origin/mod/roadmap-integration` 0 errors.
5. **Gate.** `scripts/gate-dev --pr 1083`: D-151 bypass, 8/8 stages marked PASS without running, then
   `FAIL gate evidence: … no events token (class env)` (status.md B3). Real gate, `GATE_BYPASS=0 scripts/gate-quiet`:
   GATE: FAILED in 658 s (ceiling 180 s, D-064 f): 7 stages PASS (schema compat, pr metadata,
   no GitHub Actions workflows, generated drift, secret scan tree and history, structure check); `shellcheck` FAIL class
   env (exit 127, not installed here); script tests FAIL: 132 test files PASS, 13 FAIL — `commit-check`,
   `defect-lifecycle`, `forge-events`, `forge-rate`, `gate-forge-budget`, `gate-isolation`, `gate-local`, `gate-pin`,
   `lessons`, `plan-tick`, `planner-role`, `pr-creation-path`, `train-role`. Each was rerun on the base `fab6e204d` and on
   this head side by side: identical outcome on both (same failure counts; `gate-isolation`, `gate-local`, `gate-pin`
   exit 1 on both, `planner-role` times out on both, `forge-events` passes on both when run alone). None is caused by this
   change; most need `$TOWER_EVENTS_TOKEN` or a forge adapter operation the base lacks.

## Git that remains, and why (measured)
- `remote_heads`/`superseded_job` (D-141): one `git ls-remote refs/pull/*/head` before spending a gate on a claimed job;
  the control plane queues one job per pushed head and has no supersession yet (CONTROL-STORE). A check, not a channel.
- `train_serve.refresh` (D-150): the checkout's fast-forward before each job.
- The train's merge and `train/lock` (`train_git.py`): the merge mechanism, not a job channel.
- Outside this unit's files, still reading `train/wake`: `scripts/train serve` (`train_serve.py`, the train-role session's
  consumer), the staged and disabled `services/runner/github/tower-runner.yml`, and the Worker (`core.js:122`, which also
  takes `pr.ready` from the journal directly). Follow-up for the owner of each.

## Activation after merge (operator, outside this PR)
`OU_RUNNER_TOKEN` on the runner VM, then `scripts/config set service.transport control` (the shared store holds `git`,
which the registry now refuses: `config.get` raises naming the key). Until both, the runner exits 2 naming what is
missing and nothing merges through git: that is D-290. First real run: `scripts/service runner --once` on the VM claims
from the Worker; `GET /status` then shows the VM's heartbeat.

## Cheapest useful effort
Action: rewriting the runner's transport and its two test files.
Cost: ~40 min, one session.
Requirement: Daniel (one route, no fallback) and the operator who provisions the VM token.
Cheaper rejected: flipping the shared store (R1 A1) leaves the silent fallback; a new flag keeps two routes.

Decision: D-290
Premises: none
Fit-Review: not reviewed (Daniel 2026-10-25: no review step)
Claude-Session: https://claude.ai/code/<session>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/<session>
