# CAP-001 — Publish any batch of courses from any institution
requested: 2026-10-22T11:00-03:00
requested-by: Daniel (order to solve the 20 root causes of the Brazil batch test structurally)
status: approved 2026-10-22                 # Approved by Daniel 2026-10-22 (D-013)
visual: no

## Concepts
Institution, university row, area, subarea, course, lesson, cover, batch ([CONTRACT.md](../domain/CONTRACT.md)).
Adds `CatalogBatchV2` (§5) and `catalog_media` (§3).

## Contract
Input: one `CatalogBatchV2` (sources, institutions with kind and cover, optional areas/subareas with covers, Home rows
with cover, courses with covers by sha). Output: one release, or a complete failure report. Guarantees G-1 … G-6.
Invariants INV-M1 … M5, INV-R1 … R5, INV-H1 … H4.

## Out of scope
Area order (an admin operation), visual design of covers (Figma first), playback.

## PRs
S03 → S04 → S05a → S05b → S06 → S07 → S08 → S09, then S11 and S15 ([STRUCTURAL-PLAN.md](../process/STRUCTURAL-PLAN.md)).

## Target
marginal: <1h
fixed-cost: ≤60s
A new institution with an existing adapter goes from idea to a passing dry run in < 1 h of work. 1,000 courses apply
in ≤ 60 s (`scripts/factory-bench`, warning above). The Brazil batch (301 courses, 4 institutions, 80 with own covers)
is the first use: one dry run, one write, one release, no manual prerequisite.
