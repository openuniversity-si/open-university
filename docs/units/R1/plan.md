# R1 — plan

## Alternativas

### R1. The base's real-gate state is not an input of a merge while the regime is on
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 an operator pauses the train when the base is red | remendo | não: relies on someone noticing; RC-005 had no alarm for three hours | minutes per incident | resume the train | a red base merges until someone notices | 0 |
| A2 the train holds a merge while the newest real result of the base is red; an unknown tip is reported, not held | corrige a classe | sim, for every tip that has a result | one change in engine-train and one test | revert the change | an unknown tip is not held (a gap, see Escolha) | 1 |
| A3 the train runs the real gate on the base tip itself before any merge, keyed by sha | redesenho | sim, for every tip | one real gate per tip on the train host, whose speed is not measured | revert the change | throughput loss if the host is slow | 3 |

### R2. A real-gate result of a base tip is visible only on the host that ran it
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 the train reads its own host's `.gate/shadow/<tip>.json`, the file the loop's shadow already writes | remendo | não: only on the host that runs the shadow | one file read in engine-train | revert the change | silent on a host with no shadow (reported as unknown) | 0 |
| A2 gate-shadow publishes the verdict per tip as `refs/heads/gate-base/<sha>`, the way `train/lock` and `train/wake` are shared; the train reads it from origin | corrige a classe | sim, for every host and lane | a change in engine-gate-verdict (lane 11) and one read in engine-train | delete the refs | ref growth, one per tip | 1 |
| A3 a forge event kind `base.gate` in the event contract | redesenho | sim, through the event library | a contract change: contracts/events, schema compat, regeneration | revert the contract | contract churn across units | 2 |

## Escolha
- R1 → A2: the train holds a merge while the newest result of the base tip is red, and reports a tip with no result as unknown without holding it. This keeps a missing shadow from stalling the train. A1 is a person's job and failed in RC-005. A3 needs the train host's gate speed first, which is unmeasured (intake, Lacunas); it is rung 1.
- R2 → A1 (remendo). Why not A2 now: its publisher, `scripts/gate-shadow`, is in engine-gate-verdict (lane 11), and this unit may not edit another lane's unit (relaunch rule). A1 reads a file that engine-train can read on its own host. Follow-up: a unit in engine-gate-verdict (lane 11) makes gate-shadow publish the verdict per tip as `refs/heads/gate-base/<sha>` (A2); the train then reads that ref where it exists. Until that merges, RC-005 is covered only on hosts that run the shadow, and the plan says so in `docs/operations/train.md`.

## Commits
Execution, one PR after this one, 6 items, all in engine-train (lane 2) except where marked:
1. `scripts/tests/test_train_base_hold.py`: a red result of the base tip holds a merge; a green result or no result does not. It must fail before item 3 (the test that fails without the hold). Owns: the new test file.
2. `scripts/lib/train_base_gate.py`: reads the newest `.gate/shadow/<tip>.json` of the base tip in the train's checkout and returns `red`, `green` or `unknown`. Owns: the new module. Depends on: nothing.
3. `scripts/lib/train.py`: `merge` asks item 2 before `port.merge`; a red verdict stops the merge with a printed line and no event, so the queue keeps the batch; unknown is printed and the merge goes on. Owns: `scripts/lib/train.py`. Depends on: 1, 2.
4. Registry: the switch `train.base_hold` (default on) and its owner, so the hold can be turned off by an operator. Owns: `config/registry/train/`. Parallel with 2.
5. `docs/operations/train.md`: the hold, the unknown case, the follow-up of R2 (lane 11). Owns: that doc. Depends on: 3.
6. RETRO, `docs/units/R1/retro.md`, before the merge. Last.

Units touched: engine-train (lane 2) only. Not touched: engine-gate-verdict (lane 11, holds `scripts/gate-shadow`) and engine-flow (lane 1, holds `scripts/lib/train_loop.py`).

## Premises
Premises: none. The unverified facts are in intake.md, Lacunas: whether the train host runs with `--shadow`; the real gate's speed on that host. Neither is a premise of the design: an unknown tip is reported, not held, so a host without a shadow cannot stall the train.

## Tests
- Item 1 must fail on the current train (red result, no hold) and pass after item 3.
- Items 2–5: the train's existing script tests (`scripts/tests/train*.test.sh`) pass unchanged.
- One final real gate per PR: `scripts/lane-ship <pr> --real`, with the bypass left as it is in the registry.
- The PR gate scopes its tests by covers: the new test's covers must name `scripts/lib/train.py` and `scripts/lib/train_base_gate.py`, or the scoped gate would skip it (docs/process/lane.md, "Selection holes").

## Base defects expected
- KD-3ec4be1f (scripts/tests/config.test.sh, open, owner engine-lane): may show in the script tests; not reproduced in this session.

## Cheapest useful effort
Action: the train change (items 2 and 3) and its lap through the real gate on the combined head, including the train's own tests.
Cost: about one to two minutes of real gate per lap, a few laps; no money and no quota beyond the lap.
Requirement: lane-2 (engine-train), the unit's owner lane, which keeps the train's code and reads its refusals.
Cheaper rejected: A1 of R1, a person pausing the train on a red base: rejected, it failed in RC-005 with no alarm for three hours. The real gate inside the train now (rung 1): rejected, the train host's gate speed is unmeasured and the cost would be paid on every base tip.

## Revision 1 (the execution PR, before any code)
The first draft had no way out of a red hold. A hold never moves the base tip, so a red result for the tip would block the very fix that clears it: the fix PR is itself held. Changed:
- **Release by name.** `train.base_hold_release` holds the sha of a red base tip that the train runs anyway. An operator sets it with `scripts/config set ... --actor <who> --reason <why>`, so it is recorded in the config history. A release is for that one tip: the repair PR merges on it, and the next tip is judged by its own result (unknown until someone gates it, so reported and not held).
- **The switch is off by default.** `train.base_hold` changes when the train merges. Turning it on is an operator's decision, with this plan as its record; this unit ships the mechanism inert.
- **One check per drain.** The base tip is read when a drain starts. A merge inside the drain moves the tip to a commit with no real result yet, which is unknown, so it cannot be red until someone gates it.
- **A flaky red is cleared by a rerun, not a release.** A rerun of the shadow on the same host rewrites `.gate/shadow/<sha>.json`, and the train reads the file again. KD-3ec4be1f (config.test.sh) is the known source of such a flake.
