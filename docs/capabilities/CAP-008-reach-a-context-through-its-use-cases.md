# CAP-008 — Reach any context through its use cases
requested: 2026-10-25T18:45-03:00
requested-by: A Torre (modularity roadmap step 3, D-054)
status: done 2026-10-25
visual: no

## Concepts
No new visitor concept. Release, course, lesson, session, progress, media and configuration stay as in
[CONTRACT.md](../domain/CONTRACT.md). Two structural words, defined in D-058:
- **application ring**: `<context>/application/`, the only part of a context that `app/` calls.
- **use case**: an exported function in that ring, named for what its caller asks, that takes its ports from the
  context's composition root and opens the transaction when several operations must commit together.

## Contract
Input: a page, layout, route handler or metadata file that needs something from a context; a server function that runs
statements; a domain file that needs a type.
Output: the caller calls a use case; the use case asks ports bound in `server/deps.ts`; a transaction is opened by the
use case through a port's `transaction(work)`; the domain reads only the domain and `kernel/`. Responses, rows and
rendered pages stay the same.
Errors: an `app/` import of a `server/`, `ports/`, `platform/` or `admin/` root module fails `L3.app-application`; a
domain import outside the domain fails `L3.domain-pure`; a use case importing a framework or the database package
fails `L3.application-boundary`; a context file importing its own translator entry fails `L2.db-package`.
Invariants: D-058; D-057 without its own-context allowance; ADR-36 (a context reaches another ring through a port).

## Out of scope
Visitor-visible behavior and pixels. Where `admin` sits among the contexts, services and the intents registry
(step 4). Operations scripts, which stay composition roots until step 4. Vendors (step 5). Literals (step 6).
Integration and e2e tests.

## PRs
1. Audit, plan, D-058, this design.
2. The domain imports only the domain; `L3.domain-pure`; the `application` ring is accepted.
3. Aliases from `tsconfig.json`; `L3.app-application` with a baseline that may only shrink.
4. Site, catalog projections, progress and identity, catalog reads, media, admin API, platform: each `app/` caller
   moves to a use case; the baseline is emptied and deleted.
5. Media, then catalog: server code takes its context's store (D-059), the catalog mutation becomes a use case, and
   `L2.db-package` loses the own-context allowance.
6. Close: decisions proven, metrics.

## Target
idea-to-prod: the step's PRs merged into the integration branch; production waits for the host swap (D-054)
fixed-cost: 18 PRs (#420–#437; the plan said about 17, and 3.11 split in two)
marginal: a new page or route is one use case call, and the check refuses any other import
