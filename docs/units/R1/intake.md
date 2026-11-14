# R1 — intake

## Pedido
Unit R1 of program fluxo-amplo, launched by `scripts/coordinator next fluxo-amplo` (01/11 14:45 BRT). Brief, literal: "the train refuses a merge on a red base, so the regime cannot hide one (D-206 (e))". Done criteria, literal: "the train holds a merge while the base's last real gate is red"; "a test fails without the hold". Owner lane: lane-2 (engine-train). Taken by this session (D-276).

## Intenção
The regime of exception (D-151) makes a PR's gate and the train's tier 2 green without running anything. While the regime holds, a red base does not stop the train, and nothing in the merge decision reads the base's real state. The real intention: a red base must stop merges whatever the regime says, and it must be visible to every train host, not only to the lane that measured it.

## Contexto
- Regime on 01/11: `gate.bypass=True`, `service.paused=False` (runner resumed, D-191), `train.trigger_mode=wake` (`scripts/lane-status`, 14:40 BRT). The default of `regime.exception_active` was set true by the grant of 10:52 BRT (D-260), and D-272 pins the judges' view of the regime off for the script tests only.
- The base was red from about 10:52 to about 14:20 BRT while every PR gate and the train's tier 2 read green (RC-005, open, grade 2). Nothing showed BASE BROKEN to the lanes until a manual shadow run at 14:05 BRT.
- The train runs on another host (lock holder `train@grok-bot-vm-…`, 14:40 BRT; `scripts/service status`). The container train of the earlier session is gone.
- `scripts/lib/train_loop.py:35-38` starts `gate-shadow run HEAD` detached "for measurement only ... the loop never waits for it"; its result lands in `.gate/shadow/<sha>.json` on the host that ran it (docs/operations/gate-bypass.md: "It never blocks a merge").

## Regras
- D-151: while `gate.bypass` is true, a PR's gate is green at once and the train's tier 2 is green without running a command; the shadow never blocks a merge.
- D-206 (e): the root rule this unit implements, from the program's diagnostic: a red base holds the train.
- RC-005 (open): proposal (a) is this unit; proposal (b), running the script tests for real on a PR that touches shared tooling, is not.
- D-272: the judges' view of the regime is pinned off in the script tests; the train's view is not changed here.
- Padrão v8: root cause before fix (D-081), fix the class, not the instance (fix-the-class.md), decide then report (decide-then-report.md).
- Premises: `scripts/premises find "train merge base red real gate shadow"` matched only P-47 (no forced base merge), which does not bear on this unit.

## Problema real
While the regime holds, the train's merge decision never reads the base's real-gate state, so a red base merges PRs. Resolved when: a merge is held while the newest published real-gate result of the base is red, every train host can read that result, and a test fails when the hold is removed.

## Lacunas
- Whether `grok-bot-vm` runs the train with `--shadow` (so that a result exists for each new tip). Not visible from this container; it decides how often "unknown" happens. Owner: whoever starts that train (A Torre / Daniel). The design does not depend on it: an unknown tip is reported, not held.
- The real gate's speed on the train host. Unmeasured: the e2-micro is about 12x this container's CPU (docs/operations/gate-bypass.md). Needed before any design that runs the gate inside the train. Owner: lane-2.
- Whether a shared per-tip result can be a git ref (as `train/lock` and `train/wake` are) without a new event kind. Decided in plan.md; the check is in the first code PR.
