# GX-25 RETRO

## 1. Brief quality
- Good: explicit file ownership, the contract already on base, the verdict-of-record rule.
- Missing: `gate.forge_writes_per_run_max` (6) is already spent by the run; a seventh write (`gate.started`) was not budgeted. Resolved by file-routing `gate.started` (`forge-events.file_kinds`), one key to undo.
- Ambiguous: "shared ledger" for a fresh container. The only ledger readable without GitHub reads is the file-routed step log, which is box-local; the shared part is the registered fallback (`gate-eta.fallback_stage_s`). Step events carry no plan, so the expectation is per stage.
- Wrong: base tip moved from 9fa02090 to 132af477 before launch, then to da1ac7f5.

## 2. Audit and plan
- Held: gate_status `begin` is a usable seam (the driver stays closed); `final_from_report` is the one verdict call site; GS2's critical path ported unchanged in idea.
- Broke: the plan owned no test-fixture or baseline files; the literal census (D-063, only shrinks) and unit manifests (`requires`) turned out to be part of the change.

## 3. Execution (UTC, branch commits)
- 00:5x draft PR #740, audit skeleton; audit+plan; keys; timing report; slo.expected_seconds; gate_status producer/hooks. All pushed one per push.
- Failures, by class: (a) unregistered literals in lib code (0.5, 1000, 12, 2, 100): fixed with config reads, `timedelta`, a shared `as_percent`; (b) the same class in tests: numbers moved to `scripts/tests/fixtures/gate-eta.json` instead of rewriting the census list; (c) own import edge undeclared (`engine-gate-report` -> `engine-slo`): declared in `requires`; (d) the base split `test_gate_status.py` (TX24) so my merge conflicted: took the base files and re-applied my tests in `gate_status/test_started.py`.
- Dead end: ran `literal_census --write` to make the list match; that records growth, which the gate refuses. Reverted.
- Waits: the pause (Daniel 00:57) and the base fixes (TX10 etc.) cost most of the elapsed time; gate runs are ~170-250 s.

## 4. Gate
- Run 1 (head 8f6ba426, old base): FAILED, class code: census baseline growth, units covers/manifest. Both mine.
- Run 2 (head f6e82c0f, base da1ac7f5): pinned verdict PASSED, `.dev.pass` recorded, `gate.passed` a7a6d39a published; `pr.ready` not emitted only because plan item 6 (this file) was not yet ticked. Total 249 s against the 180 s ceiling (script tests 207 s, unit tests 116 s; advisory view, not caused by this change). No known-defect ids hit.

## 5. Lessons
- A new test must not write engine values: a shared fixture helper or the census message pointing to `fixtures/` would have saved two rounds (owner: literals/LT1 maintainers).
- A producer that adds a GitHub write must be told the write budget in the brief (owner: A Torre brief template; key `gate.forge_writes_per_run_max`).
- `scripts/generate` and `literal_census --write` should say which direction they move the baseline (owner: engine-literals).
- Run `scripts/tests/units.test.sh` and `structure-check.test.sh` before the first gate: they catch manifest/`requires`/census faults in about a minute (owner: unit playbook).
