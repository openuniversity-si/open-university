# TX21 — retro

Decision D-070, Premises P-46. Lane engine-lane. Base 891b835ae. PR #751, head branch `mod/tx-owners`.

## Brief quality
Precise on evidence (every cited file, line and count held on the base) and on file ownership. One tension it did not
resolve: "the same effective owner for every tracked path" (strict, the empty owner set included) versus "no PR
conflicts on CODEOWNERS". Under strict equivalence a minimal file must still spell every owned/unowned boundary, so
it cannot stop the churn caused by claims inside unowned-majority directories (config/registry, contracts/events,
docs/*) or by unclaimed tests inside owned ones. The strict reading was kept (safe, reversible); the zero-churn option
is a proposal below.

## Delivered
- Companion rule (units.companions, derived): `scripts/tests/covers/<t>.json` belongs to the unit of
  `scripts/tests/<t>.test.sh`; same-unit claim allowed; a foreign claim names `units/<id>/unit.json:<line> "<glob>"`
  and the rule. engine-gate-plan dropped `scripts/tests/covers/**`. #740's head replayed with the rule: its
  double-claim error is gone once this merges; before the glob is dropped it reads
  `… remove units/engine-gate-plan/unit.json:23 "scripts/tests/covers/**" (D-067 (6))`.
- Unowned production file: the error names the unit(s) owning its directory's other files (same message as before
  when there are none, so the old fixture still matches exactly).
- CODEOWNERS: smallest directory cover, 953 → 120 rows, proven equivalent to the former spelling for every tracked
  path. A path added to a manifest inside its lane's region leaves it byte-identical (real-repo probe: new
  `scripts/lib/tx21_probe.py` claimed by engine-units → CODEOWNERS diff empty). It ships behind
  `generate.codeowners_minimal` (default off): the committed file stays the former spelling until a follow-up PR
  flips the switch and regenerates (see Failures).

## Premises
- CRITICAL "no ownership check is weakened": held. Assertion counts of the shared tests before/after:
  test_generate 81/81, test_units 32/32, test_unit_check 25/25, test_unit_map 25/25 (test_generate: two row-shape
  assertions restated for the new spelling, same count). New: test_codeowners_minimal 16, test_units_companion 22.
- CRITICAL "same owner set for every tracked path": held by `test_codeowners_minimal.Repository`.
- "The train's lane reader ignores unclaimed files": held (`train_ownership.lane_of`), so the 7 covers of unclaimed
  tests, now unowned, add no lane.

## Failures (root-cause class)
- Fixture paths written as JSON on one line gave every glob line 1: the line-number test needed indented manifests
  (test design).
- Literal census refused `indent=2`, `parents[2]` and a slice `[:3]` in unowned new test files (code: no literal in
  scripts/**); fixed with `indent='  '`, `parent.parent.parent` and a constant path.
- Minimal cover first emitted dir rows without the leading `/` (code); caught by reading the output, then fixed.

- **Pinned gate, `generated drift` (contract between P-46 and a generator change):** run 1 on 549607bc failed only
  `CODEOWNERS: differs from its regeneration`. The pinned gate renders committed targets with the base's generator,
  so one PR can never change a committed spelling and its generator together. Fixed by the switch (default off; the
  base generator's `--check` on this tree exits 0); the flip is a one-line follow-up after merge. Class fix: any PR
  changing a committed generator's output needs the same two steps.

## Gate runs
1. 549607bc: pinned verdict FAILED, `generated drift` only (every other stage passed, script tests 284 s).
2. Final head: result in the RETRO comment and MERGE-READY.

## Lessons
1. Strict CODEOWNERS equivalence bounds the churn gain: replay of the last 80 base merges, legacy changed on 26
   pairs, the minimal file on 21, and 10 of those are PRs that never touched a manifest (an unclaimed test, or a
   pre-claimed file created later). **Proposal for Daniel (owner: Daniel, source-of-truth decision):** give paths no
   unit claims a fallback owner (one `* @the-owner` row while every lane shares that identity). CODEOWNERS would then
   change only when an identity changes: zero churn, but ~900 non-production paths that have no owner today would
   get one.
2. A committed generated file and its generator cannot change in one PR under the pinned gate. **Rule (owner:
   engine-lane, gate docs):** ship the new renderer behind a registry switch, default off, and flip it in a follow-up;
   name the follow-up in the PR.
3. A derived rule beats a central glob: the companion rule removes the class of #740 (two units claiming one
   sidecar) instead of the instance. Rule change for every unit: never list `scripts/tests/covers/<t>.json` in a
   manifest; it follows its test (owner: engine-lane).
