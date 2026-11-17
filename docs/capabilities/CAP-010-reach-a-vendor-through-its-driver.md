# CAP-010 — Reach a vendor only through its one driver, and declare every dependency
requested: 2026-10-26T09:00-03:00
requested-by: A Torre (modularity roadmap step 5, D-054)
status: done 2026-10-26
visual: no

## Concepts
No new visitor concept. Media object, cover and lesson video stay as in [CONTRACT.md](../domain/CONTRACT.md). Three
structural words, defined in D-062:
- **vendor map**: `scripts/lib/vendor-map.json`, the one list of the packages Open University depends on, each a `vendor`,
  a `library` or a `tool`, and the retired vendors.
- **driver**: the one module a vendor's package may be imported from (for example `aws4fetch` →
  `src/media/server/r2.ts`).
- **retired vendor**: a package that may not be declared or imported (the old blob client, `@mux/*`, `media-chrome`).

## Contract
Input: a file that needs a hosted service, or a new dependency in Open University's `package.json` (archived at `567176bb`).
Output: the file calls the vendor's driver (or a port the driver implements); the dependency has one map entry. Covers
are stored in and served from R2 at `MEDIA_PUBLIC_HOST`; the fidelity references are stored in R2. Responses, rows and
rendered pages stay the same.
Errors: an import of a vendor package outside its driver fails `L3.vendor-driver`; a dependency missing from the map,
a map entry missing from `package.json`, or a vendor or library nobody imports fails `L3.dependency-declared`; a
retired package declared or imported fails `L3.vendor-retired`; a second accepted production media host fails the
media domain test; a lesson video row with a provider other than `youtube` is refused by the database.
Invariants: D-062; D-029 (no backward compatibility); D-054 (production data rewrites are queued).

## Out of scope
Visitor-visible behavior and pixels. Reading or writing production data (Q-08–Q-11 in the host swap queue). Literals
(step 6). Host portability of the remaining vendors (step 8). The e2e no-video guard, which blocks video hosts in tests
and is not a vendor use.

## PRs
1. Audit, plan, D-062, this design, the queue entries.
2. Mux out of the app and its tests; Mux out of the schema.
3. The media store on R2 only; one accepted media host.
4. The fidelity references on R2 only; the old blob client removed.
5. The vendor map and its three rules with no baseline; the incident rules they replace deleted; close.

## Target
idea-to-prod: the step's PRs merged into the integration branch; production waits for the host swap (D-054)
fixed-cost: about 8 PRs (5.1–5.8)
marginal: a new dependency is one map entry; a new vendor is one entry and one driver module, and the checker names
the file that imports it anywhere else
