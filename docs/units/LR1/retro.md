# LR1 retro

## 1. Brief quality
- Clear on the five parts and on ownership (LR1 never touches gate selection, caching, classification or the GV1 comment).
- Ambiguous: "measured effect from the event log" assumed gate events carry the failing class; they carry stage names and failing-test signatures only, so each lesson needs explicit `signals` and a class without one is `n/a`, not zero.
- Ambiguous: "total budget about 30 s, no literals" and "an over-budget check is moved to the gate, never deleted" left open who measures cost; decided: the check runner measures each run and the registry row keeps its budget.
- Collision: "push after every small step" against D-022 (one push per commit) is resolved only by the push guard; the brief should say the guard wins.
- Missing: the continuation brief (02:45) named a branch that differs from the launch branch (`claude/lr1-lessons-registry-2an67s` vs `claude/lessons-registry-commit-check-2d6037`); the system line and the user line disagreed.
- The audit/plan directory is `docs/units/LR1/` (upper case) while the brief writes `docs/units/<unit>/`; harmless but unstated.

## 2. Audit and plan
- Held: KD1's defects registry and its hash-chain pattern were reusable, so `audit_chain.py` was extracted instead of copied; GV1 was merged, so the commit-check change had a stable base.
- Held: event contracts are additive, so `lesson.*` and `lessons.reported` needed no version bump.
- Broke: the plan expected the retro files to be machine-readable; they are free prose, so the parser had to be keyword driven (class and kind keyword lists live in the registry, seeded by reading KD1 and GV1).
- Changed: `level` and `padrao_candidate` fields were added to the lesson record after A Torre's 01:53 note (a later central Padrão); recorded as a plan edit in `plan.md` (3 lines).
- Parallelism: the plan allowed step 7 beside steps 4-6; it ran first in the previous session (04:42), then 4, 5, 6 in sequence because they share `lessons.py` and the registry file.

## 3. Execution
Commit times (UTC): audit 04:32, plan 04:32 (two pushes), 3 registry 04:40, 7 local check 04:42, 4 events and effect 04:50, level fields 04:56, 5 ingestion 05:08, 6 aggregator 05:58.
| Event | Class | Rework / cost |
|---|---|---|
| Previous session hit the account session limit at about 02:08 local, after step 5 | quota | Resumed from the remote branch and the PR alone; nothing lost because every step was pushed. |
| Continuation: ran the whole `gate-quiet` by reflex before committing step 6 | process (heaviest path by reflex) | 522 s, 465 s of it script tests; it only showed the two registered base defects. |
| Registry written with non-ASCII escapes changed (`ã` rewritten) | tool (JSON dump settings) | Redumped with the default ASCII mode; diff shrank to the 80 added lines. |
| `scripts/generate all` prints the reference docs to stdout and the TS step needs a node build that fails in this container | env | Plain `scripts/generate` writes the python types; the intents-doc failure is the registered `generate-test-sh` defect. |
| `test_lessons_report.py` takes 42 s for 8 tests (each `config.get` shells out) | cost | Left as is; below the per-test ceiling and cached by the gate. |
| Full gate red on `e2e smoke` missing after known defects set `failed=1` | gate-lane defect (GS1/KD1) | Routed to the gate lane; not fixed in LR1. |
Dead ends: none in this session. Waits: the 9-minute full gate-quiet; the final gate (section 4).

## 4. Gate
- Local gate-quiet (before step 6 was pushed): `script tests` red only on `generate.test.sh` (KD-024bbecb) and `premises.test.sh` (KD-4db6e693, `measurement:S1` answer author), both registered base defects, untouched by this diff.
- `scripts/gate-dev --pr 575` on head 75d6bd1b (506 s, full battery: the diff touches `scripts/lib/**` and `config/**`, both `gate.full_battery_globs`). PASS: install, secret scans, generated drift, schema compat, suite union, lint, unit (1763 + 49), integration (651), typecheck, both builds, e2e browsers install, browser inventory, performance, smoke database.
- FAIL, two causes, neither from this diff: (a) `generate.test.sh` KD-024bbecb and `premises.test.sh` KD-4db6e693, both listed under `known_defects` with base 79045314; (b) `missing gate stages: e2e smoke`. Cause of (b): `scripts/gate-local` runs the `e2e smoke` step only when `failed` is 0, and the known-defect script-test exit sets `failed=1`, so the stage is never run and `gate_report` then reports it missing. The class is gate-lane code (GS1/KD1), routed there, not fixed here. `git diff origin/mod/roadmap-integration -- apps/web` is empty, so no web behaviour changed.
- Rerun on the retro head: docs only, cached; same two causes expected.

## 5. Lessons and owners
1. A continuation brief must name the one branch and the one PR; two different branch names in the system and user lines cost a check and risk a second PR (owner: A Torre, brief template).
2. Never run a whole `gate-quiet` to learn the state of two known defects; read `docs/operations/known-defects.md` and run the single test (owner: engine lane, a check in `scripts/pr-ready` that prints the registered base defects first).
3. The launch brief should say that the push guard wins over "push after every step" (owner: A Torre, brief template).
4. Retro files should carry a machine-readable lesson header (id, class, kind, owner) so ingestion does not guess from keywords (owner: engine lane, retro template and the ingestion parser in `scripts/lib/lesson_ingest.py`).
5. `config.get` shells out per call, which makes tests that read many settings slow; add a cached reader to the shared helper (owner: engine lane, helper in `scripts/lib/config.py`).
6. Event signals for a lesson should be written when the lesson is applied, so `lessons effect` can measure it; make `lessons apply` refuse a `check` or `tool` lesson with no signals unless `--no-signal` is given (owner: engine lane, check in `scripts/lib/lessons.py`).
7. A known base defect in `script tests` must not skip later stages: `gate-local` guards `e2e smoke` with `failed -eq 0` and the known-defect exit sets it, so the verdict gets `missing gate stages` and a PR that only meets known defects cannot pass on a full battery (owner: gate-lane, `scripts/gate-local` browser stage and `gate_report` missing-stage rule).
