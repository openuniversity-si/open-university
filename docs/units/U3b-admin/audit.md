# U3b admin: audit (read-only, before any code change)

Lane `admin-lane`, units `admin-domain` and `admin-server` (D-067, D-069). Base: `mod/roadmap-integration` at `a2c09043`.
Branch: `claude/u3b-admin-addresses-p08vs1` (the designated branch of this session; the brief's `mod/u3b-admin-addresses`
name is not used). Nothing is reused from the closed PR #553.

## Scope evidence

- `scripts/units list`: 104 valid manifests. `admin-domain` owns `apps/web/src/admin/domain/**`; `admin-server` owns
  `apps/web/src/admin/application/**`, `ports/**`, `server/**`, `testing/**`. Together they cover all 32 tracked files
  under `apps/web/src/admin`; `scripts/units check` reports 0 errors.
- Both units have an address (`scripts/units addresses --json`): `@ou/admin-domain` (home `apps/web/src/admin/domain`),
  `@ou/admin-server` (home `apps/web/src/admin`, which also holds the domain files; the file-level check passes because
  each file belongs to one unit).
- Relative specifiers that resolve in owned files before the change: 176. Of these 43 point into the same unit (kept),
  73 are kept for the Node reason below, 58 are rewritten and 2 are contract gaps (the dry run of the mechanical script).
- No `@/` alias and no `@tower/` import appears in the owned files.

## Node-run closure (why 73 specifiers keep their relative paths)

Node 22 runs TypeScript with its native loader, which does not read the tsconfig `paths` that define `@ou/*`. A file
that Node loads at runtime must keep relative specifiers, as the merged U3b precedents did (`3c0ffb84`, `a0cccfff`,
D-069 item 7). The Node-run roots are the non-test files under `apps/web/scripts`. Two chains reach admin code:

- `scripts/tower-catalog.ts` -> `scripts/lib/catalog-cli/{routes,client,commands/ship,commands/ship-apply}.ts` and
  `scripts/lib/intents.ts` -> `src/admin/domain/{route-specs,jobs,intents,job-body,lifecycle-body,permissions}.ts`,
  `src/admin/ports/jobs.ts`, `src/admin/application/{jobs,lifecycle}.ts`.
- `scripts/lib/factory-bench.ts` -> `test/fixtures/admin-catalog.ts` -> `src/admin/server/{catalog-http,catalog-routes,
  auth,job-handlers,lifecycle-handlers,media-gateway}.ts`. This chain is why the server files are in the closure too.

The 15 closure files keep their 73 cross-unit relative specifiers. They are listed in the PR body as a contract gap for
the tooling owner: a tsconfig-paths resolver on the Node path would let them move to `@ou/*` (no change here).

The closure is computed from the import graph by `scratchpad rewrite_admin.py` (not committed): a file in the closure
is never rewritten; a file outside it has every cross-unit specifier rewritten to `@ou/<unit>/<path under home>`.

## Rewrites (58 specifiers, 15 files)

Per file, the rewritten targets are the kernel units (`kernel-errors`, `kernel-protocol`, `kernel-limits`), the
catalog units (`catalog-schema`, `catalog-application`), the config units (`config-documents`), the media units
(`media-domain`, `media-application`), the platform units (`platform-runtime`, `db-contexts`, `db-catalog-store`),
the admin units themselves (`admin-domain` from server and tests, `admin-server` from domain tests) and
`tooling-catalog-cli-core` (`@ou/tooling-catalog-cli-core/routes.ts`, used only by a vitest test). Every target file
sits under its unit's home; the script refuses any target outside its home or of a unit without an address.

## Contract gaps (not edited, listed in the PR body)

1. `app-api` has no address (its `proxy.ts` is at the `src` root, GD1). Two `http-dispatcher-next.test.ts` imports of
   `app/api/admin/{catalog,media}/[...route]/route.ts` keep their relative path. For `app-api`'s U4.
2. Node-run closure (15 files, 73 specifiers) as above. For the tooling owner.
3. The admin-domain tests import admin-server files (`jobs.test.ts`, `permissions.test.ts`, `route-specs.test.ts`).
   The rewrite turns those into `@ou/admin-server/...`; `admin-domain` does not list `admin-server` in its `requires`.
   Not edited here (the manifest is U0's); `scripts/units check` still passes.

## Baseline (before any change, 4 vCPU cloud, same commit)

`scripts/unit-battery <id> --json` with `OU_CREDENTIALS` unset, env from `scripts/cloud/env.sh`:

| unit | types (tsc per unit) | unit-tests | files | battery result |
|---|---|---|---|---|
| admin-domain | ok, 17.8 s, empty output | ok, 9.7 s, 3 files | 9 | `fail` only because `over_limit`: 17.8+9.7 s against `battery.unit_time_limit` (10 s) |
| admin-server | ok, 18.3 s, empty output | ok, 11.5 s, 6 files | 23 | same: `over_limit` only |

The time limit is a registered budget; it is not loosened here. The over-limit is a pre-existing condition of the
battery on this machine (cold `next typegen` plus tsc). It is reported in the PR, not hidden.

Static test census of the admin unit tests (9 files, `^\s*(it|test)\(` call sites): 44. Recorded before and after.
