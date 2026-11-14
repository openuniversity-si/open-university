# U3b identity: audit

Lane `identity-lane`, unit `identity` (`units/identity/unit.json`, paths `apps/web/src/identity/**`). Read-only audit;
no source changed. Base: `origin/mod/roadmap-integration` at `a2c09043`, which already contains U3a (the generated
`@ou/*` map), U2, U1, K1, T1 and LR1/CO1.

## Scope and baseline

- 25 files under `apps/web/src/identity`, 7 test files, 75 tests (vitest census on the clean base: all 75 pass).
- `scripts/unit-battery identity` on the clean base: `types` ok (26 files, tsc output empty), `unit-tests` ok (8 files),
  under the 10 s limit (4.1 s). The battery's unit-test count (8) is one more than the test files vitest reports (7);
  the census above is the count to hold steady.

## Cross-unit imports (what U3b rewrites)

`scripts/units addresses --json` lists each target's importers. Filtered to identity's files, 31 import sites cross
into eight units, plus one `@/` alias (`client/AuthProvider.tsx` imports `@/kernel/cache.ts`):

| Target unit | Address | Sites | Files imported |
|---|---|---|---|
| kernel-errors | `@ou/kernel-errors/` | 5 | `errors.ts`, `error-codes.ts` |
| kernel-protocol | `@ou/kernel-protocol/` | 2 | `protocol.ts` |
| kernel-runtime | `@ou/kernel-runtime/` | 10 | `env.ts`, `cache.ts` (also via `@/`), `brand-ids.ts`, `intents.ts` |
| kernel-tables | `@ou/kernel-tables/` | 2 | `tables.ts` |
| platform-runtime | `@ou/platform-runtime/` | 6 | `host/vercel.ts`, `host/request-address.ts`, `observability/logger.ts`, `observability/context.ts` |
| db-contexts | `@ou/db-contexts/` | 2 | `db/identity/index.ts` |
| db-core | `@ou/db-core/` | 2 | `db/database-env.ts`, `db/pool.ts` |
| site-domain | `@ou/site-domain/` | 2 | `site/domain/origin.ts` |

## Contract gaps

None. `scripts/units owner <file>` gives each imported file exactly one owner, and it is the unit the import names
(e.g. `apps/web/src/kernel/error-codes.ts` is owned by `kernel-errors`). So every rewrite is an address the target
already exports; nothing is missing from another unit's address, and no other unit is edited.

## Exceptions found

- `apps/web/src/identity/domain/intents.ts` imports `../../kernel/intents.ts` (type) and `../../kernel/tables.ts`
  (`TABLE`, a value). `scripts/intents-doc.ts` (`pnpm intents:generate`) runs under plain `node` and imports this file
  through `apps/web/scripts/lib/intents.ts`. Node's native TypeScript loader does not read tsconfig `paths`, so an
  `@ou/*` import there fails with `ERR_MODULE_NOT_FOUND`. This is the same case as the config and catalog domain files
  kept relative by the earlier U3b PRs (commit `3c0ffb84`, D-069 item 7). Decision: this one file keeps its two relative
  imports; the PR body lists it. A Node resolver for `@ou/*` is a tooling change for a different owner.
- Relative `../../` lines that are not imports (the `readFileSync(join(root, "src/identity/..."))` source reads in the
  tests) are not specifiers and stay as they are.
- Same-unit `@/identity/...` imports (e.g. `client/AuthProvider.tsx` importing `@/identity/ports/sign-in`) stay: the
  brief keeps imports inside the unit as they are.

## Architecture rules touched

- `L3.provider-boundary` (only `identity/server/` imports `better-auth`): not affected; no provider import changes.
- `L7.identity-domain` (`identity/domain/` does not import `site/`): the one `site` import is in `domain/settings.test.ts`
  (test file). After the rewrite it is `@ou/site-domain/origin.ts`. The architecture check resolves `@ou` through the
  same map, so it is checked by the gate, not assumed.

## Premises relied on

- P-03: units are addressed by `@ou/<id>`; moving a unit changes only the map. (high radius: a wrong address breaks
  every importer.)
- P-13 (as listed in the brief): the rewrite is mechanical; no behaviour change. If an address resolves to a different
  file than the relative path did, the type-check or the unit tests fail.
