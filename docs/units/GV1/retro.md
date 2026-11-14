# GV1 retro

## 1. Brief quality
- Clear on what to show; ambiguous on "recorded history" for the ETA (no stored per-stage history exists on the forge) and on
  "one comment per head" when gate-dev and gate-db both run on the same head. Decided: local run reports as history; the marker
  carries sha and mode.
- "Branch `claude/gv1-...`" and "push after every step" collide with D-022 when a session pushes two commits at once; the brief did
  not say which wins.
- The brief did not say the PR body must cite an approved D-NNN for a gate change (D-025); it names D-069 only in the title.

## 2. Audit and plan
- Held: KD1 was already merged (the brief assumed it might not be), so known defects are read from `report['known_defects']`, no port needed.
- Held: `step()` is the single stage boundary; `gate_report` main is the single verdict point.
- Broke: the comment could not call `github_api`/`forge_github` directly (structure-check, D-069 item 7); the plan had no step for a
  port method. Added `ForgeEvents.upsert_comment` (plan item 6 absorbed it). Also a unit manifest entry was needed (D-067 (6)).
- Plan items 3 and 4 shipped as one commit (`Plan: 3, 4`): one module, no parallelism to gain. No sub-agents were used; the work was one
  sequential module, so fan-out would have cost more context than it saved.

## 3. Execution (failures, classes, waits)
| Failure | Class | Rework |
|---|---|---|
| registry change left `config_registry_gate.py` stale | generated drift | `scripts/generate` (python outputs) |
| `gate-local.test.sh` failed without `OU_CONFIG_STORE=file` | env of my shell, not the code | set it as the gate does |
| structure-check: direct `github_api` use | architecture class (port) | `upsert_comment` on the port, one commit |
| structure-check: unit manifest missing | ownership class | manifest paths |
| structure-check: two commits in one push (audit+plan) | process class, mine | `scripts/replay-branch 573` -> #574 |
| structure-check: gate change cites no D-NNN | process class, mine | body now cites D-069 |
Dead ends: none. Waits: the first gate run took 437 s (321 s script tests, cold cache); the rerun on #574 took 100 s (cached).
The replay rewrote committer times (all one minute), so the timeline is the order above, not clock times.

## 4. Gate
- Run 1 (#573, head c3da30e8): FAILED. structure check (2 process errors above) and script tests (only the known base defects
  `generate.test.sh` KD-024bbecb and `premises.test.sh` KD-4db6e693). The new status comment rendered this run correctly as BLOCKS.
- Run 2 (#574, head 9c5db898): PASSED, 100 s, known defects only.
- A rerun after this retro commit is needed (new head); it is docs only and cached.

## 5. Lessons and owners
1. A session that commits audit+plan before the PR exists pushes them together. Brief template (owner: A Torre) should say
   "push the audit commit, then the plan commit, as separate pushes". Cheaper still: `commit-check` is run locally by `scripts/pr-ready`
   before the first push (owner: engine lane).
2. A gate-change brief must state the D-NNN to cite in the PR body (owner: A Torre, brief template).
3. The structure-check "direct vendor call" rule could name the port method to add (owner: engine lane, `unit_check.py` message).
4. `gate-local.test.sh` reads the shared config store unless `OU_CONFIG_STORE=file`; the test should set it itself (owner: gate area,
   test fix, not done here: gate tests are KD1/GS1 territory).
5. Gate comment: the start table lists the full dev stage list until classification finishes; the replan then narrows it. Known, harmless.
