# ADR-25 — One global list of single-discipline subject areas

Date: 2026-10-14 · Status: accepted (Daniel)

## Context
University pages (Figma 556:3) group courses into rails. The catalog had no category field (only level and format), and
per-university "sections" would drift apart (MIT "Computing", Yale "CS & AI", …). The planned catalog (877 playlists in
the source map plus candidates, 429 courses kept) was mapped twice: compound areas first, then single disciplines.

## Decision
- A global table `subject_areas` (id, title, position). `courses.area_id` references it (`ON DELETE RESTRICT`).
  Migration 0012 seeded the first rows; that file is history. The table is the source of truth ([areas.md](../catalog/areas.md), D-030).
- **One area per course**, chosen by its **primary discipline**; the CS vs AI boundary and edge cases are in areas.md.
- The release carries `areas` and `courses[].areaId` (optional, so earlier releases stay valid).
- The site shows only areas with published courses: `/universities` (cover grid, dynamic hero of the selected
  university), `/universities/<slug>` (one rail per area, max 10, "See all N"), `/universities/<slug>/<area>`.
- An area is created by a ship batch `areas` entry or `tower-catalog area create`, reordered with `area move`, renamed
  with `area update`, and assigned with `course set --area-id`. Never SQL. Adding one never requires a code change (D-030).
- `area move` and `area update` rewrite the order or a title in one transaction and publish one release. The doctor's
  `taxonomy.drift` (info) compares the active release with the tables. areas.md describes the concept and lists no rows.

## Consequences
Every university reads the same vocabulary and order; adding a university needs no new taxonomy. A course that spans
disciplines appears once. Adding, moving or renaming an area is one admin API call or one batch entry; removing one is
not supported.
