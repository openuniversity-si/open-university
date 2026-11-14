# LP3 retro — fold, validate and log the live plan

1. **Brief:** clear scope and file fences. Two gaps: it says "python-test discovery" runs `scripts/tests/test_*.py`, but the
   gate runs only `*.test.sh` listed in `gate-script-tests.json` (forbidden to edit, GX-08 sidecars not merged), so
   `test_plan_live.py` rides `program.test.sh`. It names `mod/lp3` while the harness bound `claude/lp3-…` (audit L12): worked on `mod/lp3`.
2. **Audit and plan:** premises held: the fixture digests recompute with the runbook formula, so the fixture was right
   (no CANDIDATE needed). Ops with no `args` shape in the contract (reorder, records) were defined in the module docstring.
   Plan unchanged: 6 items, sequential (one file), no sub-agents.
3. **Execution (UTC):** 18:53 audit/plan → 18:57 fold, validate, log (written whole, then committed in three green
   slices) → 18:58 CLI → 18:59 literal fix → 18:59 base merge (20 behind). One failure class: the literal census (LT1)
   refused numbers in `program.py` (`indent=2` a third time) and in the test (versions, `'0' * 64`, `parents[2]`).
   I pushed commit 5 before running structure-check, so the gate would have found it. Fix: one `dump()` helper for every
   human JSON view, and tests derive numbers from the fixture. Lesson: run `scripts/structure-check` (census included)
   before every push. The pre-push local checks do not run the census on new files.
4. **Gate:** run 1 `gate-dev --pr 711` on `e45fc996`: PASSED 95.7 s, script side only (the area plan ran no web stage).
   The verdict run is the full web battery (`gate-local --dev --sha`) on the retro head, see the PR comment.
5. **Lessons:** (a) the brief template should say "Python tests run through a listed `*.test.sh` runner" until GX-08
   (owner: A Torre, brief template); (b) `local-checks.json` should include the literal census for changed files, so
   the push is refused before the gate (audit S2, owner GX-15); (c) `program.v1` has no per-unit estimate, so
   `set_estimate` is a record only. LP10 may want a field (additive v1, owner LP2/contracts).
