# GX-38 RETRO

## 1. Brief quality
- Branch name conflict: the brief says `mod/gx38`, the session designates `claude/gx38-driver-hooks-uoctn4`; the designated one was used and recorded. Lesson: the launcher should pass one branch name (owner: coordinator).
- "Pre-claim every new path" is partly moot: only production files need an owner (`unit_check.ownership`); registry, contract and docs paths are owned by no unit, so those claims are cosmetic. The brief did not say so; the audit found it.
- Missing from the brief: a new script under `scripts/lib/` also needs a `docs/structure/assets.json` entry (structure check) — cost one gate run.

## 2. Audit and plan
Premises held: GA-PG1 seam is behaviour-preserving (report and v3 payload read explicit stage fields, so the extra `started_at` key does not reach the payload). The plan ran sequentially; fan-out was not worth it for ~100 changed lines.

## 3. Execution (commits are on the PR)
1 audit, 2 plan, 3 hooks, 4 started_at, 5 pre-claims. Failures, by class:
- Engine literal census (`gate-runner.sh`: 1000 and 3 over the allowed counts): my `started_at` repeated `/ 1000` and `round(..., 3)`. Fixed by reusing the stage `seconds` and dropping the round (no baseline edit).
- `docs/structure/assets.json` had no entry for the six hook scripts: added one glob entry.
- PR body checklist format (`- [ ] 1. ...`) and base 5 commits ahead: body fixed, base merged (merge commit).
Dead end: none. Wait time was gate wall time (~4 min first run, ~40 s scoped runs).

## 4. Gate
Runs of `gate-dev --pr 700`: run 1 (own and base-tip) failed on structure check (assets, literals) and script tests (literals census, structure-check test, plus known env: root-identity/uid-65534 fs-encoding); run 2 failed on PR body plan format and base behind; run 3 passed on both the base-tip checkout (verdict of record) and the own checkout (report-only). No known base defect was hit in the passing runs.

## 5. Lessons
- Add "new scripts need an assets.json entry" and "an engine script edit must not repeat a numeric literal" to the brief template for gate-engine units (owner: coordinator / brief template).
- A shared helper for stage-record fields would avoid literal repetition in `gate-runner.sh` (owner: GX-10, which adds more fields).
- Unit ownership vs. cosmetic claims: document in STRUCTURE.md that registry/contract paths need no manifest claim (owner: structure).
