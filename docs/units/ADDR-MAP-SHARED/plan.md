# ADDR-MAP-SHARED plan

`apps/web/tsconfig.paths.json` is the output of `scripts/generate addresses` and the input of `apps/web/tsconfig.json`,
`apps/web/vitest.config.ts` and `apps/web/scripts/lib/ou-addresses.mjs`. A unit that gains `contract.entry` gains an
`@ou/<id>` address, so the generator rewrites this file; but the file lived in `web-build`'s `paths` and not in its
`shared`, so every such change was `lane undecidable` (`#592`). The fix is one declaration, in the same field its two
neighbouring web configs already use.

## Commit plan
- [ ] 1. Audit: `docs/units/ADDR-MAP-SHARED/audit.md` — the refusal quoted, the file's three readers, the effect measured.
- [ ] 2. Plan: this file, mirrored in the PR body.
- [ ] 3. `units/web-build/unit.json` declares `apps/web/tsconfig.paths.json` shared, and
  `scripts/tests/test_units.py::test_lane_own_the_census_and_the_web_config_are_shared` names the three-entry list.
- [ ] 4. Retro: `docs/units/ADDR-MAP-SHARED/retro.md`.

## Dependency graph and critical path
- 1 → 2 → 3 → gate → 4. No parallelism: three files, one of which is the test of the other two.
- Critical path: 3 (2 min) → gate-dev (≈ 15 min) → 4 (5 min).

## Premises
- The generator writes this file and nothing else writes it: `config/registry/generate.json` names the target
  `addresses` with output `tsconfig.paths.json` (audit, cited readers). Radius: low, the change is one list entry.
- Declaring a path shared does not stop `refusals()` from demanding the owner's approval on it; that half is
  `SHARED-NEEDS-NO-OWNER` (`#778`). Radius: medium for `#592` (it needs both), none for the lane rule this repairs.

## Tests per commit
- 3: `python3 -m unittest scripts.tests.test_units` — 19 tests, including the three-entry assertion. Mutation: drop the
  new entry from the manifest and show the test failing alone; restore and show green.
- Final: one `scripts/gate-dev --pr <number>` on the head.

## Known base defects expected
Read from `docs/operations/known-defects.md` at gate time; none touch `units.py` or the lane rule.

## Cheapest useful effort
Action: the final `scripts/gate-dev --pr <number>` on the PR head, plus the one mutation of the manifest entry.
Cost: about 20 min wall and one gate run.
Requirement: Daniel needs the merge door, because `#592` and the ten other address PRs stay refused until this lands and he is the one waiting on them.
Cheaper rejected: pushing the declaration without running the suite (the test asserts the exact list, so a drifted manifest would only show at the gate); skipping the mutation (it is one edit and it proves the test reads the manifest, not a copy).

Premises: none
