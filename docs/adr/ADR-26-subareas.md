# ADR-26 — Fixed subareas and dynamic subarea rails

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Date: 2026-10-17 · Status: accepted (Daniel, 17/10: "show, manda bala")

## Context
With NPTEL and the full American map, some universities hold dozens of courses in one area (MIT Engineering,
IIT Computer Science). One rail per area (ADR-25) would hide most of them behind "See all"; more areas would break the
"one discipline per area" rule. Daniel rejected manual per-page sections: the split must be automatic, by size.

## Decision
- A global table `subject_subareas` (id, area_id, title, position). A subarea belongs to one area. Subarea ids are
  globally unique and never equal an area id. Migrations 0014 and 0015 seeded the first rows; those files are history.
  The table is the source of truth ([subareas.md](../catalog/subareas.md), D-030). The doc describes the concept and lists no rows.
- `courses.subarea_id` is optional. The composite key `(area_id, subarea_id) → subject_subareas(area_id, id)` plus
  `CHECK (subarea_id IS NULL OR area_id IS NOT NULL)` make a subarea outside its course's area impossible; the API and CLI
  refuse it first with a readable error, and refuse moving a course to another area while it keeps a subarea.
- The release carries `subareas` (only once some published course has one) and `courses[].subareaId` (optional; older
  releases stay valid). `checkRelease` re-checks the invariant.
- **Rail rule, per page, from the courses that page shows** (`universities.ts`, unit-tested constants):
  an area with **≥ `SUBAREA_SPLIT_AT` = 12** courses is shown as one rail per subarea with **≥ `SUBAREA_MIN_RAIL` = 4**
  courses (taxonomy order), then one rail titled with the area for the rest; if that leaves a single rail, the area is
  shown whole. Split rails sit in the area's place. Chips stay one per area (to the area's first rail).
  The two thresholds are the split rule, not the list of subareas.
- The area page (`/universities/<slug>/<area>`) groups by the same rule, one section per rail (the rest is "Other");
  "See all" of a subarea rail links to its section (`#<subarea>`), so the page stays static (no query string).
- A subarea is created by a ship batch `subareas` entry or `tower-catalog subarea create`, and set with
  `tower-catalog course set --subarea-id` or, in bulk and idempotently, `course classify --file`
  (`POST /courses/classify`). Never SQL. Adding one never requires a code change (D-030).
- The doctor reports `courses.subarea_area` (error), `courses.subarea_missing` (info) and `taxonomy.drift` (info: the
  database against the active release, see ADR-25).

## Consequences
Big areas read like shelves without a new navigation level, and small universities look exactly as before. A course
without a subarea is never hidden (it goes to the area's own rail). Adding a subarea is one admin API call or one batch
entry. Renaming or removing one is not supported in v1. Figma: page "Proto — Dynamic", University
frames 622:2488 / 622:2907 (variables `u/split/*`, `u/single/*`, `u/sectionSplit`) and area frames 622:2486 / 622:2905.
