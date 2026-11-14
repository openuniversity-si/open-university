# U3b audit: site-lane imports to `@ou` addresses

Read-only audit before any code commit (lane `site-lane`, units `site-domain` and `site-server`).

## Evidence

- Base: `origin/mod/roadmap-integration` at `a2c09043`. U3a (addresses, unit battery) and the other U3b lanes
  (app-home, app-course, app-api, app-universities/app-authors) are already merged; this lane follows their pattern.
- `scripts/units addresses --json` (U3a) lists, per target unit, the importers that still name its files by path.
  Filtering it to importers under `apps/web/src/site/` gives the site rows, which were cross-checked with a direct
  scan of every `.ts`/`.tsx` under `apps/web/src/site/` owned by the two units (`scripts/lib/units.py` `unit_of`).
- Both units own `apps/web/src/site/domain/**` (site-domain) and `apps/web/src/site/{application,ports,server,testing}/**`
  (site-server). `site/guard.ts` and other unowned files under `site/` are out of scope and have no imports to rewrite.

## Findings

- 52 cross-unit import specifiers in the owned files (`from`, `import()`, `vi.mock`, `require`):
  - 48 rewritable to `@ou/<unit>/<path>`, where the target unit has an address (`tsconfig.json` `@ou/*` keys).
  - 4 are gaps that cannot be rewritten in this PR (see below).
- Three alias forms appear: relative (`../../kernel/errors.ts`), `@/` (`@/catalog/testing/fake`, `@/release/domain/queries`)
  and no `@tower/` alias. Same-unit relative imports (`../domain/site-data.ts` from `site-server`, `../domain/...` inside
  `site-domain`) are a cross-unit import between the two units, so they are rewritten too; imports inside one unit stay.
- Gaps (not edited, listed in the PR body as contract or manifest gaps for their owners):
  1. `apps/web/src/site/domain/hosts.test.ts` imports `../../../next.config.ts`. Its unit `web-build` has no address
     (its home is the project root, see UNITS.md), so the address form does not exist yet.
  2. `apps/web/src/site/server/site-data.ts` reads `../../../content/site/site-data.v2.json`. That is data, not a unit
     file; no unit owns `content/site/`.
  3. `apps/web/src/site/testing/site-contract.ts` and `site-contract.test.ts` import
     `../../platform/db/testing/uow-contract.ts`. No manifest owns `apps/web/src/platform/db/testing/**`
     (`unit_of` returns none), so the platform owner must give it a unit.
  4. Same file set, the `@/` and relative imports of `kernel/*` into `site/` are already addressable and are rewritten (not a gap).

## Baseline (before any edit)

- `scripts/unit-battery site-domain --json`: result ok, types 28 files ok, unit-tests 13 files ok, 9.8 s (limit 10 s).
- `scripts/unit-battery site-server --json`: result ok, types 16 files ok, unit-tests 4 files ok, 8.2 s.
- Both batteries are the tier-1 gate for this lane (`scripts/unit-battery` exists, U3a).

## Risks

- A rewritten specifier must resolve to the same file. Checked by construction: the new address is built from the
  resolved file path under the target unit's home, and the scanner rejects files outside it.
- `vi.mock` and `import()` specifiers are rewritten too; a missed one would still resolve by path and only fail the
  structure check, so the battery and the gate both exercise them.
