# U3b admin: plan

Units `admin-domain`, `admin-server` (lane `admin-lane`). Mechanical PR: no file moves, no renames, no behaviour change.

## Commit graph

Each code commit touches a disjoint set of files, so they are independent and ordered only for a readable history.
No two commits share a file, so nothing runs in parallel that could conflict.

| # | Item (Plan N) | Files owned by the commit | Depends on |
|---|---|---|---|
| 1 | audit (`docs/units/U3b-admin/audit.md`) | that file | none |
| 2 | this plan (`docs/units/U3b-admin/plan.md`) | that file | 1 |
| 3 | application and tests: `catalog-request.ts` (4), `lifecycle.test.ts` (2) | 2 files | 2 |
| 4 | domain tests: `jobs.test.ts` (2), `permissions.test.ts` (4), `route-specs.test.ts` (2) | 3 files | 2 |
| 5 | server source: `config-routes.ts` (9), `deps.ts` (11), `http-dispatcher.ts` (12) | 3 files | 2 |
| 6 | server tests: `auth.test.ts` (1), `catalog-routes.test.ts` (1), `config-routes.test.ts` (3), `http-dispatcher-next.test.ts` (2), `http-dispatcher.test.ts` (2) | 5 files | 2 |
| 7 | testing: `in-memory-jobs.ts` (2), `jobs-contract.ts` (1) | 2 files | 2 |
| 8 | census record (`docs/units/U3b-admin/census.md`): battery and tsc before/after | that file | 3-7 |

Total 15 code files, 58 rewritten specifiers. Each commit is green on its own: a rewrite maps a path to an address that
resolves to the same file (`scripts/units addresses`), so types and tests cannot change. The battery and the gate run
once after commit 7.

## Rule for each rewrite

- Target: a file owned by another unit, under that unit's home (`scripts/units addresses`). Written as
  `@ou/<unit>/<path under home>` (for example `@ou/kernel-errors/errors.ts`).
- Kept relative (not edited): same-unit imports; any file the Node-run closure reaches (audit section 2, 15 files,
  73 specifiers); targets with no address (`app-api`, 2 specifiers).
- Never edited: any file outside the two units. Their importers in other lanes keep their paths until their lanes run.

## Premises and blast radius

| Premise | Status | Radius | If it is wrong |
|---|---|---|---|
| P-03: a unit is imported only through `@ou/<id>`, and the generated map resolves it | validated | high | A rewrite does not resolve: `tsc` and the battery fail. Caught before merge. |
| P-13: one lane owns a unit at a time | inferred | medium | Another lane edits the same files at once: merge conflict, no silent change. The lane owns both units (`scripts/units who`). |

No premise here changes scope, spends money, touches production or the source of truth. Nothing is CRITICAL.

## Tests and gate

- Targeted: `scripts/unit-battery admin-domain` and `scripts/unit-battery admin-server` (tier 1, types plus unit tests),
  before and after the rewrite, with the results in `census.md`.
- Final: `OU_CREDENTIALS=network scripts/gate-dev --pr <N>` on the exact head, timed.
- Known base defect: both batteries report `over_limit` against `battery.unit_time_limit` on this machine before any
  change (audit, section 4). Owner: O1/`battery` (the budget is not loosened here).

## Expected base defects and owners

- Battery time budget on the cloud machine (above): owner O1 (battery budget).
- `app-api` address (GD1): owner of `app-api` (U4).
- Node-run resolver for `@ou/*`: owner of the tooling units (`tooling-catalog-cli-core`, `engine-wrappers`).
