# LR1 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/LR1/audit.md`).
2. Plan (this file).
3. Lessons registry: contracts `lesson.v1`/`audit.v1`, `config/registry/lessons.json`, chain helper, `scripts/lib/lessons.py`, CLI `scripts/lessons` (list, show, add, apply, retire, check), unit `engine-lessons`, tests.
4. Events and effect: additive `lesson.recorded|applied|retired` v1 + `lessons.reported` v1, EVENTS.md rows, `lessons effect` (class frequency before/after `applied_at`, from the event log).
5. Retro ingestion: `lesson_ingest.py` parser (retro.md and the RETRO comment), `lessons ingest` idempotent, seeds from KD1 and GV1.
6. Aggregator and brief feedback: `lessons report` (generated `docs/process/lessons.md`, ranks classes by queue impact, emits `lessons.reported`), `lessons for-area` query, docs.
7. Registry-driven local check: `scripts/commit-check --local`, checks as data with owner and cost budget, total budget, over-budget checks moved to the gate, `.githooks/pre-push`, five seed checks, lessons kind=check feed it.
8. Retro (`docs/units/LR1/retro.md`) and RETRO comment.

## Dependency graph and owned files
`1 -> 2 -> 3 -> {4, 5} -> 6`; `7` depends only on 3's config/unit and runs in parallel with 4-6 in a separate worktree-free sub-agent (files disjoint); `8` last.
Commits are made only by the coordinator, one push each (sub-agents write files, never commit).

| Commit | Files owned |
|---|---|
| 3 | `contracts/lessons/*`, `config/registry/lessons.json`, `scripts/lib/audit_chain.py`, `scripts/lib/lessons.py`, `scripts/lessons`, `units/engine-lessons/unit.json`, `scripts/tests/{lessons.test.sh,test_lessons.py}`, `docs/process/lessons/` (empty register dir marker), generated config types, assets and gate-script-tests entries |
| 4 | `contracts/events/lesson*.json`, lock, `docs/process/EVENTS.md`, `scripts/lib/lessons_effect.py`, `scripts/tests/test_lessons_effect.py`, generated types |
| 5 | `scripts/lib/lesson_ingest.py`, `scripts/tests/test_lesson_ingest.py`, `docs/process/lessons/*` seeds |
| 6 | `scripts/lib/lessons_report.py`, `scripts/lib/lessons_brief.py`, `docs/process/lessons.md`, `docs/operations/lessons-guide.md`, tests |
| 7 | `scripts/lib/commit_check.py`, `scripts/lib/local_checks.py`, `config/registry/local-checks.json`, `.githooks/pre-push`, `scripts/tests/test_local_checks.py`, `scripts/tests/test_commit_check.py`, `docs/operations/local-gate.md`, `AGENTS.md` line, `units/engine-commit-plan/unit.json` |

## Decisions (reported, reversible)
- The register is one record per lesson (`docs/process/lessons/<id>.yml` + `<id>.audit.jsonl`), like KD1, because D-064 (a) forbids a common file. `config/registry/lessons.json` holds settings only.
- The generated `docs/process/lessons.md` is written by `lessons report` and pinned by a test, not by a `generate.json` target (a committed target owns its whole output folder and would delete `docs/operations/*`).
- Root-cause class vocabulary is a registry list (`lessons.classes`), each mapped to a D-027 parent (code, env, contract); no new vocabulary outside the registry.
- KD1's chain helpers read `defects.*`; LR1 adds a parametrized `audit_chain.py` instead of editing KD1's module (a later PR may move `defects.py` onto it).

## Premises
Premises: none registered. Working premises:
- **CRITICAL**: none (no production, money or source of truth; the local check never blocks on its own failure to run).
- (high) `commit_check.py` is a gate file: the PR body cites D-069 (D-025). Held: D-069 is recorded in DECISIONS.md.
- (medium) The event log is enough to count a class before/after (`port.read` returns the full channel); with too little history `effect` says "insufficient data", never a number.
- (medium) Retro section 5 is a numbered list in both seed retros; the parser tolerates other shapes by emitting no candidate.
- (low) A pre-push hook under the existing `core.hooksPath` needs no install change.

## Targeted tests, then one final gate
3: `lessons.test.sh`, `config.test.sh`, `structure-check`. 4: `event-contracts.test.sh`, `generate --check`. 5/6: their own test files. 7: `commit-check.test.sh`, `test_local_checks.py`. Then one `gate-dev`.

## Known base defects expected
`scripts/tests/generate.test.sh` (KD-024bbecb), `scripts/tests/premises.test.sh` (KD-4db6e693); owner engine-lane, excused by the gate.

## Amendment 2026-10-27 01:50 (A Torre, Daniel: additive, small)
`lesson.v1` gains two optional registered fields: `level` (one of `lessons.levels`: commit, pr, program, venture; absent reads as `lessons.default_level`) and `padrao_candidate` (bool, default false). They mark lessons that apply to every venture, to be lifted later into a central Padrão in A Torre. The lift is not built here. Delivered as its own commit under plan item 3 (`Plan: 3`), before item 5. No other scope change.
