# CONTROL-STORE plan

## Plan
- [x] 1. audit.md skeleton
- [ ] 2. audit.md findings + plan.md
- [ ] 3. Store fixes in core.js: retention (no history over budget), supersession (`jobs_superseded_total`), TTL (`jobs_expired_total`, `JOB_TTL_S=3600` in wrangler.toml) + their tests
- [ ] 4. retro.md

Critical path: 2 -> 3 -> 4 (all in one file `core.js` + its test file: a file collision, so no parallel commits; ~25 min).

## Alternativas
### R1
- A1 remendo: `room > 0 ? slice(-room) : []`. 
- A2 corrige a classe: same plus a test of both branches.
### R2
- A1 remendo: only supersession.
- A2 corrige a classe: supersession (redundant) + TTL (old), both counted. 
- A3 redesenho: per-PR single-slot queue; larger, belongs with CONTROL-ROUTE.

## Escolha
- R1 → A2: the over-budget case is the one that failed unnoticed.
- R2 → A2: bounds the queue by relevance and age; A3 deferred, Follow-up: CONTROL-ROUTE.

Supersession drops only `queued` jobs (same kind, same PR, different sha); leased/cancelling/done are untouched. TTL drops only `queued` jobs, runs in `claim` and `tick` (before lease requeue). `JOB_TTL_S<=0` disables it.

Premises: none
Decision: D-054
Fit-Review: not reviewed (Daniel 2026-10-25: no review step)
