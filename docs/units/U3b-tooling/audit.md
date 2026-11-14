# U3b tooling lane: audit

Read-only audit before the first code commit (D-067 (1), P-03, P-13; plan v3 §9.2 row U3b). Branch
`claude/u3b-tooling-addresses-nvjjtx`, base `origin/mod/roadmap-integration` at `a2c09043` (CO1 #576 merged). U3a
(`scripts/units addresses`, `scripts/unit-battery`) is merged; other lanes' U3b rewrites (factory, release-server,
identity, playback, progress, app, config) are merged.

## Scope

Units owned by `tooling-lane` (`units/<id>/unit.json`): tooling-brand, tooling-catalog-cli-content,
tooling-catalog-cli-core, tooling-catalog-cli-media, tooling-catalog-cli-ship, tooling-checks, tooling-db,
tooling-docs, tooling-entrypoints, tooling-literals, tooling-media, tooling-perf, web-build.

## Evidence (commands and counts, measured on the base)

- `scripts/units addresses`: every tooling unit except `web-build` has an address `@ou/<id>` (`apps/web/scripts`,
  `apps/web/scripts/lib/catalog-cli`, `.../catalog-cli/commands`). `web-build` has none (its home is the project root,
  U0/U3a rule). `tooling-checks`, `tooling-docs` and `ui-tokens`-style units with no cross-unit path import are already
  addressable.
- Cross-unit imports in the lane's files (relative, `@/`, `@tower/*`, `vi.mock`-style specifiers resolved through the
  tsconfig aliases): **459** specifiers resolve to a file of another unit. 75 of them are in files that may be
  rewritten (22 files); 384 are in files Node runs directly (77 files, see below); 6 are unresolved (fixture strings
  inside tests, JSON and similar); 3 target `scripts/check-architecture.mjs`, which belongs to
  `engine-architecture-check`, a unit outside the TypeScript project with no address; 1 is a JSON file with no owner.
- **Node-run files cannot use `@ou/`.** `scripts/tower-catalog` runs `apps/web/scripts/tower-catalog.ts` with the pinned
  `node` (native TypeScript stripping), and `tower-factory`, the catalog-bake and the other `apps/web/scripts/*.ts`
  entries run the same way. Node does not read tsconfig `paths`, so `@ou/...` fails with `ERR_MODULE_NOT_FOUND`. The
  precedent is `3c0ffb84` (U3b config): the domain files Node loads stay relative until a Node resolver for `@ou/*`
  exists. The graph reached from the top-level scripts through relative imports is 384 specifiers in 77 files,
  nearly the whole `catalog-cli` tree, `media-cli`, the literal census and the db scripts.
- The test census (`vitest list`, projects `unit`, `int`, `perf`, `perf-int`) and `tsc --noEmit -p apps/web/tsconfig.json`
  were recorded before any edit (`tsc` exit 0, no output; unit 1256 lines, int 259, perf 20, perf-int 5). Files are in
  the scratch directory of the session, not committed.
- Existing `@ou/` uses in `apps/web/scripts`: none. So no file in the lane already uses an address.

## Findings

1. The mechanical rewrite can land only in files Node does not run: the tests and the non-Node modules. 22 files,
   75 specifiers. The remaining 384 specifiers stay relative and are a contract gap (below).
2. Specifier style is the one of the earlier U3b commits: `@ou/<id>/<file-relative-to-home>.ts`, the extension kept.
   The home of each address is taken from `scripts/units addresses`; the file must belong to the target unit
   (`scripts/units check` enforces it).
3. Tests run under vitest (aliases from tsconfig), so their `@ou/` imports resolve. A heavy test that spawns the
   catalog CLI spawns Node on the CLI's relative graph, which is still relative; that is the gap, not the test.
4. `web-build` files are loaded by Next, Vitest, Playwright and ESLint loaders. Their cross-unit imports are not changed
   here (no address for `web-build` yet, and tool loaders are not verified for `@ou/*`).

## Premises used

- P-03 (units are addressed by `@ou/<id>`), P-13 (an address never reaches into another unit).
- Node resolution of `@ou/*`: **not verified** on the Node path; treated as false (3c0ffb84 proves it for the domain
  files). Its blast radius is high if it were true in the other direction: converting node-run files would break
  the operator CLI, the production admin tool. Decision: keep those files relative (reversible; no behaviour change).

## Contract gaps for the target units' U4 (not edited here)

- `engine-architecture-check`: `scripts/check-architecture.mjs` has no address (outside the TypeScript project).
- `web-build`: no address; a tool-loaded config tree.
- Node resolver for `@ou/*` (owner: tooling-lane, a separate PR): needed before the 384 node-run specifiers can move.
