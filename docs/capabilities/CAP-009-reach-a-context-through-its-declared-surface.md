# CAP-009 — Reach any context through its declared surface, and register every intent
requested: 2026-10-25T22:35-03:00
requested-by: A Torre (modularity roadmap step 4, D-054)
status: done 2026-10-26
visual: no

## Concepts
No new visitor concept. Institution, lecturer, area, course, edition, lesson, text, media object, cover, release and
batch stay as in [CONTRACT.md](../domain/CONTRACT.md); each gets one owner context in the generated contexts document (`scripts/generate contexts`)
(PR 4.12). Three structural words, defined in D-060:
- **context map**: `units/cells/<cell>.json`, joined into the context map by `scripts/generate context-map`, the one list of contexts with their half, `dependsOn`, tables and
  size budget.
- **published surface**: a context's `application/` and `domain/` rings (and `client/`, for client files), the only
  part another context may import.
- **intent**: one thing a caller can ask (an admin route, a use case `app/` calls, a script operation), registered in
  its context's `domain/intents.ts` with its business contract and its database contract.

## Contract
Input: a file of one context that needs something from another; an admin route, a use case or a script operation.
Output: the file imports the other context's use case or domain export, along a dependency the map declares; the
entry point has one registered intent naming its meaning, its invariants, guarantees and decisions, the tables it
reads and writes, its transaction, idempotency and audit, and its proof. Responses, rows and rendered pages stay the
same.
Errors: an edge into another context's `ports/`, `server/`, `deps.ts`, `testing/` or root module fails
`L3.context-ports`; an edge along an undeclared dependency, or a cyclic map, fails `L3.context-dag`; a context above
its budget fails `L3.context-size`; an entry point without an intent, a citation that does not exist, a table the
intent's context may not write, a proof that does not exist, or an intent with no entry fails `intents.test.ts`; `INTENTS.md` is generated (`scripts/generate intents`).
Invariants: D-060; D-058; D-059; INV-R4 (publishing goes through the admin API); G-1 to G-6 on the batch intents.

## Out of scope
Visitor-visible behavior and pixels. Database migrations (ownership moves in the map and translator folders only).
Vendors (step 5). Literals (step 6). Structure rules beyond the context map (step 7). Integration and e2e tests.

## PRs
1. Audit, plan, D-060, this design.
2. The context map; `L3.context-ports` and `L3.context-dag` with a shrink-only baseline.
3. The intents registry: media and config routes, one route registry; then the catalog routes; then the use cases.
4. `admin` becomes a context and owns the admin API's HTTP; the catalog's handlers become use cases.
5. Catalog → media and playback through their use cases; the cycles broken; the baseline deleted.
6. The catalog split into `catalog` and `release` (D-061: no `publishing` context); concept ownership; the intents'
   database check; context budgets.
7. Operations scripts through published surfaces; the incident rules the map covers deleted; close.

## Target
idea-to-prod: the step's PRs merged into the integration branch; production waits for the host swap (D-054)
fixed-cost: about 20 PRs (4.1–4.18, 4.8 in three parts)
marginal: a new context dependency is one line in the map; a new admin route or use case is one intent entry, and
the test names what is missing
