# U3b identity: plan

Mirrors the PR body. Source: [audit.md](audit.md).

## Commits (dependency graph)

Each commit is one small, green step: the change and the tests it touches pass alone. Commits run in order, one
after the other; they share files (`server/config.ts`, `server/handler.ts`, `server/session.ts`, `client/AuthProvider.tsx`,
the tests), so none runs in parallel with another.

1. **audit** (`docs/units/U3b/audit.md`). Done.
2. **plan** (this file). Done with commit 2.
3. **kernel imports** → `@ou/kernel-errors/`, `@ou/kernel-protocol/`, `@ou/kernel-runtime/`, `@ou/kernel-tables/`,
   including the `@/kernel/cache.ts` alias in `client/AuthProvider.tsx`. 19 sites, source and tests. Excludes
   `domain/intents.ts` (Node-run exception). Owns: the identity files that import `kernel/`.
4. **platform, db and site imports** → `@ou/platform-runtime/`, `@ou/db-contexts/`, `@ou/db-core/`, `@ou/site-domain/`.
   12 sites. Owns: the identity files that import `platform/` or `site/`.
5. **retro** (`docs/units/U3b/retro.md`), committed and posted before merge.

Files of commits 3 and 4 do not overlap by design of the step, but they touch the same files in sequence, which is
fine because they are not parallel.

## Premises and blast radius

- **P-03** (stable addresses, `@ou/<id>`). Radius high: a wrong address breaks every importer of that unit. Checked by
  the type-check and the unit tests after each commit; a mis-mapped file fails them.
- **P-13** (exclusive unit ownership). Radius high: a file owned by two units would make the rewrite a cross-lane
  edit. Checked: every imported file has one owner, the one the import names (audit, no contract gap).
- No CRITICAL premise: no spend, no production, no source-of-truth change, no secret.

## Tests per commit

- After each commit: `scripts/unit-battery identity` (tier 1: types, unit and script tests), and the identity vitest
  census compared with the baseline (7 files, 75 tests, all pass).
- Sanity grep after commit 4: no `../../kernel`, `../../platform`, `../../site` or `@/kernel|platform|site` specifier left
  in `apps/web/src/identity`, except `domain/intents.ts`.

## Final gate

- `gate-dev --pr 583` on the exact head, after `git merge origin/mod/roadmap-integration` if the base moved.
- No gate-db (the diff does not touch the database).

## Known base defects expected

- The timing-sensitive tests named in the brief (tower-catalog cover concurrency, read latency). Not identity's. If only
  they fail, merge the base and re-gate; never change them.
- The architecture check's `L7.identity-domain` reads through `@ou` now; if it resolves differently from the relative
  path, that is a finding to report, not a rule to relax.
