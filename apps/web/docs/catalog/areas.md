# Subject areas

Decision (Daniel, 14/10/2026; [ADR-25](../adr/ADR-25-subject-areas.md)): every university page groups its courses by
**one global, ordered list of single-discipline areas**, shared by all universities. Each course has exactly one area. A
university page (`/universities/<slug>`) shows one rail per area it has published courses in, in this order, with at
most 10 cards and a "See all N" link to `/universities/<slug>/<area>`. Areas without published courses are not shown
anywhere; an area with a single course is still shown.

**Areas, their titles and their order are data.** The `subject_areas` table is the only source; it is changed through
the admin catalog API (`scripts/tower-catalog`), never by a code change, a migration or SQL. The live list comes from
`area list`; this page does not copy it. Migration `0012_subject_areas.sql` only seeded the first 30 areas (history).

Big areas can be split into subarea rails on a page with many courses of them: see [subareas](subareas.md)
([ADR-26](../adr/ADR-26-subareas.md)).

## Operations (tower-catalog over the admin API, never SQL)

Each line is one admin API call. `area move` and `area update` change the order or a title in one transaction and
publish one release, like other catalog writes; `area create` adds an area that shows up once a published course has it.

```sh
scripts/tower-catalog area list --target prod                                  # the live list: position, id, title, uses, published
scripts/tower-catalog area create --id design --title Design --target prod     # appended last
scripts/tower-catalog area create --id design --title Design --position 31     # a free position only
scripts/tower-catalog area move design --position 5 --target prod              # to 5 (1..n); the others shift; one release
scripts/tower-catalog area update design --title "Product Design" --target prod  # rename; the id (URL) stays; one release
scripts/tower-catalog course set <course> --area-id economics --target prod    # assign (or --unset area-id)
scripts/tower-catalog release create --note "Areas" --target prod              # publish other changes; rollback: release activate <previous>
```

- `area move <id> --position <n>` (`POST /areas/:id/move`): `n` is 1..number of areas; positions are rewritten 1..n with
  no gaps. The same position is a no-op (no release); an unknown id is 404, a position beyond the count is 422.
- `area update <id> --title <t>` (`PATCH /areas/:id`): titles stay unique (case-insensitive, 409 otherwise).
- Areas are never deleted (courses reference them with `ON DELETE RESTRICT`).
- `doctor` reports `taxonomy.drift` (info) for areas or subareas whose order or title in the database differs from the
  active release, e.g. after `area create` and before the next release.

## Classification rules

1. **One area per course** (`courses.area_id`). A course is never listed under two areas; cross-cutting courses go
   to their primary discipline.
2. **Primary discipline wins:** the area is the discipline the course teaches, not its topic or audience. Marx's
   *Capital* is Economics (not Philosophy or History); *Perception* is Psychology (not Neuroscience); Sandel's *Justice*
   and political philosophy are Philosophy (not Political Science); a history of a science is History.
3. **Computer Science vs Artificial Intelligence:** machine learning, deep learning, LLMs, agents, computer vision, NLP
   and reinforcement learning are Artificial Intelligence; everything else in computing (programming, CS50, databases,
   systems, mobile apps, games programming) is Computer Science. Robotics without learning is Engineering; robot learning
   is Artificial Intelligence. "Economics of AI" is Economics (the discipline taught).
4. **Edge cases decided:** CS50 for Business → Computer Science; 2D game development → Computer Science; nuclear
   engineering courses → Energy; lung cancer patient journey → Medicine; Genesis (Peterson) → Religion; Maps of Meaning
   and Personality → Psychology; Awakening from the Meaning Crisis and After Socrates → Philosophy; STS.081 → History.
   The full mapping of the planned catalog (429 playlists) is `/workspace/torre/catalogo/AREAS-MAPEAMENTO-v2.csv`.
5. **Single-discipline titles only:** no compound areas ("Science & Engineering"); a new area must be one discipline.

## Where it shows

- Only areas with **published** courses appear (per university, from the active release); nothing is hidden because it
  has few courses.
- Release: `areas` (id, title, in order) and `courses[].areaId`; `compileRelease` adds `areas` once any course has one.
  Every published course must have an area (D-017, INV-H1); publication without one is refused.

Related: [tabs](tabs.md), [university covers](university-covers.md), [CLI](cli.md).
