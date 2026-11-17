# Subareas

Shared covers (D-031) are versioned per owner in `catalog_media`, independently of courses. A course uses a subarea cover only when it declares `coverFrom: subarea:<id>` for its own subarea. A course with no subarea may declare `coverFrom: area:<id>` for its own area. `own` uses the course's covers. Nothing walks the tree, and a course never uses the institution cover ([cover-hierarchy.md](cover-hierarchy.md)). Use the media API or
`scripts/tower-media` with `--owner subarea:<id>` for upload/list/rollback. Available kinds are
`poster_9x16`, the three hero kinds, `og`, and `lesson_default`. A course bundle sets the declaration with `course.coverFrom`. A lesson's own frame wins; otherwise the fallback is that same declared owner.
The publication check accepts the declared owner's covers without copying them onto the course.
See [media operations](../media/README.md#cover-inheritance-adr-30) for pruning and parity requirements.

Decision (Daniel, 17/10/2026; [ADR-26](../adr/ADR-26-subareas.md); [D-030](../domain/DECISIONS.md)): some [areas](areas.md) have
**subareas**. Each course keeps exactly one area and may have **one subarea of that same area** (`courses.subarea_id`).
Nobody browses by subarea and no page lists them: a university page only **splits a big area into subarea rails**.

**Subareas, their titles and their order are data.** The `subject_subareas` table is the only source. A row is created by a ship batch `subareas` entry (`src/catalog/domain/batch-plan.ts`) or by `scripts/tower-catalog subarea create`. Adding one never requires a code change (D-030). This page does not copy the rows. Migrations `0014_subject_subareas.sql` and `0015_subarea_textile_engineering.sql` only seeded the first rows (history). The live list is `subarea list`. Ids are unique across all areas and never equal an area id.

## Rail rule (per page, automatic)

Computed on every university page from the courses that page shows (`apps/web/src/catalog/domain/universities.ts`):

| Constant | Value | Meaning |
|---|---|---|
| `SUBAREA_SPLIT_AT` | 12 | An area with at least 12 courses on the page is split; below that it is one rail, as before. |
| `SUBAREA_MIN_RAIL` | 4 | Inside a split area, a subarea needs at least 4 courses for a rail of its own. |

These two numbers are the split rule, not the taxonomy. The subareas themselves stay rows.

- Split rails sit together in the area's place, subareas in position order, then **one rail titled with the area**
  holding the rest (no subarea, or a subarea under 4 courses). If only one rail would remain, the area is shown whole.
- Each rail keeps max 10 cards and "See all N". For a subarea rail it opens the area page at that section
  (`/universities/<slug>/<area>#<subarea>`; the rest is `#<area>-other`).
- Chips stay **one per area**, pointing at the area's first rail.
- The area page groups by the same rule: one section (h2) per rail, the rest titled **Other**; an unsplit area is one grid.

A course whose discipline matches none of the area's subareas keeps `subarea_id` null.

## Operations (tower-catalog over the admin API, never SQL)

```sh
scripts/tower-catalog subarea list --target prod                         # the live list, in area order then position
scripts/tower-catalog subarea list --area engineering --covers           # one area; --covers adds active covers
scripts/tower-catalog subarea create --id naval-engineering --area-id engineering --title "Naval Engineering" --target prod
scripts/tower-catalog course set <course> --subarea-id robotics --target prod   # the subarea must be in the course's area
scripts/tower-catalog course set <course> --unset subareaId              # clear it
scripts/tower-catalog course classify --file subareas.csv --release --note "Subareas"   # bulk, idempotent
```

A ship batch carries the same create as `subareas: [{ id, areaId, title }]`. The batch plan
(`src/catalog/domain/batch-plan.ts`) upserts that entry; it does not read a list from code.

The classify file is CSV (`course,area_id,subarea_id`; `course` is an id or slug; an empty cell keeps the value, `null`
clears it) or JSON (`[{"course": "...", "areaId": "...", "subareaId": "..."}]`). It only writes rows that change, so
running it twice is a no-op; every row is checked first and nothing is written if one is wrong. Rollback is
`tower-catalog release activate <previous release>`.

Adding a subarea is `subarea create` or one batch entry on each target. No doc row, no code list, no new migration.
Renaming or removing one is not supported in v1. `doctor` reports `taxonomy.drift` (info) when the database and the
active release disagree.
