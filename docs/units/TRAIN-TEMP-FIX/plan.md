# TRAIN-TEMP-FIX — plan

Reads [audit.md](audit.md) `## Causas raiz` (R1–R4) and [research.md](research.md) `## Escada de ambição`. A temporary
fix inside today's design: no change to the batch, the lock model, the control-plane Worker or the job store.

## Alternativas

### R1 A train run that dies leaves no durable cause (mecanismo faltando)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Run the train by hand from a session with the token whenever it stalls (what merged #1084/#1083 at 17:32Z, F9) | remendo | não: the next stall is just as silent | 1 min per stall, plus the hours until someone notices | nothing to undo | the stall is found by a human again | 0 |
| A2 Make the machine that runs the train able to read the journal again: `$TOWER_EVENTS_TOKEN` (and the D-290 runner token) in the VM's `runner.env`, or a git read path for the log | remendo for R1, the fix for R2 | não for R1: the next different cause dies just as silently | VM access this unit does not have (no gcloud, no ssh); a git log path reverses D-290 | edit one file on the VM | cannot be done or proved from a session; a git log path re-opens a route CONTROL-ROUTE deleted | 1 |
| A3 Make the train's failure impossible to miss: a run that raises releases the lock with `died: <type>: <first line>` on the release record (over git, the channel that still works), ends its output with `train: died: …` (the runner job's `log_tail`), and `scripts/service status` warns with it and relays the control plane's own failing checks (the silent VM runner of F10) | corrige a classe | sim: every cause of death, present and future, names itself where a session reads | ~30 min, two code commits | revert one merge commit; the record field is additive (older readers ignore it) | an exception message that carried a secret would be written on a ref: messages are the engine's own (`ControlError` names the variable, never its value) and are cut to one line of 300 characters | 2 |
| A4 Supervised runner with a credential inventory per runner and failure events in the train contract | redesenho | sim | a unit or more | n/a | out of scope by Daniel's order | 4 |

### R2 The log adapter moved to a transport that one of the runners cannot use (arquitetura/desenho)
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Provision the VM's tokens (R1's A2, first half) | remendo | não: the next switch can strand another runner | VM access | edit one file | not reachable from here | 1 |
| A2 An inventory of who must hold which credential, checked before a route switch | corrige a classe | sim | the redesign | n/a | out of scope | 3 |

## Escolha
- R1 → A3: it is the only alternative that a session can implement, test and prove today, and it covers every cause of
  death, not just today's; A1 is still used once (step 7 of the brief: `scripts/train run --pr 1085`) because the
  train must run somewhere that holds the token, and A2 is weighed and not stacked: it is not executable from a
  session (no VM access) and its git variant would reverse D-290.
- R2 → A1, remendo, not executed here: the VM is out of this session's reach. Follow-up: the VM's owner (CONTROL-ROUTE
  lane, `docs/operations/services.md:38`) provisions the runner token in `runner.env`, recorded on the diary as a
  blocker and in [status.md](status.md); the class fix (A2) belongs to the train redesign.
- R3: fixed by `5b23c44fe` (#1083) before this unit acted (audit F13); this unit records the before/after count only.
- R4 (bug local): fixed in commit 5 (the status line says `free (released by …)`).

Rollback (one key): `git revert -m 1 <merge sha of this PR>`. No registry switch is added: the change is additive (a
`died` field on a release record and two status lines), and a switch would be one more key to keep for a temporary
fix.

## Commits
1. intake.md + research.md — `docs/units/TRAIN-TEMP-FIX/{intake,research}.md`.
2. audit.md — `docs/units/TRAIN-TEMP-FIX/audit.md` (after 1).
3. plan.md — this file (after 2).
4. A dying run leaves its reason — `scripts/lib/engine_role.py`, `scripts/lib/train.py`, `scripts/lib/forge_events.py`,
   `scripts/lib/forge_github.py`, `scripts/lib/forge_origin.py` (own dependency: the port's `unlock` gains an optional
   `died`), `scripts/tests/test_train_role.py`, `scripts/tests/test_train.py`, `scripts/tests/test_battery.py`,
   `scripts/tests/test_planner_role.py` (fakes accept `died`), `scripts/tests/forge_events/test_forge_contract.py`.
5. Status shows it — `scripts/lib/service_status.py`, `scripts/tests/test_service_status.py` (file-disjoint from 4: it
   reads the `died` key by name, so 4 and 5 could run in parallel; one writer serializes them).
6. status.md, the push-refusal incident of this unit closed, retro — `docs/units/TRAIN-TEMP-FIX/{status,retro}.md`,
   `docs/operations/incidents/I-774747c4.md` (after 5 and the gate).

Critical path: 1 → 2 → 3 → 4 → 5 → gate → 6 → pr-ready → train run, about 60 min; every edge after 3 is a single-writer
collision, not a data dependency, except gate → 6 (the retro quotes the gate).

## Premises
Premises: none. Unit premises (not registered): U1 the train run from this session reaches the control plane with
`$TOWER_EVENTS_TOKEN` (proved at 17:32Z by F9; blast radius: this PR's merge). U2 the VM cannot be fixed from here
(blast radius: the train stays session-run until its owner provisions it; CRITICAL for "the train merges by itself",
not for this PR).

## Tests
- Commit 4: `test_train_role.py`, `test_train.py`, `test_battery.py`, `test_planner_role.py`,
  `forge_events/test_forge_contract.py`, `forge_events/test_loopback.py`, `forge_events/test_forge_flow_compatibility.py`,
  `forge_events/test_forge_requirements.py`.
- Commit 5: `test_service_status.py`, `test_service_runner.py`.
- One final gate: `scripts/gate-dev --pr 1085`.

## Base defects expected
The brief's list (`pr-creation-path.test.sh`, `test_config_check.py::test_structure_check_fails_on_a_registered_literal`,
`test_structure.py` (28), `test_gate_forge_budget.py` (2), `test_preflight.py::test_pinned_vercel_cli_starts`,
`test_github_cli.py::test_the_cache_keeps_at_most_its_entries`), plus two this unit found red on the base (audit F12):
`test_train_role.py::RestBudget::test_the_run_publishes_its_rest_calls_against_the_budget` and `test_planner_role.py`
(`ForgeCompatibilityError` for its `LockingForge`). Owners: the engine lane; not fixed here.

## Cheapest useful effort
Action: commits 4 and 5 (a dying run names itself on the lock release and in status) and one train run of this PR from this session.
Cost: about 30 min of session time and one gate run; no money.
Requirement: Daniel needs the train to merge again and to stop paying for silent stalls.
Cheaper rejected: running the train by hand once (A1) merges today but leaves the next stall just as silent; provisioning the VM token (A2) cannot be done from a session.
