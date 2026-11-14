# ORIGIN-FINISH — plan

Reads [audit.md](audit.md) (`## Causas raiz` R1–R5) and [research.md](research.md) (`## Escada de ambição`).

## Alternativas

### R1 The vendor check cannot see a Python process that runs a vendor's module by path
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 add the seven sites to the baseline | remendo | não: the count grows and the calls stay | 10 min | revert | shrink-only refuses growth | 0 |
| A2 move the seven calls behind the port and teach the detector the Python argv form, so a new one is refused | corrige a classe | sim | ~90 min | revert per commit | a consumer's demand missing from operation_demands | 1 |
| A3 delete `github_cli.py` and every subprocess client | redesenho | sim | larger: sessions and tests still use the shim | hard | breaks session tooling | 2 |

### R2 The forge is selected per concern, not once
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 document the board, the store and the remote | remendo | não | 5 min | — | the dual path stays | 0 |
| A2 the board takes the selected forge; the Origin adapter refuses a git remote whose host is not a declared Origin git host (fail closed); the config store's move is its own unit | corrige a classe | sim, for the forge operations; the store follows | ~40 min | revert | the Origin git host is unknown here, so the key starts empty and the operator sets it | 1 |
| A3 one forge object built once (API + git remote + store) from one key | redesenho | sim | a redesign of config bootstrap | hard | collides with TRAIN-DEFINITIVE | 3 |

### R3 Nothing checks that the selected forge can run before the operation runs on it
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 add an Origin row to `credentials.PROVIDERS` | remendo | não: the GitHub row stays mandatory | 15 min | revert | preflight still demands GitHub after the switch | 0 |
| A2 the forge credential is the selected forge's: each forge module answers its own gaps, the port dispatches by `forge-events.adapter`, preflight prints them | corrige a classe | sim | ~40 min | revert | preflight messages pinned in tests | 1 |

### R4 Origin is not part of any environment the operation runs in
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 flip `forge-events.adapter` to origin now | remendo | não: no environment can reach Origin, every gate and train run fails | 1 min | `scripts/config revert` | stops the whole operation | 0 |
| A2 the engine names every gap of the selected forge (R3) and the outside steps are written exactly; the coordinator applies them | corrige a classe | sim, inside the repository; the environments are outside | in R3 | revert | none until the switch | 1 |
| A3 pin the `origin` CLI in the toolchain manifest and the cloud setup | redesenho | sim | needs the vendor's published binary and checksum, unreachable from this egress | revert | an unverified checksum stops setup | 2 |

### R5 The engine names a change's head by GitHub's ref namespace
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 leave `refs/pull/*` and record it | remendo | não | 0 | — | the runner's stale check breaks on a forge without that namespace | 0 |
| A2 a port operation for a change's head ref, answered by each adapter | corrige a classe | sim | a new port operation, its demands and proofs, plus the runner (TRAIN-DEFINITIVE's file) | revert | collides with TRAIN-DEFINITIVE (`service_runner.py`) | 1 |

## Escolha
- R1 → A2: removes the calls and makes the class refusable; A3 breaks session tooling for no operation gain.
- R2 → A2: closes the forge's dual path now, fail closed; the config store moves in its own unit because it carries the
  5 live overrides (a source-of-truth move of the configuration).
  Follow-up: CONFIG-STORE-CONTROL (config.store_adapter gains `control`, a snapshot copy, then the switch).
- R3 → A2: the readiness of the selected forge is the safety of the operator's switch.
- R4 → A2: the only safe rung reachable here; A1 would stop the operation and A3 needs the vendor's checksum this egress
  cannot fetch. Follow-up: ORIGIN-TOOLCHAIN (pin the origin CLI in `config/registry/toolchain.json` once its release
  checksum is reachable).
- R5 → A1 remendo, recorded: the sites are in `service_runner.py` and the gate's pin, which TRAIN-DEFINITIVE redesigns now.
  Follow-up: ORIGIN-HEAD-REF (a port operation for a change's head ref), after TRAIN-DEFINITIVE merges.

## Commits
Items (the `Plan: N` trailers). Several commits may deliver one item.
- [ ] 1. docs(origin-finish): audit skeleton, the draft PR first
- [ ] 2. docs(origin-finish): intake and research
- [ ] 3. docs(origin-finish): the audit
- [ ] 4. docs(origin-finish): the plan
- [ ] 5. GitHub calls outside the adapters move behind the port; the vendor check sees the Python argv form
- [ ] 6. One selection: the board takes the selected forge; Origin refuses a non-Origin git remote; the dead
      `release_policy merge` command leaves
- [ ] 7. Preflight checks the selected forge's credentials and reach
- [ ] 8. docs(origin-finish): the retro

Graph (files owned; `‖` runs in parallel):
- 5a gate pin and explain → `port.change` (`gate_pin.py`, `gate_explain.py`, their tests) ‖
- 5b merge_behind, decision_next, lane_ship, lane_status → the port (those modules, their tests) ‖
- 6a Origin git host guard (`forge_origin.py`, `origin-client.git_hosts`, Origin adapter tests) ‖
- 7 + 6b + 6c (coordinator): `credentials.py`, `preflight.py`, `forge_events.py`, `forge_github.py`,
  `forge_origin_client.py`, `release_policy.py`, their tests
- 5c (after 5a, 5b): `vendor_check.py`, `engine-vendors.json`, `operation_demands.json`, `operation_relations.json`,
  unit manifests. Real edge: the detector is green only once the sites are gone.

Critical path: 4 → 5a/5b (~40 min, parallel) → 5c (~15 min) → gate (~10 min) → 8. About 75 minutes.

## Premises
Premises: none
- CRITICAL (unverified, outside): `openuniversity-si/open-university` exists on Origin with its branches. If not, the switch cannot run;
  scope unchanged (the switch is the coordinator's step).
- CRITICAL (unverified, outside): Origin's git host. The guard starts with no host declared and refuses; the operator
  declares it. Safe and reversible.

## Tests
- 5a/5b: each module's suite (`scripts/run test <name>` per `scripts/tests/covers/`).
- 6/7: `scripts/run test forge-events`, `credentials`, `release-policy`, `preflight`.
- 5c: `vendor_check` over the tree (0 errors), `python3 scripts/lib/operation_demands.py` (0 confrontation),
  `scripts/operation-relations`, `scripts/structure-check`.
- One final `scripts/gate-dev --pr 1087`.

## Base defects expected
Found on the base `98cf1db5` and fixed here (the gate's D-151 bypass runs no suite, so each was measured by hand):
- `forge-events`: `test_operation_integration` imported `scripts.tests.*` (ModuleNotFoundError).
- `defect-lifecycle`: the shared defects fixture's journal lacked `open_changes` (defect_router's demand).
- `operation-relations`: the declaration named `train.py`/`engine_role.py` lines the tree no longer has.
- `commit-check`: a test pinned Origin's refusal of `force_pushes`, which #1081 removed.

## Outside steps (the coordinator; this unit stops here)
1. Daniel's decision (source of truth): `openuniversity-si/open-university` is imported on Origin with every branch, and GitHub is
   frozen for writes at the cut-over.
2. Runner VM and each cloud environment: install the `origin` CLI (or set `OU_ORIGIN_CLI`), add `CURSOR_API_KEY` as a
   secret, allow egress to the Origin API and git hosts.
3. `git remote set-url origin <Origin git URL of openuniversity-si/open-university>` on the VM checkout.
4. `scripts/config set origin-client.git_hosts '["<Origin git host>"]' --reason "..."`, and
   `scripts/config set forge-events.repo <owner/name on Origin>` when Origin's slug differs from `openuniversity-si/open-university`
   (the Origin fixtures use `openuniversity-si/open-university`). Both go to the change store, which is still a
   GitHub issue until CONFIG-STORE-CONTROL moves it. The control plane names the same slug in `REPO` (`services/control-plane/wrangler.toml`):
   its `pr.ready` train jobs and sweeps carry it, and the Origin adapter refuses a lock of another repository.
   `forge-events.*` keys locate the change store, so `scripts/config set` refuses them: `forge-events.repo` and
   `forge-events.adapter` (step 6) change in their registry files, and the overrides of the old store are set again in
   the new one before the merge (from a checkout of the cut-over head).
5. `scripts/cloud/preflight` with the forge on origin prints no forge gap.
6. `scripts/config set forge-events.adapter origin --reason "ORIGIN-FINISH cut-over"` (revert: `scripts/config revert`).
7. First real run: the smallest PR opened on Origin, `scripts/gate-dev --pr <n>`, `scripts/pr-ready`, the train merges.

## Cheapest useful effort
Action: moving seven GitHub calls behind the port with their tests.
Cost: about 60–90 minutes of session time and the sub-agents' quota; no money.
Requirement: Daniel, whose standing target ends the project only when GitHub is out of the operation; these calls keep
it in whatever the selector says.
Cheaper rejected: adding them to the baseline keeps GitHub in the operation and the shrink-only rule refuses it;
flipping the selector alone would leave the board, the git remote and the seven calls on GitHub.
