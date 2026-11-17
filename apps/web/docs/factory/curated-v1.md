# curated/v1

<!-- Generated from apps/web/src/factory/domain/curated.ts. Do not edit; the unit test fails when it is stale. -->

One JSON file per institution run. It is the only input of `curatedToBatch`. Limits are the catalog schema
(INV-R1): an id is at most 64 characters, a course title at most 200,
a lesson title at most 1000.

Rules checked by the schema:

- `provenance.titles` of `translated` is a schema error. `originalTitle` stays in the source language.
- `durationSeconds` is an integer greater than 0. A scheduled video is not a lesson.
- An over-long field fails by its path (`courses.0.id`, `courses.0.title`).
- `decision: hold` keeps the course in the file and out of the batch, and names `holdReason`.
- `decision: include` may omit a field. The converter holds that course. A missing year, coverFrom or required cover is a hold, never a guessed value.
- The institution is kind `institution`. Its cover names alt, credit, sourceUrl and license for the University row.
- Home-row placement is `after` (the previous row) or omitted. The batch has no position field.
- `positions`, when present, is an inclusive playlist range `{ from, to }` of positive integers with `from` <= `to`. Absent means the whole playlist.

### `run`

| Field | Type | Required |
|---|---|---|
| `id` | string | yes |
| `createdAt` | string | yes |
| `adapter` | string | yes |

### `institution`

| Field | Type | Required |
|---|---|---|
| `id` | string | yes |
| `slug` | string | yes |
| `name` | string | yes |
| `fullName` | string | yes |
| `place` | string | yes |
| `kind` | `"institution"` | yes |
| `monogram` | string | yes |
| `cover` | object | yes |
| `homeRow` | object | yes |

### `sources[]`

| Field | Type | Required |
|---|---|---|
| `id` | string | yes |
| `kind` | `"youtube-channel"` · `"youtube-playlist"` · `"portal"` | yes |
| `title` | string | yes |
| `url` | string | yes |
| `youtubeChannelId` | string | no |

### `licenses[]`

| Field | Type | Required |
|---|---|---|
| `code` | string | yes |
| `name` | string | yes |
| `url` | string | no |
| `requiresAttribution` | boolean | yes |
| `nonCommercial` | boolean | no |
| `shareAlike` | boolean | no |
| `embedOnly` | boolean | no |
| `attributionTemplate` | string | no |

### `areas[]`

| Field | Type | Required |
|---|---|---|
| `id` | string | yes |
| `title` | string | yes |
| `cover` | object | no |

### `subareas[]`

| Field | Type | Required |
|---|---|---|
| `id` | string | yes |
| `areaId` | string | yes |
| `title` | string | yes |
| `cover` | object | no |

### `courses[]`

| Field | Type | Required |
|---|---|---|
| `sourcePlaylistId` | string | yes |
| `decision` | `"include"` · `"hold"` · `"exclude"` | yes |
| `holdReason` | string | no |
| `lecturer` | object | no |
| `id` | string | no |
| `slug` | string | no |
| `title` | string | no |
| `originalTitle` | string | no |
| `language` | string | no |
| `areaId` | string | no |
| `subareaId` | string | no |
| `license` | string | no |
| `rights` | `"unverified"` · `"cleared"` · `"permission-requested"` · `"accepted-risk"` · `"restricted"` | no |
| `canonicalUrl` | string | no |
| `year` | integer | no |
| `coverFrom` | string | no |
| `sharedWith` | list | no |
| `cover` | object | no |
| `variantOf` | string | no |
| `sourceId` | string | no |
| `positions` | object | no |
| `lessons` | list | no |

### `provenance`

| Field | Type | Required |
|---|---|---|
| `titles` | `"original"` · `"translated"` | yes |
| `fetchedAt` | string | yes |
| `counts` | object | yes |
