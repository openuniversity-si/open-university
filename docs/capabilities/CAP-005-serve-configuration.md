# CAP-005 — Serve configuration without a build
requested: 2026-10-23T09:57-03:00          # latest bound: M11 approval on record in 94cccdbb (M10-PLAN.md)
requested-by: Daniel (M11, approved 2026-10-23)
status: approved 2026-10-23
visual: no
condition: before-start open — the absolute no-literal gate is on and the outside count is zero (M11 approval, 94cccdbb); M11 started on 2026-10-25 before it (step 1 audit F2)
condition: before-merge open — Daniel approves the configuration migration before production, and it is not merged without that approval (94cccdbb); 0033_config_documents merged in #355 and reached production through #360's tail without it (host swap queue Q-01)

## Concepts
No new visitor concept. Theme, public copy, limits, and editorial rules stay the keys in D-050.
A configuration document is a revision of those keys. The contract and the domain boundaries stay in code.

## Contract
Input: one of the four documents, or the absence of a stored revision.
Output: the values a reader serves. Revision 0 is the code keys. A stored revision replaces them after validation.
Errors: a document that adds a key, drops a key, exceeds a code ceiling, or renames a persisted editorial word is refused.
Invariants: D-050 (a value lives in a documented key) and D-051 (those four domains are versioned documents).

## Out of scope
Pixels and words on the day the code keys are still the served revision. Pagination and cache durations.
Open University's `content/catalog/*.json` (archived at `567176bb`). A lesson summary. A new `TEXT_FIELDS.lesson` field.
The absolute literal gate. A migration for any table other than the configuration documents.

## PRs
1. The decision and the document contract.
2. The version and history tables.
3. The admin API.
4. The cached read.

## Target
idea-to-prod: 24h
marginal: 1h
The next document uses the same table, the same guard, and the same cache tag.
