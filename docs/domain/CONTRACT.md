# Open University domain contract (chapter 1 of the constitution)

Status: **Archived record** (OU-DECOUPLE F5, D-113). Open University left this repository (D-105, D-111) and its code
is archived at `567176bb` (D-110), so nothing here binds the engine: the engine's rules are its decisions
([DECISIONS.md](DECISIONS.md)) and its contracts (`contracts/`). The text below is kept as it was approved, because the
Open University capabilities and decisions cite its ids; the code and paths it names are in the archive.

Approved by Daniel 2026-10-22 (D-013). Owner: A Torre (structure owner, [STRUCTURE.md](../process/STRUCTURE.md#b5-structure-owner-and-fit-review)).

This file is the single written definition of what the catalog *is*. Code, migrations, the admin API, the CLI, the
factory, Figma and every agent prompt derive from it. When code and this contract disagree, the code is the bug, or
the contract changes first through the decision rite ([STRUCTURE.md](../process/STRUCTURE.md#c5-decision-to-code)).
Each invariant has an id (`INV-…`) and each batch guarantee an id (`G-…`). Tests name the id they prove, and
[DECISIONS.md](DECISIONS.md) links each of Daniel's decisions to them.

Present tense describes the target. A line marked **(today)** states the current behaviour that a planned PR
([STRUCTURAL-PLAN.md](../process/STRUCTURAL-PLAN.md)) replaces.

## 1. Concepts

| Concept | Definition | Identity | Stored in (target) |
|---|---|---|---|
| **Institution** | Who offers a course: a university, institute or channel. Shown on the Universities tab as one row. `kind` is `institution`, `person` or `channel`, always declared (no DB default). A University row and a course's `institution_id` point only at `kind = institution` (D-024). | `entityId` (≤ 64, kebab) + unique slug | `authors` (`kind` required) |
| **Lecturer** | Who teaches a course: a person (or channel). Shown on the Authors tab. A lecturer may teach at several institutions (D-024). | `entityId` + unique slug | `authors`, referenced by `courses.author_id` |
| **University row** | The Home/Universities presentation of an institution: title, full name, place, position, visibility, cover, OG. | row id = institution slug | `home_rows` (`kind = curated`) linked 1:1 to its institution (D-016) |
| **Area** | One global single-discipline subject (ADR-25). Ordered list. Data, not code. | `entityId` | `subject_areas` |
| **Subarea** | An optional split of one area (ADR-26). Belongs to exactly one area. | `entityId`, unique within area | `subject_subareas` |
| **Course** | One teachable unit from one institution, in one area and at most one subarea, with one or more editions. | `entityId` (≤ 64) + slug (≤ 120) | `courses` |
| **Edition** | A dated offering of a course (ADR-21, D-034). `year` is known or explicitly `null`; never invented. An optional `variant` (`kind` `language`, `term` or `group`, plus a short `label`) distinguishes two offerings of the same year. The offering is `(courseId, year, variant)`. | `entityId` | `course_editions` |
| **Lesson** | One video in one edition of one course. A YouTube video is one lesson of that course. Another course uses the same video only when both declare the share (D-032). | `entityId` + slug within course | `lessons`, `lesson_videos` |
| **Text** | Editorial text of a course or lesson, approved by a separate automatic reviewer, never by its generator (D-019). | (entity, field) | `catalog_texts` |
| **Media object** | Immutable bytes addressed by sha256 (ADR-35). | sha256 | `media_objects`, R2 `m/<sha>.<ext>` |
| **Cover** | A media object attached to one hierarchy node with a kind (`poster_9x16`, `hero_*`, `og`, `still_16x9`, `lesson_default`, `cover_16x9`) and variant. | (node, kind, variant, version) | `catalog_media` (one table, every node kind) |
| **Release** | An immutable compiled snapshot that the site reads (ADR-37). | number + sha | `catalog_releases`, projections |
| **Batch** | The unit of publication: the complete desired state of a set of courses and everything they reference. | content hash | `catalog_ship_batches` |
| **Factory** | Everything that turns a source (a YouTube channel, a university portal) into a batch: ingest, curation, texts, publish. See FACTORY.md (archived with Open University at `567176bb`, D-110). | — | repo package, no data in git |

## 2. The hierarchy

The catalog has two axes. Both are trees, both are stored, and both are walked only through one domain module
(`src/catalog/domain/hierarchy.ts`, planned PR S06).

```
taxonomy axis (a course declares one cover owner on it)     provenance axis (no inheritance)
area ─┬─ subarea ─┬─ course ── edition ── lesson             institution ── course
      │           └─ course …                                 └─ university row (presentation)
      └─ course (no subarea) ── edition ── lesson
```

- **INV-H1** Every course has at most one institution (`courses.institution_id`) and every course on a University row has
  exactly that row's institution (D-024); **(today)** courses placed on no University row may have none. Every **published** course has exactly one area (D-017); a
  draft may have none. There is no unclassified trailing rail.
- **INV-H2** A subarea belongs to one area; a course's subarea is inside the course's own area (composite FK, today).
- **INV-H3** The parent of a course on the taxonomy axis is its subarea, else its area. The parent of a lesson is its
  course. An area and an institution have no parent.
- **INV-H4** The hierarchy is not duplicated in code. Areas, subareas, their titles and their order are rows changed
  only through the admin API (`area create`, `area move`, `area update`, `subarea create`) or a ship batch `areas` or
  `subareas` entry. Adding one never requires a code change (D-030). No list of areas or subareas exists in source, docs
  or tests (enforced by `areas.test.ts`).
- **INV-H5** A university row belongs to exactly one institution and an institution has at most one row
  (`home_rows.institution_id` required and unique for curated rows). A row never groups institutions (D-016).

## 3. Media and cover inheritance

- **INV-M1** Any hierarchy node can own media: institution, area, subarea, course, lesson. One table
  (`catalog_media`) with `owner_kind IN ('institution','area','subarea','course','lesson')` holds every attachment.
  The legacy asset tables and the cover columns `authors.media_sha256`, `home_rows.media_sha256` and
  `home_rows.og_media_sha256` are gone (D-029). There is no second model to read.
- **INV-M2 (declared owner only)** A course stores `coverFrom`: `own`, `subarea:<id>` or `area:<id>`. Its cover of
  kind *k* is the active *k* of that owner, or none. `subarea:<id>` is legal only for the course's own subarea.
  `area:<id>` is legal only when the course has no subarea, and only for its own area. Nothing walks from that owner
  to another, and nothing resolves from a descendant (no "first course poster"). The provenance axis carries no
  inheritance: a course never resolves its institution's cover (D-014, D-031).
- **INV-M3 (one resolver)** `resolveCover(node, kind)` in `src/catalog/domain/cover-resolve.ts` is the only function
  that decides which image a node shows. Compile, projections, pages, OG and the doctor call it. An architecture rule
  rejects any other reader of media rows outside the media adapter.
- **INV-M4 (institution cover mandatory)** An institution that is visible and publishes a course has its own cover
  (and the university row its own cover; OG falls back to that cover, then the brand card). Institutions never inherit.
  The API rejects creating or showing such an institution without one; the database enforces it with a deferred
  constraint trigger at commit. Decision D-002.
- **INV-M5 (no silent cover)** Every course carries `coverFrom`. A ship rejects a course whose declaration is not its
  own subarea (or its area when it has none), or whose declared owner lacks any required cover kind. A missing cover,
  year or other required field rejects the course (it is held); nothing is filled in by fallback. A lesson uses its
  own `cover_16x9` when it has one; otherwise its fallback is that same declared owner and no further ancestor
  (D-031). `cover_provisional` is gone.

## 4. Catalog rules

- **INV-R1 (one schema)** Every field limit, pattern and default lives once in `src/catalog/domain/schema/`
  (zod). The bundle/batch validator, the admin route contracts, the TypeScript types and
  `docs/catalog/schema.md` (archived with Open University at `567176bb`, D-110) (generated, `pnpm schema:check` in the gate) derive from it. Examples:
  `entityId` ≤ 64 everywhere, slug ≤ 120, `edition.year` integer or `null` (unknown, never invented; the store keeps a
  year on every edition, so writing a `null` year is refused until it is named). `edition.variant`, when present, is
  `{ kind, label }` from that same schema (D-034). `edition.language` is that schema's language label (D-035): the
  course language is its default edition's language, and a variant of kind `language` uses that same string as its label.
- **INV-R2 (one rule set)** Every rule that needs stored state (references exist, slugs free, cover present, video once
  per course, Home row valid) is a pure function in `src/catalog/domain/rules/` over a snapshot slice that a port loads.
  Routes, the batch applier and the CLI preview call the same function. Each rule has a stable id
  (`ref.source.unknown`, `cover.institution.missing`, …) declared once in a registry; an architecture rule rejects a
  second declaration or a rule message built in `server/`.
- **INV-R3** A YouTube video appears at most once per course. It may appear in another course only when both courses
  declare that share. Watch progress belongs to the lesson, so it is separate per course (D-003, D-032).
- **INV-R4** Publishing data happens only through the admin API (`tower-catalog`, `tower-media`); never SQL or direct
  R2 (D-005).
- **INV-R5** A published course has a license, source, canonical URL and cleared or accepted rights (DB check today).

## 5. The batch (unit of publication)

A batch is a **declarative document of desired state**, `CatalogBatchV2` (`src/catalog/domain/schema/batch-v2.ts`, S07). It contains everything
needed for its courses to be live, and nothing is created outside it:

```
CatalogBatchV2 {
  version: 2, updateRefs?: false
  sources:      [{ id, kind: youtube-channel|youtube-playlist|institution-site, title, url, youtubeChannelId? }]
  institutions: [{ id, slug, name, monogram, kind: institution, cover: {poster: sha, og?: sha} }]
  lecturers:    [{ id, slug, name, monogram, kind: person|channel }]            # D-024: who teaches
  licenses?:    [{ code, name, url?, requiresAttribution, … }]            # e.g. cc-by, created in this pass
  areas?:       [{ id, title, cover?: {poster, heroDesktop, heroPresent, heroMobile, og?, still?, lessonDefault?} }]
  subareas?:    [{ id, areaId, title, cover?: {poster, heroDesktop, heroPresent, heroMobile, og?, lessonDefault?} }]
  homeRows?:    [{ id, institutionId, title, fullName, place, after, visible,
                   cover: {sha, alt, credit, sourceUrl, license, note?}, og?: sha }]
  courses:      [{ institutionId, homeRowId?, course (authorId = lecturer, coverFrom: own|subarea:<id>|area:<id>),
                   editions, lessons, texts, covers: [{kind, sha}] }]     # bytes uploaded before, by content address
}
```

The cover kinds each owner accepts are one list (`src/kernel/cover-kinds.ts`, D-035). The batch schema, the plan, `mediaKey` and the `catalog_media` check read that list. A kind the owner does not accept fails the plan with 412 before any write. An area accepts `still_16x9`. A subarea does not.

Semantics are **additive upsert by id**: a reference that exists with the same content is a no-op, with different
content is a conflict unless `--update-refs` is set, and absent is created. Nothing is deleted by omission.

Guarantees (each has a test named after its id, planned PR S08):

| Id | Guarantee | Proof |
|---|---|---|
| **G-1 All or nothing** | The batch commits every row, every attachment and one release, or nothing. A failing course fails the batch before any write is visible. | `batch-apply.int.test.ts › G-1` (fault injected after the last write) |
| **G-2 Idempotent** | Applying the same content hash twice returns the first result and writes nothing. | `› G-2` |
| **G-3 Dry run is the write** | `dryRun: true` runs the *same* transaction (validate, references, writes, rules, release compile) and rolls back. Its report equals the committed report except ids/numbers. | `› G-3` (property: report(dry) ≡ report(write)) |
| **G-4 Order-free** | The server resolves the order (refs → nodes → media → courses → rules → release). The client sends one request per chunk; no step happens before or after the commit. | `› G-4` (new course with own covers, new institution, new row in one batch) |
| **G-5 Complete failure report** | A rejected batch lists every failing rule by id and entity, not the first. | `› G-5` |
| **G-6 Bounded cost** | 1,000 courses apply in ≤ 60 s on the reference database; release cost grows with changed courses, not catalog size. A cut reuses a stored projection when the course is outside the fresh set, its revision matches, and its author, license, source and rows are unchanged (D-033). | `scripts/factory-bench` (gate-noite stage); `incremental-compile.perf.test.ts` › D-033 |

Chunking (≤ 1 MiB, ≤ 100 chunks) is transport only; a batch is open until all chunks arrive (0022). `POST /batches/apply`
stages CatalogBatchV2 parts with `format = catalog-v2` (0026); the references travel in the first part. The chunked
keys and the content hash are every array key of the batch schema, including `licenses` (D-035). `PUT /home`
accepts the same `dryRun`: it replaces the rows, runs the deferred cover constraint and compiles the release, then
rolls that work back. The report is the write's report plus `dryRun: true`. `tower-catalog ship <dir|batch>`
uploads missing cover bytes and sends only `POST /batches/apply` (S09). `--dry-run` posts `dryRun: true` and prints that report.

## 6. What is outside this chapter

Playback, identity and the site's visual design (Figma is the source, D-006) are governed by their ADRs. Later chapters
of the constitution cover them when their own structural questions come up.
