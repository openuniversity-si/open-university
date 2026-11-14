# GX-32 RETRO: base health signal (`base.red` / `base.green`)

PR #737, branch `mod/gx32`, base `mod/roadmap-integration` (3cae824a at launch, b1542ca4 merged in at be794b76).

## 1. Brief quality
- Clear on ownership, contracts (do not edit), rollback switch and the GX-13 rule. Missing: **how tier 3 hands its failing tests to the battery**. `GateResult` carries failing test *files* only, with no signature (`engine_role.py:45,53-59`), and the battery's `battery.red` names one stage. The answer was found in the audit: `GATE_REPORT_DIR` (`gate-local:280`) lets the caller pick the report directory.
- Ambiguous: `defects.stages` (all stage kinds) next to the GX-13 re-run, which only knows how to re-run a script test. Resolved by splitting "adjudicated" (`defects.stages`, every per-test stage) from "re-runnable" (the script shape only, `defect_adapters.rerunnable`).
- The brief asks to "pause re-gate asks while the base is red", which lives in the train or coordinator, not in the files of this unit. `defect_detect.base_red(base)` is exposed; the wiring is routed to the train owner.
- The harness named a branch (`claude/gx32-…`) different from the brief's (`mod/gx32`). The brief's explicit name was used (one branch, one PR).

## 2. Audit and plan
- Premises held: GX-13 merged (32f3aca0 on base), contracts locked and unused (only the `test_event_contracts.py` fixture), `scripts/lib/defect_*.py` already owned by `engine-defects` (no manifest or CODEOWNERS change for the new file).
- One premise broke: "battery.py needs no new unit edge". It imports `defect_adapters` (engine-defects). The structure check refused `engine-battery` with no `requires`, and the line was added (OWN DEPENDENCIES rule).
- The plan did not change (6 items). Items 4 and 5 were parallel by file but were run in sequence by one writer: each took about 5 minutes, less than a sub-agent brief.

## 3. Execution (UTC commit times)
- 03:01 skeleton + draft PR #737 + STATUS (step 0 within ~3 min). 03:04 audit, 03:05 plan, 03:06 adapters, 03:11 adjudication, 03:12 battery, 03:14 literal/requires correction, 03:15 base merge (be794b76).
- Failure 1 (class: **test reaches the real forge**): the first adjudication commit made `apply_to_report` read the repository channel through the GitHub adapter. The existing `Touched` tests then took 18 s per read (55 s suite instead of 14 s; 8 s per read under the hermetic network denial). Fix for the class: a module-level `setUpModule` stub in `test_defect_detect.py`, so no test in the file reaches the forge; a test that needs the signal passes its own `reader`. The suite runs in 4 s.
- Failure 2 (class: **engine literal census**, D-068): the new tests added integers (tip numbers, `range(5)`, a datetime, `0o755` written a second time) and one duration string. Found by `scripts/structure-check` **before** the gate (brief standard v2 (4)), not by the gate. Fix: one shared `tier3_gate` helper (the chmod is written once), tips from a counter, the injected config clock, string PR names. Lesson below.
- No dead ends and no waits other than the gate (196 s).

## 4. Gate
- One pinned run, `scripts/gate-dev --pr 737` on be794b76: **PASSED**, 7 stages (no GitHub Actions workflows, generated drift, schema compat, secret scan tree/history, structure check, script tests), 88/88 script tests PASS, no known defect needed, `gate.passed 3cb4fe9113bc`. Total 196.192 s over the 180 s ceiling (report-only warning, D-064 (f); the script-tests stage took 151.5 s).
- The RETRO commit (docs only) is re-gated before MERGE-READY.

## 5. Lessons
- The literal census should run in `scripts/commit-check --local` (pre-push), not only in the full structure check, so a test that adds integers is refused at push. Owner: GX-15 (local-checks.json / local_checks.py).
- A test-suite guard that fails any script test that opens a GitHub connection *outside* the hermetic layer (today the hermetic denial only shows up as a slow retry, 8 s). Owner: GX-ENV / hermetic owner. A registry key for the forge read timeout of read-only consumers would bound it.
- Brief template: when a unit consumes another component's output (here tier 3's failing tests), name the hand-off channel in the brief. Owner: the coordinator (brief template).

## First real run (DONE MEANS RUNNING)
The producer runs only where the battery runs (`battery.enabled` off, owned by the train session). After merge, the coordinator or the train session runs `scripts/battery run` on the next `integration.advanced`. Evidence to collect: a `base.red` (red tip) or no event (green tip with no open red) on the repository channel, read with `scripts/forge-events` (or `forge_events.ForgeEvents.read(repo, None, kinds=['base.red','base.green'])`). Then one PR gated on that base whose only failure is a listed test shows `source: base.red` in `known_defects`.
