# LP7 plan: wire the lost inputs (Decision D-071, Premises: P-51)

Critical path: 1 -> 2 -> 3 (sequential, ~25 min; small enough that sub-agents cost more than they save; all edits are in
disjoint files but one writer).

1. audit + plan docs (this commit). Files: docs/units/LP7/*.
2. premise.* through the port (`scripts/lib/premises.py`, `scripts/tests/test_premises.py`). `--no-emit` prints; an
   unreachable forge prints with a warning. Test: fake adapter.
3. `lessons.apply_lesson` (idempotent, by plan decision, audit line, lesson.applied) + `lessons_brief.brief_lines`
   (`scripts/lib/lessons.py`, `lessons_brief.py`, `scripts/tests/test_lessons_apply.py`).
4. retro (`docs/units/LP7/retro.md`).

Premises: P-51 (the planner calls these paths; blast low, reversible). CRITICAL: none.
Tests: test_premises.py, test_lessons*.py, structure-check, `scripts/program check live-planning`; one gate at the end.
Known base defects: none touched.
