# U3b testing lane: audit (read-only)

Lane `testing-lane`, units `testing-e2e` (`apps/web/e2e/**`) and `testing-support` (`apps/web/test/**`). Base:
`origin/mod/roadmap-integration` at `a2c09043` (CO1 #576 merged). U3a #516 (`scripts/units addresses`, the `@ou/` map,
`scripts/unit-battery`) is merged. Old branches `claude/u3b-*` are reference only; the work branch is a fresh branch
from the base, and no old commit is reused.

## Inventory

- Tracked files under the two units: 101 (`e2e/` 36 + `e2e/fixtures/` 9; `test/` 8 + `test/fixtures/` 8,
  `test/int/` 36, `test/lint/` 1, `test/meta/` 2, `test/site/` 1). Only TypeScript files carry imports.
- Import forms in the lane: static `import … from`, `export * from`, dynamic `import()`, `vi.mock` / `vi.doMock` /
  `vi.importActual` / `vi.doUnmock` (the regex of `scripts/lib/unit_map.py` `TS_IMPORT` does not cover the `vi.*`
  forms; the rewrite covers both).
- Specifier kinds found: relative into another unit (`../../src/…`, `../src/…`, `../../scripts/…`,
  `../../public/…`, `../../next.config.ts`, `../../design/…`), the alias `@/progress/domain/rules.ts`, and the
  tsconfig keys `@tower/catalog`, `@tower/media`, `@tower/playback-engine` (these three map to `src/release/server/…`
  and `src/playback/client/…`). No `@ou/` import exists in the lane yet.

## Evidence of the rewrite (dry run of the script, not committed)

The rewrite resolves every lane specifier with the unit map's own resolver (`unit_map.Code.resolve_import`, the
tsconfig `paths` as the only alias source), finds the owning unit of the target with `units.unit_of`, and writes
`@ou/<owner>/<path relative to the owner's home>` when the owner has an address and the target lies under its home.

| Result | Count |
|---|---|
| specifiers to rewrite | 271 (in 62 files; by owner: 34 units, largest `db-catalog-store` 22, `media-server` 22, `db-media` 20, `tooling-db` 20, `catalog-application` 19) |
| same-unit specifiers (lane to lane), kept as written | 103 |
| specifiers that do not resolve to a tracked file | 0 |
| gaps (kept relative, listed as contract gaps in the PR body) | 6 specifiers in 4 files, 4 causes |

Gap causes (none can be addressed without editing another unit, which is out of scope):

1. `web-build` has no address (its home is the project root `apps/web`): `e2e/specimen.spec.ts` →
   `design/figma-tokens.snapshot.json`; `test/site/noindex.test.ts` → `next.config.ts`. Owner for U4: `web-build`.
2. `app-api` has no address: its home is `apps/web/src`, which holds units of other cells (GD1, U3a). It owns
   `src/app/api/health/route.ts`, imported by `test/int/catalog-admin-flow.int.test.ts` and
   `test/int/tower-catalog.int.test.ts`. Owner for U4: `app-api` (give `proxy.ts` and the health route their own folder).
3. `src/platform/db/testing/uow-contract.ts` is in no unit (`test/int/executable-contracts.int.test.ts`). Owner for
   U4: the `db-*` lane (ownership of the file is missing).
4. `public/fonts/manifest.json` is in no unit (`test/meta/fonts.test.ts`). Owner for U4: the lane that owns `public/`.

## Risks checked

- **Tooling resolution.** The U3b history records that Node-run tooling cannot resolve `@ou` (D-069 item 7); the lane's
  files run under vitest (its `alias` derives from the tsconfig `paths`), Playwright (honours tsconfig `paths`) or
  `scripts/tests/*.test.sh`. The unit battery and the gate are the check: any file run by plain Node keeps its relative
  import and is listed.
- **Ownership.** Each edited file is owned by a lane unit (`scripts/units owner`); no file of another unit is edited.
- **Type-check and census.** Baseline runs of `scripts/unit-battery testing-e2e` and `testing-support` at the base are
  started before any edit; the after-run must match (same files, same test count, zero type errors).
- **Known timing-sensitive tests** (tower-catalog cover concurrency, read-latency) are not changed.

## Premises consulted

- P-03 (validated, radius high): a unit is imported only through `@ou/<id>`. Confirms the target form.
- P-13 (inferred, radius medium): one lane per unit. The lane edits only its two units' files.

## Brief quality

- The brief's branch name `mod/u3b-testing-addresses` conflicts with the harness's designated branch
  `claude/u3b-testing-addresses-8ea1lc`. The designated branch is used (it equals the base head: no old work on it).
- The brief names P-03 and P-13 but not their status; P-13 is only `inferred` in the register.
- The brief's `scripts/units who <unit>` is correct; `scripts/units owner <path>` is the one to check each file.
