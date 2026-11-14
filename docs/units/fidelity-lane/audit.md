# U3b audit: fidelity lane imports to `@ou` addresses

Lane: `fidelity-lane` (owns `fidelity-references`, `fidelity-runner`). Read-only audit; evidence from the
merged base `origin/mod/roadmap-integration` at a2c09043.

## Address map (U3a, generated)

- `scripts/lib/units.py addresses`: `fidelity-references` -> `@ou/fidelity-references` (home
  `apps/web/fidelity/references`), `fidelity-runner` -> `@ou/fidelity-runner` (home `apps/web/fidelity`). Both have an
  address. Neither is addressable yet, because the lane still has importers by path.
- tsconfig `paths` (apps/web/tsconfig.json) carry `@ou/<id>/*` keys only. A bare `@ou/<id>` has no key and
  `unit_addresses.resolve` refuses it until a unit has a contract entry (U4). The import form is therefore
  `@ou/<unit>/<path under the unit's home>`, the form the merged U3b PRs use (for example
  `@ou/catalog-hierarchy/course-status.ts`). The brief's `@ou/<target-unit>` reads as this form.
- Targets needed by the lane, from the map: `@ou/db-operations/*` -> `src/platform/db/*`
  (`tooling/index.ts`, `operations/index.ts`), `@ou/kernel-protocol/*` -> `src/kernel/*` (`node.ts`),
  `@ou/media-application/*` -> `src/media/*` (`application/operations.ts`), `@ou/media-domain/*` -> `src/media/*`
  (`domain/object-store.ts`).

## Cross-unit imports in the lane (scan of `apps/web/fidelity/**`, 26 specifiers)

Scanned with the tsconfig `paths` and the relative resolver; owners from `scripts/lib/units.py unit_of`.

- Runner -> references: `./references/active.ts`, `./references/connect.ts`, `./references/storage.ts`
  (media.ts, media-fetch.ts, references-fetch.ts, resolve.ts, resolve.test.ts, run.ts).
- Runner or references -> kernel-protocol: `../src/kernel/node.ts` (media-fetch, run, summary, references/active,
  figma, storage).
- References -> db-operations: `../../src/platform/db/tooling/index.ts`, `../../src/platform/db/operations/index.ts`.
- References -> media-application / media-domain: `../../src/media/application/operations.ts`,
  `../../src/media/domain/object-store.ts` (storage.ts).

## The Node constraint decides the scope

Every `apps/web/package.json` fidelity script runs a lane file with `node <file>.ts` (`fidelity`,
`fidelity:selftest`, `fidelity:summary`, `fidelity:references`, `fidelity:sync`, `fidelity:migrate-r2`). Node's native
TypeScript loader reads no tsconfig `paths`, and a bare `@ou/...` specifier never resolves under Node
(ERR_MODULE_NOT_FOUND). The same reason kept the U3b config domain files and the baked postinstall relative (commit
3c0ffb84, commit 2d7d70e2).

Closure from the seven Node entry points (`apps/web/fidelity/references-fetch.ts`, `media-fetch.ts`, `run.ts`,
`selftest-run.ts`, `summary.ts`, `apps/web/scripts/fidelity-sync.ts`, `fidelity-migrate-r2.ts`): 19 lane files, all
non-test. Every cross-unit specifier in those 19 files stays relative (22 of 26). They are a contract gap for the
Node path, listed in the PR body, not an edit to another unit.

Off the Node path (only vitest or Playwright load them): `references/references.test.ts`,
`references/references.int.test.ts`, `resolve.test.ts`, and the `*.test.ts` files with no cross-unit import
(`compare.test.ts`, `perceptual.test.ts`). These hold the 4 specifiers in 3 files that this PR rewrites.

vitest derives its aliases from the tsconfig `paths` (apps/web/vitest.config.ts), so the rewritten tests resolve the
same files. Playwright importers (`apps/web/e2e/fidelity.spec.ts`) load lane files from outside the lane; they are
owned by `testing-e2e` and out of scope.

## Known base state

- No lane file has an `@ou/` import today. `scripts/units check` and `unit_addresses.check` are clean on the base.
- Baseline `scripts/unit-battery` for both units is recorded before the first code commit (see the PR body).

## Evidence commands

- `python3 scripts/lib/units.py addresses`
- `python3 scripts/lib/units.py owner apps/web/fidelity/references/active.ts` -> `fidelity-references fidelity-lane`
- Node closure: scratchpad script over `git ls-files` and `apps/web/tsconfig.json` (19 files, listed above).
