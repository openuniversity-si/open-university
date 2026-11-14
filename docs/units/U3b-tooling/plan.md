# U3b tooling lane: plan

The PR body mirrors this file. Commits in order; each green on its own (change plus its tests).

## Commits

| # | Commit | Owns (files) | Runs in | Tests before push |
|---|---|---|---|---|
| 1 | audit (done) | `docs/units/U3b-tooling/audit.md` | - | none (docs) |
| 2 | this plan | `docs/units/U3b-tooling/plan.md` | - | none (docs) |
| 3 | catalog-cli tests and modules: `@ou/` for cross-unit imports | `apps/web/scripts/lib/catalog-cli/**/*.test.ts`, `.../cli.test-helpers.ts`, `.../ship-reconcile.ts` (not node-run) | after 2 | `unit-battery` for tooling-catalog-cli-core, -content, -media, -ship; `vitest list` census diff |
| 4 | the other tooling units' test and non-Node files | `apps/web/scripts/lib/{batch-from-dir,database-target,factory-bench,font-coverage,intent-tables,intents,media-*,no-video-report,slug-fixtures,static-home}*.ts`, `apps/web/scripts/tower-catalog.test.ts` | after 2, parallel with 3 (disjoint files) | `unit-battery` for each touched unit; `tsc` diff |

Commits 3 and 4 touch disjoint files, so they can run in parallel; the coordinator pushes them in order.

## Rule for every rewrite

- A specifier is rewritten only if: it is relative, `@/` or a `@tower/*` alias; it resolves to a tracked file; that file
  belongs to exactly one unit; that unit is not the importer's unit; the unit has an address; the file lies under the
  unit's home; and the importer is not run by Node directly.
- New specifier: `@ou/<target-unit>/<path under home>`, extension kept, the same specifier text inside `from`,
  `import(`, `require(` or `vi.mock(` only.
- Everything else stays as it is and is listed in the PR body as a gap.
- The generator is a one-off script in the session scratch directory (not committed). Its dry run and its diff of
  each file are the evidence; nothing is hand-edited.

## Gaps (listed, not edited)

1. **Node-run files (384 specifiers, 77 files)**: `tower-catalog.ts`, the `apps/web/scripts/*.ts` entries and the
   web-build config files. Node does not resolve `@ou/*`. Fix is a separate tooling PR: a Node resolver for the `@ou`
   scope (e.g. a module-resolution hook registered by the wrapper), reviewed as an operator-path change. Not done here
   (a new mechanism in the production admin path is not a mechanical change).
2. `scripts/check-architecture.mjs` (`engine-architecture-check`): no address, outside the TypeScript project. U4 of
   that unit.
3. `web-build`: no address (project-root home). U4 of web-build.

## Premises

- P-03: units are imported by `@ou/<id>`. Blast radius high: a wrong address resolves nothing; the tsc and unit-battery
  checks catch it.
- P-13: an address never reaches into another unit. Blast radius high: `scripts/units check` enforces it.
- Node resolves `@ou/*` on its own path: **false**, verified by 3c0ffb84 and by `ERR_MODULE_NOT_FOUND` in the audit's
  premise check. Blast radius if wrong: the production catalog CLI breaks. Handling: keep those files relative (safe).

## Final gate

`scripts/gate-dev --pr <n>` on the exact head, with `OU_CREDENTIALS=network` and the env from `scripts/cloud/env.sh`,
after `git merge origin/mod/roadmap-integration` if the base moved. Known timing-sensitive tests are not changed.
