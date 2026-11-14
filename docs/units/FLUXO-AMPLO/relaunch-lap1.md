# FLUXO-AMPLO relaunch, lap 1 (01/11, BRT)

## Outcome
- Seven open PRs at 13:50 BRT. Five are in the base: #1014 (merged by the train at 14:06), #936 (14:26), #933 (14:30),
  #932 (lap, gate PASSED, pr.ready, admitted) and #980 (lap, gate PASSED, pr.ready, admitted).
- Two stopped and reported, not forced:
  - #962: a conflict in `docs/programs/fluxo-amplo/plan.md`. Both sides add units at the same place, and the PR carries
    `I1` twice (D-231 and D-234), so keeping both sides would give the graph a duplicate id. `CODEOWNERS` and
    `docs/structure/assets.json` also conflict; the first is derived, the second is append-only.
  - #1006: five files conflict (`docs/operations/incidents.md`, `docs/process/repeats.md`, `scripts/lib/repeats.py`,
    `scripts/lib/usage.py`, `scripts/tests/test_repeats.py`): 11 conflict blocks, about 290 lines. Left for its lane.
- The train: the lock was held by `train@grok-bot-vm-301145804` (14:36 to 14:40 BRT). This container runs no train.
  Nothing was stopped or started here.

## Metric (`scripts/lane-status`, counted commits per hour)
- 14:40 BRT: 5.7 per hour over three hours, newest hour 17.
- 14:47 BRT: 7.7 per hour, newest hour 23.
- `scripts/coordinator status fluxo-amplo`: 11 of 27 units merged.
- Did the goal improve, or only the number? The number moved, because merges landed: the train merged five PRs in
  about 40 minutes, and the lane's two laps were two of them. The mechanism did not improve yet. A lap still needs
  hand work on manifest and graph conflicts (RC-006), and the engine's write-budget block stopped every lap from
  13:57 to 14:35 BRT while the token's live core quota read 14,923 of 15,000 (measured at 14:05 BRT).

## Measured blockers
- Engine write-budget block (`scripts/lib/forge_rate.py`, state in `~/.cache/the-tower/forge-write-budget.json`):
  kind primary, GET `/repos/openuniversity-si/open-university/issues/:id`, recorded 13:57:04 BRT, blocked for 2297 s until 14:35:21 BRT.
  The state was not edited. The block lasts longer than the live numbers needed, which is recorded as an observation.
- `scripts/lane-ship` refuses a PR that has already merged, with the message "the plan is not fully ticked", because
  `base..HEAD` holds no PR commit once the PR is in the base (#1014, 14:43 BRT). The message names the wrong cause.
- The push guard refuses a push when the remote PR branch moved under the lap (#932, 14:42 BRT). The lap then
  stopped with the merge local and nothing pushed.

## Next unit
- `scripts/coordinator next fluxo-amplo` lists F2, K1, K5, L1, R1 and a fix unit for defect KD-3ec4be1f.
  F2 is already delivered by #932, but the graph has no `pr` link for it, so the coordinator shows it pending.
  The fix is one `pr` field in `plan.md`, the same pattern as #1014.
- RC-006 (`docs/process/rule-challenges/RC-006.md`) has no unit yet. It belongs to engine-flow (lane 1). Five cases are
  now on record, and the manifest union in `lane-ship` would have removed the hand work from four of them.
- Not started here: a unit needs intake, research, audit and plan first (D-077). The decision is D-273.
