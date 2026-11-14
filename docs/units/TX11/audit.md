# TX11 audit: flake attribution on the PR's own head

Base: `891b835ae` (mod/roadmap-integration tip at launch). Every finding re-read on that base.

## What exists

| # | Finding | Where |
|---|---|---|
| A1 | A flake is detected only from train runs: `Train.flake` asks `quarantine.proven_flaky(runs[-1], runs)`, a red run whose sha also has a green run among the train's own runs. Nothing reads a red-then-green re-run of the per-PR gate. | `scripts/lib/train.py:229-235` |
| A2 | The train is not running on its own: `train.trigger_mode` defaults to `emit_only`, so A1 never fires for a PR today. | `config/registry/train.json:330-333` |
| A3 | A quarantined test stays blocking in every tier; the quarantine changes no gate policy. Its state is the repository log alone (`test.flaked`, `test.quarantined`, `test.unquarantined`). | `scripts/lib/quarantine.py:14`, `state()` `:61-72`, `Quarantine.report` `:104-124` |
| A4 | Browser retries are 0; the per-PR gate never re-runs a red test on the same head. | `apps/web/playwright.config.ts:38`, `scripts/gate-local:350` |
| A5 | The only excuse route is known base defects: `gate_report.finalize` calls `adjudicate_known_defects` (`gate_report.py:200-205`) -> `gate_adjudicate.adjudicate` (`gate_adjudicate.py:32-49`) -> `defect_detect.apply_to_report`. A failure is excused only when it fails on the recorded base with the same normalized signature: script tests by a base re-run (`defect_detect.py:131-157`, `adjudicate` `:208-236`), other stages by the tier-3 `base.red` listing (`:183-198`, `:221-224`). A load flake on the PR passes on the base, so it stays the PR's and blocks. | as cited |
| A6 | The re-run building block exists: `gate_test_cache.run(scripts, root, location, source, tool_root)` runs exactly the named script tests through `gate_graph`, hermetic, in the checkout under test, and records a PASS marker in `location`. Called with a throwaway `location`, a re-run neither reads nor writes the real cache. | `scripts/lib/gate_test_cache.py:213-243` |
| A7 | The checkout under test is exported to the report step as `OU_SUBJECT_ROOT`; the tool root is the module's own checkout. The report step runs in the same process environment as the stages (same inputs). | `scripts/gate-local:250`, `:499` |
| A8 | The status table and the verdict already show `report['known_defects']`: the "Known base defect" column (`gate_status.py:192-198`) and `verdict_payload.known_defects` with keys id, stage, signature, base_sha, defect (`gate_proof.py:49-51`). `defect_events` turns each item into `defect.detected`, and `scripts/defects sync` turns that into a record through `defects.record` (test, signature, owner and unit derived from the unit manifests, one evidence entry with `at` per sighting). | `scripts/lib/gate_adjudicate.py:9-28`, `scripts/lib/defects.py:204-238`, `:278-293` |
| A9 | The class of a red stage is printed by the stage runner into the stage log (`gate_classify.py <stage> <log>`) and read back from the last machine line by the status table. Classes: code, env, contract. | `scripts/lib/gate-runner.sh:85-90`, `scripts/lib/gate_status.py:158-171`, `scripts/lib/gate_classify.py:20-25` |
| A10 | A failure is a list of `{id, stage, signature}` from `defect_adapters.failures(report, logs)`; a script-test failure's id is the script path and its signature is `gate_failures.script_failures`' normalized one. | `scripts/lib/defect_adapters.py:51-59` |

## Gaps TX11 closes

1. No attribution of a failure that passes on one re-run at the same head (A1, A4, A5): such a failure turns the PR red today.
2. No `flake` class (A9): tonight's #717 gate-result-cache failure printed class env.
3. No path from a per-PR flake to the quarantine (A3) or the defect registry (A8).

## Scope limits

- v1 re-runs the `script tests` stage only (`gate-flake.stages`): it is the one stage whose failing tests can be re-run alone through a public API (A6). The vitest `Test timed out` and browser cases stay the PR's until a re-run API exists for them; a stage outside the list is never excused.
- A test the PR changed (its file, covers manifest or declared covers) is never excused as a flake, the same rule as base defects (`defect_detect.touched`).
