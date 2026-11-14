# GX-13 RETRO — known defects against a recorded base

PR #729, branch `mod/gx13`, base `mod/roadmap-integration` (eaeeb29d at launch, fbc09f28 merged in). Decision D-070.

## 1. Brief quality
- Clear on the four rules and the two switches; the file fence was precise and correct.
- Gap: "an excused stage keeps `raw_result: FAIL` and the defect id in the **published** verdict" cannot be met from the owned files. The published stage records are built by `gate_proof.stage_records` (`gate_proof.py:12-17`), which belongs to GX-10 (running at the same time) and drops `raw_result`. The report keeps it (`defect_detect.apply_to_report` already set it at KD1; GX-13 adds the stage's defect ids); the verdict carries the ids only in `known_defects`. The brief should have listed `gate_proof.py` as the seam, or routed the line to GX-10.
- Gap: the open → resolved rule needs a writer: `defects.sync` (`defects.py`) is the only tool that changes a record from gate events, and `defects.py` / `test_defects.py` were not in the owned list. Taken as an own dependency (one guarded branch plus one switch-off patch in the old test that encoded "open is never verified").
- The brief's branch (`mod/gx13`) and the session's default branch (`claude/gx13-...`) differ; the brief's was used (one branch).
- The plan.md source (GA3 §3 GX-13) still cites `defect_detect.py:45-49`, `:81-83` and `gate_report.py:116-134`; the first two were still exact, the third had moved to `gate_adjudicate.py` (plan-v2 E16 said so).

## 2. Audit and plan
- Premise held: `OU_GATE_BASE_SHA` reaches gate_report (exported by `gate-local:189` before every report call).
- Premise held: KD-024bbecb and KD-4db6e693 no longer reproduce on eaeeb29d (`generate.test.sh` 23 OK, `premises.test.sh` 34 OK), so the fixtures are real.
- BD1 #667 harvest: nothing fit (its lifecycle part is a record `kind`, needing contract and `defects.py` record changes; the rest is the excluded adapters).
- Plan changed in one place: commit 6 also touched `defects.py` and `test_defects.py` (above), and a literal class fix (`defects.short`).
- No sub-agents: every code commit edits `defect_detect.py` and `test_defect_detect.py`; a split would only collide (recorded in the PR).

## 3. Execution (commit times from the branch)
- 01:28 skeleton + draft PR #729 + STATUS (step 0 within 3 minutes).
- 01:31 audit, 01:31 plan, 01:32 registry switches (`scripts/generate`), 01:34 recorded base + install, 01:36 touched rule, 01:39 verify-open + tool-made transitions.
- Failures, each with its class:
  - `test_adjudication_uses_the_recorded_base` errored: patching `subprocess.run` globally broke `defects.derive_owner`. Class: over-broad mock. Fixed by testing through the real function on a real repo and only forbidding `resolve_base`.
  - structure check `number 40 is written N times` (twice) and `number 12` in `defects.py`: the absolute-literal ratchet. Class: repeated literals. Fixed once per file by a named constant (`HEAD`, `OTHER`) or a helper (`defects.short`), then `literal_census.py --write` shrank the baseline. Second occurrence was a new file (defects.py), not a repeat of the same cause in the same file.
  - `test_defects.Sync...right_status` failed: it encoded the old rule "open is not verified". Expected by design; the old assertion now runs with the switch off.
- No dead ends, no waits other than the gate.

## 4. Gate
- Run 1 (pinned `scripts/gate-dev --pr 729`, head 58bed19b after merging fbc09f28): `gate: pinned verdict PASSED`, `GATE: PASSED (recorded .gate/records/58bed19b….dev.pass)`, `GATE TOTAL: 167.495s (ceiling 180s)`. Stages 7/7 PASS (no GitHub Actions workflows, generated drift, schema compat, secret scan tree/history, structure check, script tests 138.3 s). Script tests 86/86 PASS, 0 cached, no known defect needed (`known_defects: None`, no stage with `raw_result`). Advisory head-tooling run: PASSED (23.7 s, report-only). `DB path classification: db=0`.
- None of KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 or the GX-ENV env tests appeared in this selection.
- Run 2 on the RETRO head (docs-only commit; P-01: the structure check reruns).
- The first real run of the new rules is the gate itself: the pinned gate ran the base's tooling, so GX-13's adjudication runs for real only once this merges and the pinned tool root carries it. After merge: the next adjudicated gate on any PR (`dev` with `--pr`) reads `OU_GATE_BASE_SHA`; the next `scripts/defects sync` of its events moves KD-024bbecb / KD-4db6e693 `resolved -> verified` when they still pass (evidence to look for: `defect.verified` events with the recorded base sha).

## 5. Lessons
- Brief template: when a rule must appear in the published verdict, name the module that builds the verdict and its owner (here `gate_proof.stage_records`, GX-10). Owner: A Torre (brief author).
- A lifecycle rule always has a writer: a brief that adds a status transition should list `defects.py` (sync) and `test_defects.py`. Owner: plan-v2 §5.2 file map (GX-32 extends these rules next).
- Run `scripts/structure-check` before the first test run of a new test file: the literal ratchet counts test constants too. Owner: every unit (already in BRIEF STANDARD v2 (4); it caught both before push).
- Open item for GX-10: copy `raw_result` (and `defects`) from the report stage into `stage_records` so SLOs can count excused stages from the verdict (F-11).
