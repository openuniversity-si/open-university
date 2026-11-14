# Repeated actions (D-208)

Each action done three times by hand is a candidate to systematise. `scripts/repeats` lists the open ones, by count.

| Action | Count | Status | Where it is systematised |
|---|---|---|---|
| Opening a pull request, its body typed by hand | 25 | systematised | `scripts/pr-body`, `scripts/deliver --open` (D-208; `lane-ship --create` until F9) |
| Writing a decision row (number, time, proof) | 70 | systematised, not adopted | histórica, sem medição por transcrito: the record (`scripts/decision-record`, D-217), the row renderer, the write that adds missing rows without rewriting (`scripts/decision-table --write`, D1); the pre-push local check `decision_table` (`scripts/lib/local_checks.py`, #140) runs the drift check on every push that changes a record or the table, and refuses a record without its row |
| Renumbering a colliding decision | 6 | systematised | D-250: the claim on the remote (D-190) takes the number; `scripts/decision-table --check` refuses a duplicate id and a renumbering that leaves a gap (#971, D-183) |
| Resolving a conflict in the decisions table | 8 | open | one record per decision, the table generated (unit D1) |
| Claiming a decision number | 15 | systematised | `scripts/decision-next --claim` (D-190) |
| Writing a lane's start message by hand | 12 | open | the plan's briefs (units B1 and F1, D-206) |
| Checking the flow by running five commands | 9 | systematised | `scripts/flow-check` (D-197) |
| Computing the commit rate by hand | 3 | systematised | `scripts/commit-rate` (D-202) |
| Reading a unit's status from events by hand | 4 | open | the fold from merged pull requests (unit F1, D-206) |

## Measured on the session's transcript (`scripts/usage`, D-208)
The 1,204-call session below is not in this container: its counts are kept as they were measured. `scripts/repeats --transcript FILE` measures any transcript the container holds.
One session, its transcript, 1,204 tool calls: 1,062 shell, 40 messages to other sessions, 26 pull requests created through the GitHub tool, 11 pull request updates, 10 notification reads. From the shell: 787 test runs by hand, 693 library calls, 217 structure checks, 98 flow metrics, 97 cloud checks, 87 laps, 81 lane statuses, 63 regenerations; git: 220 commits, 193 fetches, 174 logs, 104 checkouts, 99 merges, 98 pushes, 79 remote listings.

| Action | Count | Status | Where it is systematised |
|---|---|---|---|
| Syncing a branch with the base (fetch, checkout, merge) by hand | 400 | adoption pending | `scripts/branch-start NAME` (D-211), on the base and documented in lane.md (Starting a branch); start every branch with it |
| Regenerating derived files after an edit | 63 | open | the regeneration exists: `scripts/generate --changed` computes its own paths, the checkout's diff against `gate.changed_base_ref` plus the uncommitted files (#176), and reads paths from stdin only with the opt-in `--stdin`, which `scripts/lib/generate_stage.sh` passes with the staged paths (D-222 (5)); the pre-commit hook that calls the stage script is not wired yet, because `.githooks/*` belongs to engine-push-guard |
| Running the status commands one by one (flow metrics, lane status, service, coordinator) | 264 | systematised, not adopted | `scripts/flow-check` (D-197, D-230): one entry; it replaces flow-metrics --cycles, lane-status, service health, gate-shadow latest, coordinator status and decision-next. Histórica, não reproduzida: the 264 is not reproduced from a transcript on disk; measured on 01/11 (this session's transcript): 0 runs of the six by hand and 1 run of `scripts/flow-check`; the count stays as written (it is not raised or lowered by hand) |
| Running the structure check by hand after each edit | 217 | systematised, not adopted | `scripts/deliver` runs the gate on the exact head before the merge, and its structure check stage is the whole `scripts/structure-check` (`lane-ship` ran it before its push until F9, #978, #986). The pre-push hook runs only the cheap part, `commit-check --local` (`local_checks.structure_fast`: decisions, links, postmortems, premises, the plan), not the whole check (20-34 s). Measured: 217 by hand in the earlier session whose transcript is not in this container; 0 by hand in this session (`scripts/repeats --transcript`, 750e06d9). The count is the latest measure over named sources (D-254); 217 is the historical figure, not reproduced here |
| Opening a pull request through the GitHub tool | 26 | systematised, not adopted | `scripts/deliver --open` (D-166; it replaced `lane-ship --create`, which F9 removed) |
| Messages to other sessions to nudge them | 40 | systematised, not adopted | the read is in place: `scripts/flow-check --idle` (the idle lanes, the review ready ones and the next launches) is the one read before each nudge; the nudge itself still goes by message (D-193) |
| Writing a decision row by hand (Edit or Write to DECISIONS.md) | 0 | adoption pending | `scripts/decision-record` (D-217) is the only path; a hand edit of the table is counted per transcript (`scripts/repeats --write --transcript PATH`) |

## Estado real (lane 20, D-208, D-206)
What the register can and cannot say about the decision record, as measured on the branch it was written on:

- **Measure.** `scripts/usage PATH` counts the runs of `scripts/decision-record` (a run is a shell segment that starts with the name; a name inside an argument is not counted, since lane 20) and the Edit and Write calls to `docs/domain/DECISIONS.md`. `scripts/repeats --write --transcript PATH` writes the hand-written row from them. The count only rises (the register keeps the larger of its own and the transcript's), so the 70 is a history, not a rate. The rate is the hand writes per transcript, and it can only be read from transcripts that are on the machine: this session's transcript holds 0 hand writes to the table. The other lanes' transcripts are not here, so the fall of the 70 cannot be confirmed from this session.
- **Drift.** `scripts/decision-table --check` exits 1 on `origin/mod/roadmap-integration`: 8 of 13 records have their row. Five have none (D-228, D-237, D-239, D-241, D-242); four ids are written twice (D-165, D-166, D-167, D-173). `--handwritten` exits 0: no row was written by hand without a record.

### Incidents (design, class, case)
- **I1, `mecanismo faltando`.** The 70x row was not measured, and the write could only raise a count, so the 70 could never fall. Case: `scripts/repeats --write --transcript` on this session wrote 0 changes. Fixed by measuring the hand writes per transcript (the row above).
- **I2, `bug local`.** `scripts/usage` counted a script or a git verb wherever its name appeared in a command: `rg "decision-record" scripts` counted as a run. Case: this session's counts for `scripts/lib`, `scripts/decision-table` and `scripts/decision-record` were mentions. Fixed: a run is a segment that starts with the name.
- **I3, `mecanismo faltando`.** The 70x row claimed "check passes" while the check exits 1. No gate stage runs `decision-table --check`, and the status was typed by hand, so the red stayed unseen. Options, not taken here (the table is shared by every lane, and the choice of which row survives for the four doubled ids is Daniel's): remendo, `scripts/decision-table --write` adds the five missing rows and the doubled ids are settled by hand; corrige a classe, a gate stage runs `--check` and `decision-record` writes its row in the same commit; redesenho, `DECISIONS.md` is generated whole from the records (the next step of D1).
- **I4, `bug local` (brief).** The lane brief says `--check` refuses a line without a record. That is `--handwritten`; `--check` refuses a record without a row. Both are reported above, neither is changed.

The test `scripts/tests/test_repeats.py` (`Claims`) holds that a row claiming "check passes" must match `scripts/decision-table --check`.

