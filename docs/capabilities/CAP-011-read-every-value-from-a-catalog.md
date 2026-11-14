# CAP-011 — Read every value from a documented catalog key
requested: 2026-10-26T12:00-03:00
requested-by: A Torre (modularity roadmap step 6, D-054)
status: requested
visual: no

## Concepts
No new visitor concept. Four structural words, defined in D-063:
- **catalog**: a file listed in `scripts/lib/literal-catalogs/<area>.json` (one manifest per census area, D-064 a) with its domain and description; it holds only
  documented declarations, and it is the one place its values are spelled.
- **offender**: a string, number, boolean or regular expression literal in a production file of Open University outside a
  catalog and outside D-050's structural exceptions.
- **census**: the AST reading that lists every offender with its file, line, kind and role (`pnpm literals:census`).
- **exception list**: `scripts/lib/absolute-literals-baseline/<area>.json`, one file per census area (D-064 a), the offenders still allowed, per file and value; it
  equals the census and, per area and value, only shrinks.

## Contract
Input: a file that needs a value (a word, a bound, a table name, a sheet length, `0`, `true`).
Output: the file reads a catalog key named for what the value controls; a literal type is derived from the catalog.
Rendered pages, responses and rows stay the same.
Errors: a new literal outside a catalog fails the absolute test; a removed literal still on the list fails it until
its entry goes; a value the base's list does not have, or allows fewer times over all files, fails
`structure-check`; a catalog with logic, an undocumented export or key, or a key named after its value fails the
catalog rules.
Invariants: D-063; D-050 and D-052 (the domains and the theme slots); D-051 (documents read the same keys).

## Out of scope
Visitor-visible behavior and pixels. Test files (`*.test.ts`, `*.int.test.ts`, `testing/`, `e2e/`, `test/`). The
Python gate tooling in the repository's `scripts/`: its unregistered literals are D-068's engine census (LT1,
`scripts/lib/literal_census.py`, allowed counts derived from the base census, TX22; the old list under `scripts/lib/absolute-literals-baseline/engine/` is deprecated and goes once TX22 is the base). Host portability (step 8).

## PRs
1. Audit, plan, D-063, this design.
2. The reading on the AST over every production file.
3. The catalog manifest and its rules.
4. The gate on, with the exact and shrink-only exception list.
5. The areas, from protocol and storage to the contexts, sheets, markup and tooling, each to zero.
6. Close: the list is empty.

## Target
idea-to-prod: the step's PRs merged into the integration branch; production waits for the host swap (D-054)
fixed-cost: about 35 PRs (6.1–6.20)
marginal: a new value is one documented key in its catalog; a literal anywhere else fails the absolute test with its
file, line and role
