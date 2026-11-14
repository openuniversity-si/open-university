# CAP-002 — Read any admin list without walking the catalog
requested: 2026-10-22T11:00-03:00
requested-by: Daniel (STRUCTURAL-PLAN S10, approved with the structural design, D-013)
status: approved 2026-10-22
visual: no

## Concepts
Course, release, cover, subarea ([CONTRACT.md](../domain/CONTRACT.md)). Uses the stored course projections and the
release redirect projection only as the shape of a read model: admin lists project the columns they show. No new
concept. Rules stay `evaluateRules` in the domain core.

## Contract
Input: `GET /courses` and `GET /redirects` with an optional keyset cursor; `media list --owners type:id,…`;
`subarea list --covers`. Output: one page of courses (counts and the same pending rules as a full read) or redirects
(`live` is still the next release: the target path is publishable and the source is not); one media response with
every named owner; one subarea response whose `covers` array is the active cover state of every subarea.
Errors: invalid cursor or owner token is 400. A named owner with no rows is an empty list, not a missing owner.
Invariants: INV-R2 (pending rules are the core, not a second copy), INV-M3 (cover kinds still come from `resolveCover`).

## Out of scope
Migrations (0025 is S06, 0026 is S08). Hierarchy, batch apply, ship, and the cover resolver (S05b, already in
production). Rebuilding projections on write (S11).

## PRs
S10 only. Depends on S05a, which is merged and in production. S05b is also in production and is not a dependency.

## Target
On a 10,000-course fixture, course list < 1 s and redirect list < 1 s (`read-latency.perf.int.test.ts`). One call returns
every subarea's cover state. The next institution's operator lists courses, redirects and subarea covers without an
N+1 walk (the Brazil run was 18.5 s, 11.7 s and 111 calls).
