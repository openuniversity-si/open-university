# S1: spike, `progress` as a workspace package (P-03, D-067, D-069)

Question (answer input to P-03): does a unit become `package.json per unit`, or do units stay logical (a manifest in
`units/<id>/unit.json`, an `@ou/<id>` address, the checker guarding the boundary)?

**Answer: logical units now. `progress` stays at `apps/web/src/progress`; nothing is lost.** A package works for build,
tests and a package-local type check, but not for `tsc -b`, and it breaks the unit battery and the address check
(below). A unit may become a package only after what it imports has: leaf units first (the order below).

## What was tried (4 vCPU cloud, Next 16.4.2, TypeScript 6.0.3, Vitest 5.0.3, pnpm 10.34.6)

The experiment was run on a scratch tree and reverted; this PR carries no code or lockfile change.

1. `git mv apps/web/src/progress units/progress/src`; manifest `paths` set to `units/progress/**`.
2. `units/progress/package.json` (`@ou/progress`, `exports: {"./*": "./src/*"}`, devDependencies `@types/node`,
   `@types/react`, `typescript`, `vitest`, dependency `server-only`, all at the app's pinned versions).
3. `apps/web/pnpm-workspace.yaml` with `.` and `../../units/progress` (the lockfile stays in `apps/web`; a root
   workspace would have moved it and the gate keys its caches on that path). The app depends on `@ou/progress: workspace:*`.
4. 26 app files rewritten to `@ou/progress/<dir>/<file>.ts` (the `exports` pattern does not add an extension, so
   extensionless imports fail; relative imports into the unit also had to go). The unit's 15 relative imports into
   `kernel`, `platform`, `identity`, `catalog/testing` and `test/fixtures` became the owning units' `@ou/` addresses.
5. `units/progress/tsconfig.json`, `vitest.config.ts` (aliases derived from the app's generated `paths`), and in
   `apps/web/next.config.ts` `transpilePackages: ["@ou/progress"]` plus `turbopack.root` set to the repository root.

## Measurements

| Step | Before (logical) | After (package) | Note |
|---|---|---|---|
| `next build` (`pnpm build`) | 40.6 s | 39.8 s | green; needs `transpilePackages` and `turbopack.root` |
| app `tsc --noEmit` (warm) | 23.7 s (first run, cold) | 20.4 s | green |
| `scripts/unit-battery progress` | 4.96 s, 21 files typed, 6 test files | 2.23 s, **1 file, 1 test file** | false green, see 3 |
| package `tsc -p` (no emit) | n/a | about 3.2 s | green, after adding `server-only` as its dependency |
| package `tsc -b` (composite) | n/a | **fails**, 79 x TS6307 | see 1 |
| package `vitest run` | n/a | 1.4 s wall, 5 files, 27 tests | green, aliases borrowed from the app |

Times are single runs on the shared 4 vCPU box; differences under about 10 percent are noise. The build and the
app type check do not change: the package is compiled from source inside the app.

## What breaks

1. **`tsc -b` cannot work while the unit imports app code.** Composite projects must list every file; `progress`
   imports `kernel`, `platform/db`, `platform/observability`, `identity` and `catalog/testing`, which live inside
   `apps/web` and in turn import more app files (identity config, media types). That is TS6307 for every one of them.
   A project reference needs the target to be a composite project too, so the dependency units must be packages first.
2. **The package needs its own toolchain surface**: `server-only`, `@types/node`, `vitest`, `typescript` as declared
   dependencies (13 new lockfile lines in the app importer plus the package importer), and a second Vitest config
   that re-derives the app's aliases.
3. **The unit battery goes green on nothing.** `battery.unit_steps` include only `apps/web/**`, so a unit outside
   `apps/web` is typed and tested on 1 file. This is the dangerous failure: it reports `ok`. Any package form needs
   steps whose `cwd` and `include` come from the manifest (an `scripts/unit-battery` change, K1/U3a territory).
4. **The address generator drops the unit.** `scripts/generate addresses` only maps homes inside the TypeScript
   project, so `@ou/progress` disappears from `tsconfig.json` `paths` and the checker reports `unit progress has no
   address` 59 times (`structure-check`: 59 errors). A package address would be its package name resolved by pnpm, a
   different mechanism from the generated `paths`; two mechanisms for one fact break D-069 item 1.
5. **Boundary facts the move exposed** (true for the logical form too): `platform/db/uow` is `db-core`, which
   `progress` does not declare in `requires`; `platform/db/testing/*` belongs to no unit and so has no address.
6. **Other tooling keyed to the path** `apps/web/src/progress`: `gate-impact`, `gate-areas`, `architecture-contracts`,
   the literal catalog and absolute-literals baseline, `vitest.config.ts` coverage thresholds, `eslint.config.mjs`,
   CODEOWNERS, e2e and several Python tests.
7. `turbopack.root` moved to the repository root; the existing relative `resolveAlias` entries kept working, but this
   widens the file-watching and tracing root of the only deployable app.

## Decision input for U4

- Keep units logical until the leaves are packages. Order for a future package form: `kernel-*`, `platform-runtime`,
  `db-core` first (no app imports), then units that import only those (`identity`, `progress`), then the rest.
- Preconditions to reopen: (a) battery steps derived from the manifest home, (b) the address generator emitting one
  mechanism for in-app and out-of-app homes, (c) test-only helpers (`platform/db/testing/*`, `test/fixtures`) given
  owners, (d) kernel and platform packaged so `tsc -b` references can resolve.
- Until then U4 moves nothing physically: it migrates literals and imports to `@ou/<id>` addresses (P-05) inside
  `apps/web/src`, which keeps the address the stable seam (D-067 (1)); a later package move changes only the generated map.

D-069 items touched: 1 (one mechanism for addresses), 2 (the answer is recorded in the premise), 12 (pinned versions
reused, lockfile kept in `apps/web`), 14 (battery limit untouched; false-green finding recorded). Premise: P-03.
