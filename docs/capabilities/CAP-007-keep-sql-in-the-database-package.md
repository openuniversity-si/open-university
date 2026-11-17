# CAP-007 — Keep every SQL statement in the database package
requested: 2026-10-25T15:30-03:00
requested-by: A Torre (modularity roadmap step 2, D-054)
status: approved 2026-10-25
visual: no
condition: before-production open — the release host reaches PostgreSQL over TCP, since the serverless WebSocket transport is removed (D-056; queued by PR 2.3 in docs/process/host-swap-queue.md)

## Concepts
No new visitor concept. Release, course, lesson, session, media and configuration stay as in
[CONTRACT.md](../domain/CONTRACT.md). Two structural words, defined in D-056:
- **database package**: Open University's `src/platform/db/` (archived at `567176bb`), the only place a SQL statement is written.
- **translator**: a module in `platform/db/<context>/` that implements a port of that context by turning each
  operation into SQL and each row back into the context's types.

## Contract
Input: one SQL statement, connection or driver import outside the database package.
Output: the statement lives in the translator of the context that owns its tables, behind an operation of that
context's port. The caller asks for the operation. The rows stored, the release served and the pages rendered stay
the same.
Errors: a SQL literal, a `pg`/`drizzle-orm` import or an import of a package internal outside the package, or a
translator naming another context's table, fails the `L2.db-package` rule of the architecture check.
Invariants: D-056; ADR-36 (a context reaches another ring through a port); table ownership per translator folder, checked by the same rule.

## Out of scope
Visitor-visible behavior and pixels. Integration and e2e tests, which may seed and assert with SQL against the local
test database. Use cases and transaction boundaries above the port (step 3). Contexts and the intents registry
(step 4). Vendors other than the database (step 5). Production migrations, which wait in the host swap queue.

## PRs
1. Audit, plan, D-056, this design.
2. `L2.db-package` with a baseline that may only shrink.
3. One driver: `pg` everywhere; the serverless transport and its preload are removed.
4. Config, then progress, rate limit and identity, then admin jobs, media, catalog: each context's SQL moves into its
   translator behind its port.
5. Operations scripts and the tooling database go through translators.
6. D-036: an edition's language is required (local migration, queued).
7. The baseline is empty and deleted; the rule stands alone.

## Target
idea-to-prod: the step's PRs merged into the integration branch; production waits for the host swap (D-054)
marginal: a new query is one operation on a port and one function in its translator, and the check refuses any other place
