# CAP-003 — Serve any public page from a bounded view model
requested: 2026-10-23T03:57-03:00
requested-by: Daniel (production incident, release 133)
status: approved 2026-10-23
visual: no

## Concepts
Release, course, institution ([CONTRACT.md](../domain/CONTRACT.md)). No new concept. The page reads a release
projection and hands the client only the fields that page renders. Rules stay in the domain core.

## Contract
Input: a public route (`/`, `/universities`, `/authors`, `/universities/[slug]`, `/c/[course]`) and the active release.
Output: HTML whose client payload is the view model of that route. A university card is slug, name, fullName, place,
cover, courseCount and hero. Course cards are id, slug, title and poster. A billboard is the fields the billboard renders.
Errors: a projection missing from the release fails the read. A cache entry over 1.5 MB is not stored.
A route outside the SITE-HEALTH ceilings is not a working page (D-038). The ceilings are the only copy.
Invariants: G-6 (a page read does not walk the catalog one course at a time). D-037, D-038.

## Out of scope
Visual changes. Home and course pages keep their signed-in twin, because they render per-viewer progress. Hosting
config, environment variables, and GitHub Actions.

## PRs
One PR. Depends on the projection index already in production (D-033).

## Target
idea-to-prod: 24h
marginal: 1h
On a release the size of release 133 (2,363 courses), `/universities` is under 150 KB of HTML and under 100 KB of RSC.
An uncached read is one batched projection query plus a bounded media read, not one query per course. Every Data Cache
entry stays under 1.5 MB. The next institution's index page reuses the same view model and the same budgets.
Done means the SITE-HEALTH definition passes for every main route and both audiences, on the fixture and on the
rehearsal clone of the batch that is about to reach production.
