# TX13 retro

## Result

- Bisect named **#658** (ui-lesson-row, merge f02bff91): 694601 -> 695469 bytes in one merge, flat to the tip f1af963d
  (audit.md table). #605 and #607 (the brief's suspects) changed nothing: 695469 on both sides.
- Cause: a client component (`PlaylistItem.tsx`) reached `@ou/site-text/text.json` through `lessonRowLabel`. A JSON
  module is not tree-shaken, so two route chunks each carried the whole text document (+434 bytes each).
- Fix (expand step): the row builders write `name` with `lessonRowLabel` on the server; the row and the rail read it.
  Head 3889cb3b: **695018 bytes, `state: ok`** (limit 695296). With the contract steps (fixture + required name):
  694535 measured.
- `git diff origin/mod/roadmap-integration...HEAD -- config/registry/budgets.json`: empty. Threshold/timeout grep: no line.

## Brief quality

- Good: the measure recipe (budgets.py, bundle_globs), the "do not raise the limit" fence, and "measure, do not guess".
- Off: the evidence pointed at #605/#607 because the first red sighting followed them. The budget itself (B1, #580)
  merged in the same train batch, so "first red" is when the check first ran on a production build, not when the bundle
  grew. Rule: a base-red brief names the first commit where the check *existed and ran*, and asks for a bisect from the
  budget's measurement commit.
- Missing: a one-lane fix was assumed possible. Here the consumer (an app-lane fixture) and the cause (ui-lane) were in
  two lanes, and a red base deadlocks a second-lane PR that must go first.

## Premises

- P-46: held (no covers manifest, gate file or aggregate touched).
- "The fix lives in one lane": broken, see Failures 2. Recovered with expand/contract.

## Why the crossing merge was green (root cause class: gate selection + ordering)

1. #658 (10-27 10:21Z) merged before any gate judged the bundle: `check-bundle` came with B1, and B1 merged at 02:53Z on
   10-28.
2. B1 set the limit from a measurement at 06:57Z on 10-27 (a2c09043 tree, 694601), then merged the base five times. Its
   later gates (ee737219, bb30c617) did not plan `build (production)`, because its diff touched no web-build input. Its head
   already measured 695469 > 695296.
3. The train judged the batch with B1, #605, #607 and #726 on the combined result (Tier 2) without a production build, so the
   budget was first evaluated by the next PR whose gate built production (#586, #742).

Rule changes (proposed, not done here):
- A PR that adds or tightens a budget re-measures it on its exact head at merge time: the gate plan selects the stage that
  produces the budget's metric whenever `config/registry/budgets.json` or the check's code changes (owner: engine-gate-plan,
  engine-lane).
- The train judges budgets on the merged result: Tier 2 runs `build (production)` + `check-bundle` when any member touches
  a web-build input or a budget (owner: train, engine-lane).

## Failures

1. First measurement run died at once: `pnpm install` from the repo root (no root package.json). Class: tooling (my
   script). Fixed: install in apps/web.
2. The first fix (required `name`) failed typecheck on the app-lane fixture (TS2741), and the ui-lesson-row contract test
   counted the fixture's new extensionless import. Class: contract (lane rule vs a cross-lane consumer). Resolved by
   expand/contract, which keeps every PR green alone.
3. `unit_check`: ui-showcase imported ui-lesson-row without declaring it. Class: code. Fixed in the same commit
   (`requires`).

Finding for the ui-lesson-row owner: the contract scan's `ADDRESS` regex
(`src/ui/lesson-row/contract.test.ts:6`, `[^".]+`) skips addresses that end in `.ts`, so imports in the `.ts` style
(`@ou/ui-lesson-row/lesson-row/copy.ts`) are never checked against `contract.ts`. Not changed here (not this unit's
cause).

4. Gate on eb22aaee: `build (test engine)` and `e2e smoke` red, classified `code`. Root cause: env. The test build runs
   `pnpm media:cache --from snapshot`, which downloads 147 objects when the offline seed is empty. Setup's seed step
   (`scripts/cloud/setup.sh:171-174`) had failed quietly (`seed_note`), so `/root/.cache/open-university/media` held 0
   files, and some downloads through the egress proxy hit the 30 s timeout (`scripts/lib/media-check.ts:53`, TimeoutError).
   It reproduced identically on the clean base 36692e98. `e2e smoke` failed only because `.next-test` was never built.
   Fixed in the environment, not the PR: re-ran `media:cache` until 147/147 were cached, then `setup.sh` re-seeded 148
   files. Rule: a gate stage that fails on a missing offline seed should classify `env`, not `code`, and setup should
   fail loudly when the media seed is incomplete (owner: engine-gate-run / gate_classify, engine-lane).
5. Gate on 60aa22e8: `unit tests` red in `apps/web/scripts/lib/architecture-engine.test.ts` ("a manifest glob means what
   scripts/lib/units.py means"): `scripts/tests/covers/battery.json` expected owner engine-battery, got none. Not this
   PR's: it fails identically on the bare base ee091f9d, passes on b475bece, and fails on 6d70f4e4 (#751 TX21, which
   moved covers ownership to the companion rule in units.py and dropped `covers/**` from engine-gate-plan, while the TS
   mirror of the glob rule was left behind). Class: base-red, engine-lane. Not fixed here (another lane).

## Gate runs

- 3889cb3b, a404f108: stopped (head moved / behind base); not verdicts.
- eb22aaee (base 36692e98): 18/20 PASS, `build (production)` PASS; `build (test engine)` and `e2e smoke` FAIL (env, item 4).
- 60aa22e8 (base ee091f9d): 19/20 PASS, including `build (test engine)`, `build (production)`, `e2e smoke` and
  `performance tests`; `unit tests` FAIL 1 of 1789 (base-red, item 5).

## Lessons

- A budget is a shared inventory: bisect from its measurement commit, not from the first red sighting (tool: a
  `budgets.py bisect <from> <to>` helper that builds and measures first-parent merges; owner engine-budgets).
- A client module must not import a generated whole-document JSON. A test that walks each `"use client"` module's
  imports and refuses `src/generated/text/` makes this structural (it lands with the ui contract step, once the
  fallback is gone; owner ui-lesson-row).
