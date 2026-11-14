# U3b media: audit

Read-only audit at launch (base `origin/mod/roadmap-integration` = `a2c09043`, which includes U3a #516, U0 #509,
CO1 #576 and the earlier U3b lanes #534, #536, #544). The branch `claude/u3b-media-addresses-k989tc` was at the
base with no commits of its own, so the restart from the merged base needs no salvage of #538.

## Scope (from the manifests)

| Unit | Paths (`units/<id>/unit.json`) | Address home | Files | Type-check files | Unit-test files | Vitest tests |
|---|---|---|---|---|---|---|
| media-application | `src/media/application/**`, `src/media/ports/**`, `src/media/testing/**` | `apps/web/src/media` | 13 | 14 | 4 | (see census) |
| media-domain | `src/media/client/**`, `src/media/domain/**` | `apps/web/src/media` | 26 | 26 | 9 | (see census) |
| media-server | `src/media/server/**` | `apps/web/src/media/server` | 29 | 29 | 11 | (see census) |

The lane's files are the 68 tracked files under `apps/web/src/media` (6 + 2 + 5 + 1 + 25 + 29 by directory). The 23
lane test files hold 82 vitest tests (`pnpm exec vitest list <files> --json`, census-base).

Every lane unit has an address (`scripts/units addresses`). `media-domain` and `media-application` share the home
`apps/web/src/media`, which holds only media-cell units, so neither is refused by GD1.

## Import census

`scripts/lib/unit_map.py` `Code.resolve_import` resolves every import specifier of the lane's files (static `import`
and `export … from`, `import()`, `require()`), and `units_of` names the unit that owns the target. Scan:
`/tmp/claude-0/.../scratchpad/u3b_scan.py` (a read-only script, not committed; its result is the table below).

- 319 import specifiers in the lane's files: 80 name third-party modules or `node:*` (not units, left alone) and 239
  name a repository file. Of those 239: 69 are same-unit imports (left as they are), 166 are cross-unit imports that
  can be rewritten, and 4 have no address target (below).
- **166 cross-unit imports that can be rewritten** to `@ou/<unit>/<path under home>`:
  - media-application: 58 (to media-domain 20, media-server 25, platform-runtime 2, kernel-runtime 2, kernel-errors and kernel-protocol and others, see scan)
  - media-domain: 32 (to kernel-runtime, kernel-ids, kernel-limits, kernel-protocol, kernel-errors, kernel-tables, site-domain)
  - media-server: 76 (to media-domain 39, kernel-runtime, kernel-limits, kernel-protocol, kernel-ids, kernel-errors, platform-runtime, db-core, db-media, catalog-hierarchy, testing-support, admin-server, fidelity-references, tooling-media)
- **4 imports with no address target (contract gaps, left relative):**
  - `apps/web/src/media/domain/direct-delivery.test.ts` → `apps/web/next.config.ts`: unit `web-build` has no address (its home is the project root; `scripts/units addresses` reason: "gets an address when it has its own directory").
  - `apps/web/src/media/testing/in-memory-media.ts`, `media-contract.ts`, `media-contract.test.ts` → `apps/web/src/platform/db/testing/in-memory-uow.ts` and `uow-contract.ts`: no unit owns those paths (`units_of` is empty), so there is no `@ou/` address for them. For db-core's U4 (or a unit that owns `platform/db/testing/**`).

## Evidence that the rewrite is safe

- Baseline batteries (before any change): `scripts/unit-battery media-application` green (types 14 files, unit-tests 4 files,
  4.22 s); `media-domain` green (26 files, 9 files, 3.40 s); `media-server` green (29 files, 11 files, 8.49 s).
- Vitest census of the lane's tests before the change: 82 tests in 23 files.
- Existing merged U3b lanes already use the same form, e.g. `apps/web/src/config/server/deps.ts`:
  `import { buildWithoutDatabase } from "@ou/db-core/database-env.ts";` (the `.ts` extension is kept).
- The lane has no `vi.mock`, `vi.doMock` or `require` with a relative or aliased specifier (checked by grep); the
  only `vi.mock` names `next/cache`.
- `scripts/lib/unit_addresses.py` `check` refuses an address whose file belongs to another unit; every rewrite below
  resolves to a file of the target unit (`units_of(target) == [unit]`), so `structure-check` should pass.

## Known base defects that could touch this PR

None identified in the lane's tier-1 battery. The known timing-sensitive tests (tower-catalog cover concurrency,
read-latency) are not in the lane and are not run by the battery.

## Premises checked

- P-03 (stable addresses): a unit is imported by `@ou/<id>`, so moving it changes only the map. Confirmed by the U3a
  merge (`scripts/units addresses` produces an address per lane unit).
- P-13 (no two lanes edit the same file): every file this PR touches is owned by exactly one lane unit (`scripts/units
  owner <path>` = media-lane). The PR touches no file of another lane.
