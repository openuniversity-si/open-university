# U3b playback: audit (lane playback-lane)

Read-only audit before the first code commit (AGENTS.md, D-067, D-069). Evidence is from `origin/mod/roadmap-integration`
at `a2c09043`.

## Scope

- Units: `playback-client` (`apps/web/src/playback/{application,client,ports,server,testing}/**`) and `playback-domain`
  (`apps/web/src/playback/domain/**`), both owned by `playback-lane` (`units/<id>/unit.json`, `scripts/units who`).
- Both homes: `playback-client` is `apps/web/src/playback` (it holds the domain, which is the same cell, so it has an
  address); `playback-domain` is `apps/web/src/playback/domain`. Both addresses exist (`scripts/units addresses`).
- Files in scope: 42 `.ts`/`.tsx` files under `apps/web/src/playback`.

## Evidence

1. **Cross-unit specifiers in the lane's files: 80.** Found by a scan of every `from`, `import()`, `vi.mock` and
   `require` specifier in the 42 files, resolved through the relative path or the `@/` alias to its owning unit
   (`scripts/units owner`). 54 can take an `@ou/` address; 26 cannot (evidence 2 and 3). No `@tower/` alias and no
   `@ou/` specifier exists in these files today.
2. **Node-loaded files keep relative imports (D-069 item 7).** Node 22 loads TypeScript with its native loader, which
   does not read the `tsconfig` `paths`. The base already records this in `3c0ffb84` (domain files, catalog CLI) and
   `2d7d70e2` (`catalog-bake`). The closure of relative imports from the Node entry points (`apps/web/scripts/**`,
   `apps/web/fidelity/**`, the root `apps/web/*.ts|mjs` configs) reaches 13 files of this lane: `application/operations.ts`
   (from `scripts/tower-catalog.ts`), `application/video.ts` (from `catalog/server/deps.ts`), `domain/intents.ts`
   (from `scripts/lib/intents.ts`), `domain/markers.ts` (from `scripts/bundle-check.ts`), `domain/oembed.ts` (from the
   catalog CLI context), `domain/vocabulary.ts`, `domain/source-driver.ts`, `domain/drivers/youtube.ts`,
   `domain/drivers/institutional-url.ts`, `domain/youtube-identity.ts`, `domain/oembed-schedule.ts`,
   `server/source-registry.ts` and `server/oembed-resolver.ts` (the last two from `apps/web/next.config.ts`, a
   conservative entry: Next loads its config outside the TypeScript project). Every specifier of these files stays
   relative; this is a contract gap for the tooling owner (a Node `paths` loader), not an edit of another unit.
3. **Unowned target.** `platform/db/testing/uow-contract.ts` (imported by `testing/transport-contract.ts` and its test)
   belongs to no unit (`scripts/units owner` prints an empty owner). It keeps its relative import; a contract gap for the
   platform owner.
4. **Address map.** `@ou/playback-client/*` → `./src/playback/*`, `@ou/playback-domain/*` → `./src/playback/domain/*`,
   and every other target used here (`kernel-errors`, `kernel-limits`, `kernel-protocol`, `kernel-runtime`, `progress`,
   `site-domain`, `identity`, `platform-runtime`, `catalog-hierarchy`) has an address in `tsconfig.json`. The kernel
   units share the home `apps/web/src/kernel`; their addresses name only files they own (`@ou/kernel-errors/errors.ts`),
   which the U3a check accepts.
5. **Layering already crossed.** Some domain files import client or server files (`domain/engine.test.ts` →
   `testing/fake-engine.ts`, `domain/drivers/source-driver.test.ts` → `server/source-registry.ts`), and the domain's
   `drivers/youtube.test.ts` imports `catalog-hierarchy`. These are rewritten mechanically (no behaviour change) and are
   recorded as existing layering debt, not fixed here.
6. **Baselines recorded before any edit.** `tsc --noEmit` for `apps/web` exits 0 with empty output (24 s).
   `vitest list --project unit src/playback` lists 52 lines and `--project int src/playback` exits 0; saved as
   `census-before` in the PR body. The test census must match after the change.

## Premises

- P-03 (stable addresses `@ou/<id>`): high radius. If the map resolved a file to another unit, a rewrite would import
  the wrong unit. Checked: every rewrite target is re-resolved with `scripts/units owner` before it is written.
- P-13 (two lanes never edit the same file): high radius. The scope is exclusive to `playback-lane`; no file of another
  unit is edited. Checked by `scripts/units owner` on every touched file.
- Not CRITICAL: no production, no secret, no source-of-truth change, no spend.

## Known base defects expected

- `apps/web/next.config.ts` imports playback server code by a relative path (outside this lane, owner: site/web-build).
- The Node loader gap (`paths` not honoured by Node) is owned by the tooling owner; the base already documents it.
