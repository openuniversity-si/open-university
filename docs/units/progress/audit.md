# U3b progress: audit

Lane `progress-lane`, unit `progress` (`units/progress/unit.json`, home `apps/web/src/progress`, cell `progress`).
Read-only audit of the progress unit's files before any import is changed. Evidence from `scripts/units addresses`,
`scripts/units owner <path>`, `rg` over `apps/web/src/progress`, and the generated `apps/web/tsconfig.json` `paths`.

## Scope

- 20 files under `apps/web/src/progress/` (15 source, 5 test). Test census before the change: 5 test files, 20 `it`/`test`
  call sites (`rg -c "^\s*(it|test)(\.each)?\("`).
- Only imports that cross a unit boundary change. Imports inside `progress` (`./`, `../domain/…`, `../ports/…`) stay.

## Cross-unit imports (22)

| File | Import | Owning unit | Address after U3b | Action |
|---|---|---|---|---|
| `client/client.ts` | `../../kernel/cache.ts` | kernel-runtime | `@ou/kernel-runtime/cache.ts` | rewrite |
| `client/client.ts` | `../../kernel/protocol.ts` | kernel-protocol | `@ou/kernel-protocol/protocol.ts` | rewrite |
| `domain/rules.ts` | `../../kernel/extent.ts` | kernel-limits | `@ou/kernel-limits/extent.ts` | rewrite |
| `domain/view.ts` | `../../kernel/extent.ts` | kernel-limits | `@ou/kernel-limits/extent.ts` | rewrite |
| `domain/intents.ts` | `../../kernel/intents.ts` | kernel-runtime | `@ou/kernel-runtime/intents.ts` | rewrite |
| `domain/intents.ts` | `../../kernel/tables.ts` | kernel-tables | `@ou/kernel-tables/tables.ts` | rewrite |
| `application/viewer.ts` | `../../platform/observability/logger.ts` | platform-runtime | `@ou/platform-runtime/observability/logger.ts` | rewrite |
| `application/viewer.ts` | `../../identity/application/session.ts` | identity | `@ou/identity/application/session.ts` | rewrite |
| `server/handler.ts` | `../../kernel/extent.ts` | kernel-limits | `@ou/kernel-limits/extent.ts` | rewrite |
| `server/handler.ts` | `../../kernel/javascript.ts` | kernel-protocol | `@ou/kernel-protocol/javascript.ts` | rewrite |
| `server/handler.ts` | `../../kernel/cache.ts` | kernel-runtime | `@ou/kernel-runtime/cache.ts` | rewrite |
| `server/handler.ts` | `../../kernel/protocol.ts` | kernel-protocol | `@ou/kernel-protocol/protocol.ts` | rewrite |
| `server/handler.ts` | `../../platform/observability/context.ts` | platform-runtime | `@ou/platform-runtime/observability/context.ts` | rewrite |
| `server/handler.ts` | `../../platform/observability/logger.ts` | platform-runtime | `@ou/platform-runtime/observability/logger.ts` | rewrite |
| `server/deps.ts` | `../../platform/db/progress/index.ts` | db-contexts | `@ou/db-contexts/progress/index.ts` | rewrite |
| `testing/in-memory-progress.ts` | `../../platform/db/uow.ts` | db-core | `@ou/db-core/uow.ts` | rewrite |
| `testing/progress-contract.ts` | `../../platform/db/uow.ts` | db-core | `@ou/db-core/uow.ts` | rewrite |
| `server/handler.test.ts` | `../../catalog/testing/fake.ts` | catalog-application | `@ou/catalog-application/testing/fake.ts` | rewrite |
| `testing/in-memory-progress.ts` | `../../platform/db/testing/in-memory-uow.ts` | none (`-`) | none | contract gap |
| `domain/view.test.ts` | `../../../test/fixtures/progress-oracle.ts` | none (`-`) | none | contract gap |
| `testing/progress-contract.ts` | `../../platform/db/testing/uow-contract.ts` | none (`-`) | none | contract gap |
| `testing/progress-contract.test.ts` | `../../platform/db/testing/uow-contract.ts` | none (`-`) | none | contract gap |

Totals: 18 rewritable, 4 gaps. The 4 gaps point at files no unit owns (`scripts/units owner` prints `-`), so there is no
`@ou/<id>` to name. (The first audit pass missed `progress-contract.ts`'s second import; this line corrects it.) They are listed for the owner of `platform/db/testing` and `test/fixtures` (U4 or a later unit
manifest), not edited here.

## Premise checks (cheap evidence)

- **Every target is addressed.** Each rewritable target's unit has an address in `scripts/units addresses --json`
  (`kernel-runtime`, `kernel-protocol`, `kernel-limits`, `kernel-tables`, `platform-runtime`, `identity`, `db-core`,
  `db-contexts`, `catalog-application`). The `tsconfig.json` `paths` carry the `@ou/<id>/*` wildcard for each.
- **Shared homes are safe.** `kernel-*` units share the home `apps/web/src/kernel`, so the address is
  `@ou/kernel-<x>/<file>`; structure-check refuses only an address whose file belongs to another unit, and every
  rewritten file belongs to the unit named in its address (checked by `scripts/units owner`).
- **Cell stays intact.** The progress home holds only progress units (cell `progress`); the targets' homes are not
  widened by this change (no file is added or moved).
- **Requires vs. imports (noted, not changed).** `progress` declares `requires` for `db-contexts`, `identity`,
  `kernel-limits`, `kernel-protocol`, `kernel-runtime`, `kernel-tables`, `platform-runtime`. It also imports
  `kernel-runtime` (cache, intents), `kernel-protocol` (javascript), `db-core` (uow) and `catalog-application` (test
  fake only). `db-core` and `catalog-application` are not in `requires`. This PR does not change the manifest; the gap
  goes into the PR body for the unit owners.

## Test census (before the change)

- Test files: 5. Test call sites: 20 (`view.test.ts` 3, `rules.test.ts` 10, `maintenance.test.ts` 1,
  `handler.test.ts` 5, `progress-contract.test.ts` 1).
- Type-check and unit battery baselines are recorded in the PR body (`tsc --noEmit` and `scripts/unit-battery progress`).

## Known base defects

- None known for this unit at base `a2c09043`. The timing-sensitive tests named in the brief (tower-catalog cover
  concurrency, read-latency) are not in `progress`.

## Lessons read

- `scripts/lessons for-area apps/web/src/progress` returned `lessons: none applied for this area`.
- Baseline `tsc --noEmit` at `a2c09043` (apps/web): exit 0, no output.
