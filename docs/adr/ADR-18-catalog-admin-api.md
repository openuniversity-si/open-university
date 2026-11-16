# ADR-18 — Protected admin API for the dynamic catalog

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Date: 2026-10-11 · Status: accepted (P4 of the dynamic catalog plan; builds on ADR-17)

## Context
P1–P3 put the catalog in the database and made the site read the active release (ADR-17), but every change still needed
SQL or a migration script. P4 adds the protected API every later tool uses (the `tower-catalog` CLI in P5, the YouTube
import in P6): full CRUD, deletes, reorder, publish, rollback, preview and a consistency report, under the media admin
secret. The reference of each route is [docs/catalog/admin-api.md](../catalog/admin-api.md); the runbook is
docs/operations/catalog.md.

## Decision
- **One guard for media and catalog (E0).** Bearer comparison remains constant-time over SHA-256 digests.
  Only missing/invalid Bearers spend the local IP budget (30 requests / 10 failed auths per fixed minute).
  Valid Bearers bypass that IP bucket and share **600 requests per database minute per secret**, across all instances
  and both APIs. Additive migration `0016_admin_rate_limits` stores one row per SHA-256 secret digest; an atomic UPSERT
  uses the database clock, resets the counter on rollover and reuses the row. Neither IPs nor secrets are persisted.
  429 replies include `Retry-After` (seconds to rollover). A missing secret or unavailable counter returns 503;
  every reply is `no-store`. The catalog and media clients retry 429 up to four times, honouring `Retry-After`
  (seconds or HTTP date) plus exponential backoff with jitter. Authentication denial happens before any mutation,
  so these 429 retries are safe for every method; network/502 replay remains restricted to GET/keyed POST.
- **Layers.** `contracts.ts` (Zod 4, envelope, error codes; the CLI imports it) → `service/*.ts` (pure functions over a
  `Queryable`, no `next/*`, tested on real PG18) → `rules.ts` (the §2.2 preconditions as named rules, shared by status,
  publish, `GET /courses` and the doctor) → `deps.ts` (secret, shared limiter, `appPool`, `invalidateCatalog`, oEmbed, R2,
  clock, uuid, log) → `routes.ts`, one `defineRoute` per route of plan §3.2. Each `app/api/admin/catalog/**/route.ts`
  only exports `catalogHandler("<METHOD> <path>")` with `runtime = "nodejs"` and `dynamic = "force-dynamic"`;
  `routes.test.ts` checks the files and the table match both ways.
- **Contract.** `{ ok: true, data, requestId }` or `{ ok: false, error: { code, message, details? }, requestId }`;
  `requestId` is a safe client `x-request-id` (≤ 64 of `[A-Za-z0-9._-]`) or a new UUID, echoed in the header. Codes:
  400 `invalid` (Zod issues: path, code and message, never values), 401, 404, 409 `revision_conflict` (with
  `currentRevision`) / `state_conflict` / `slug_taken` / `has_dependents`, 412 `preconditions_failed` (the complete
  list), 413 (> 1 MB), 422 `idempotency_mismatch` / `unprocessable`, 429, 502 `upstream_failed` (class and SQLSTATE or
  HTTP status only), 503. Race-time constraint errors map to the same codes (`errors.ts databaseError`).
- **One mutation, one transaction** (`db.ts runMutation`): `BEGIN`, the idempotency key under an advisory lock, the work
  with `SELECT … FOR UPDATE` on the entity (and the course, for lesson changes), its `catalog_audit` rows, the stored
  response, `COMMIT`. A handler that returns success without an audit row throws `AuditMissingError` and rolls back;
  only an explicit `noop` (nothing changed) skips the audit. Network I/O (oEmbed, R2, revalidation) never runs while a
  transaction is open: oEmbed before it, R2 deletes and `revalidateTag` after the commit. Tests record every
  `BEGIN/COMMIT` and network call and prove the order.
- **Revisions.** Every field change bumps the row's `revision`; any lesson change (create, patch, reorder, delete) also
  bumps its course's, so a course's `expectedRevision` covers its lesson order. The Home's revision is a dedicated
  singleton row, `catalog_home.revision` (0007), not `MAX(home_rows.revision)`: `PUT /home` replaces every row, so a MAX
  restarts and could repeat a value a stale client saw.
- **Idempotency.** `Idempotency-Key` (≤ 128 of `[A-Za-z0-9._:-]`) is required on every creating POST, publish,
  unpublish, `POST /releases` (not dry-run), activate, `imports/:id/draft` and `texts/approve|revoke`. The key, route and
  canonical request hash (`canonical.ts`: sorted keys at every level, query + body) are stored with the 2xx response in
  the mutation's transaction; a replay answers the stored status and data with `Idempotent-Replay: true` and audits
  nothing; another body or route with the key is 422; concurrent requests queue on the key's advisory lock and execute
  once. 4xx answers store nothing, so a client fixes the body and retries with the same key. Each idempotent POST prunes
  up to 500 keys older than 30 days after its commit (never failing the request). `PATCH`, `PUT`, `DELETE` and the
  redirect POST are naturally idempotent (same request = `noop`, or 404 after a delete) and take `expectedRevision`.
- **Audit in every mutation.** `actor` is `X-Tower-Actor` (`^[a-z0-9:@._ -]{1,64}$`, default `cli:tower-catalog`; a
  value containing the secret is refused), plus `request_id`, `action`, entity, `before`/`after` limited to changed
  fields (texts: hash, status and source, never the copy) and `release_number`. `GET /audit?entity=kind:id&limit≤200`
  reads it newest first. Each mutation also logs `CATALOG_ADMIN {action, entity, requestId, status, ms}`; an activation
  logs `CATALOG_RELEASE_ACTIVATED {number, sha}`. Bodies are never logged.
- **Releases.** Publishing compiles the tables (`compileRelease`), validates with `releaseSchema`, inserts `MAX+1` under
  `pg_advisory_xact_lock('catalog:release')`, flips `is_active` in the same transaction (the partial unique index keeps
  one active row) and, after the commit, calls `invalidateCatalog()` (`revalidateTag("catalog", { expire: 0 })` and the
  static Home) once. A compile or validation failure is 422 and the active release stays. An unchanged compile is a
  `noop` (no new number). Payloads are immutable twice over: the API never sends an `UPDATE` that touches `payload`
  (tested), and the 0007 trigger `catalog_releases_immutable` refuses any change other than `is_active`/`activated_at`,
  and any `DELETE` (SQLSTATE 55000). `POST /releases/:n/activate` re-validates the stored payload and is the rollback.
  The release diff (`dryRun`, publish, doctor) compares canonical JSON: stored payloads come back from `jsonb` with their
  keys reordered.
- **Edits of published courses wait for their publish.** The next compile of a published course *outside* the publish
  being made keeps the live text of any field whose edit is not approved yet (`compileRelease(…, { previous, fresh })`),
  so editing a course never changes the site and never blocks publishing another course. The course being published
  (`fresh`) must have every required text approved at its current hash (`rules.ts texts.approved`). Hidden lessons leave
  no gap: release order counts visible lessons. A redirect whose target is not live stays in the table and out of the
  release until its target is published again (the doctor lists it as dormant).
- **Publish preflight.** Visible videos last checked more than 7 days ago are re-checked with oEmbed before the
  transaction; a failure is a `videos.fresh` precondition (412), a success refreshes `checked_at`/`checked_by='oembed'`.
  Publishing needs every `published` rule: author, a visible lesson, contiguous positions, YouTube `ok`, required texts
  present, valid (slot length, Inter subset) and approved at their hash, the four required covers, rights fields,
  `rights_status ∈ {cleared, accepted-risk}`, and a visible Home row unless `allowOrphan`.
- **Archive vs purge.** `DELETE /courses/:id` and `DELETE /lessons/:id` are dry-runs unless `confirm=true` (with
  `expectedRevision`); the dry-run returns the exact report (lessons, videos, texts, Home items, asset rows, R2 keys,
  progress rows left behind, redirects, blockers). `archive` = status `archived` (a published course goes through the
  unpublish path: new release, featured replacement required). `purge` only for a course never published or archived,
  in one transaction and FK order (Home items, texts, asset rows, videos, lessons, redirects into it, the course;
  `catalog_imports.course_id` becomes NULL). **`lesson_progress` is never deleted**; the doctor reports orphaned rows.
  Asset rows are read and deleted with the media repository (`ownedMedia`/`deleteOwnedMedia`, sharing
  `deleteMedia`'s "pathname still used by another row" rule), inside the purge transaction; the R2 keys to drop are
  queued in `r2_pending_deletions` (0007) in that same transaction and deleted after the commit. A key that fails stays
  queued with its attempt count; the answer is 502 `upstream_failed` with `details.pendingKeys`, the audit records
  `r2Pending`, the doctor reports it, and re-running the same `DELETE` finishes it. `keepBytes=true` keeps all bytes.
- **Preview.** `POST /preview-token {courseId?, ttlMinutes ≤ 60}` signs `{v, exp, scope, nonce}` with HMAC-SHA256 under a
  key derived from the admin secret (HKDF-SHA256, info `catalog-preview-v1`), never the secret itself. The public
  `GET /api/catalog/preview?token=&to=` verifies in constant time, answers a generic 401 otherwise, refuses any `to`
  that is not `/` or under `/c/` on the same site (400), enables `draftMode()`, stores the token in an httpOnly cookie
  for its remaining lifetime and redirects 307, with `no-store` and `X-Robots-Tag: noindex`. In draft mode with a valid
  cookie, `getCatalogState()` compiles the tables uncached (`compileDraftCatalog`: the token's draft/review courses as
  published, their drafts shown, missing required text as `[field]`, missing rights as placeholders) and the body gets
  `data-preview="true"`. Without the cookie nothing changes: a prerender sees draft mode off and the Home stays static.
- **Doctor.** `GET /doctor` is read-only: orphan texts, orphan asset rows, orphan progress (count and sample), not-ok
  videos of published courses, published courses that would not pass publish now, R2 keys pending, broken and dormant
  redirects, sequences behind `MAX(id)`, a release that no longer compiles, and drift between the active release and the
  current compile (with the diff). `ok` is false when a finding is an error.

## Divergences from the plan and the brief (the repository wins)
1. **`POST /courses/:id/lessons` requires `durationSeconds`.** oEmbed has no duration and `lessons.duration_seconds` is
   `NOT NULL > 0`; the CLI sends what yt-dlp read.
2. **Home revision** lives in `catalog_home` (above), not in `MAX(home_rows.revision)`.
3. **R2 leftovers** are rows of `r2_pending_deletions`, not only a flag in the audit: the doctor and the re-run need the
   exact keys. The audit still records `r2Pending`/`r2Completed`.
4. **Purge reuses the media repository's row logic, not `deleteMedia` itself**: `deleteMedia` opens its own transaction
   per variant, which cannot join the single purge transaction. `ownedMedia`/`deleteOwnedMedia` share its pathname rule.
5. **`catalog_imports.status` gains `received`** (0007): an import is stored by `POST /imports` and becomes `drafted`
   with `POST /imports/:id/draft`; the plan's CHECK knew only `drafted`/`discarded`.
6. **`content_sources` gains `revision`/`updated_at`** (0007) so `PATCH /sources/:id` can take `expectedRevision`.
7. **Unpublish** takes `to: "draft" | "archived"` (default `draft`). The plan's table says published → review; the brief
   says published leaves to draft/archived through unpublish only. `POST /status` never leaves `published`.
8. **A published lesson whose video stops being `ok` blocks every compile** (422, doctor `videos.not_ok` error) until it
   is fixed or hidden with `PATCH /lessons/:id {visible:false}`: the site never publishes a broken embed silently.
9. **Slot budgets** live in `src/catalog/fields.ts` (Figma "Proto — Dynamic" values) until P0 adds
   `design/catalog-slots.json`; course and lesson `about` are optional for publish (omitted unless approved).
10. **Asset foreign keys are `0008_catalog_asset_fks`**, not `0007` (0007 is the admin schema). Their prerequisite, parity
    clean on the three remote targets, was not met at the start: `v1-staging` had only 0001–0003 and no catalog. This PR
    applied 0004–0008 there, imported the v1 catalog (second run `0 changed`) and checked parity: 0 differences on
    v1-preview, v1-staging and prod. `tower-media list --all` showed no asset row without a catalog owner on prod (337
    rows) and v1-preview (330); staging's migration validated the constraint. Both FKs are `ON DELETE RESTRICT`; the
    purge deletes asset rows first. The doctor keeps its orphan-asset check for any database migrated before 0008.
11. **`POST /preview-token` is not audited** (it changes nothing). The `PreviewBadge` visual is P7; P4 adds only
    `data-preview`.
12. The brief's `/c/genesis` is `/c/biblical-series-genesis` in the catalog.

13. **`GET /tables`** (P5) returns the normalized tables and the active release in one REPEATABLE READ snapshot, so
    `courses.legacy` or the Mux columns of `lesson_videos`. It is read-only and not audited.
14. **Static routes failed in production** (P5): Next 16 calls a route handler on a path without dynamic segments with
    `{ params: Promise<undefined> }`, and `next.ts` passed that `undefined` to the params schema. So `GET /doctor`,
    `/courses`, `/releases`, `/home`… answered `400 Invalid path parameter` on preview and prod. `catalogHandler` now
    treats it as `{}`, and `next.test.ts` calls a static route with Next's real context shape.
15. **`sequences.behind` was a false positive** (P5): the doctor read `pg_sequences.last_value`, which is NULL after
    never clean. It now reads each sequence's next value (`last_value`, `is_called`) the way `syncSequences` does.

## CLI
`scripts/tower-catalog` (P5, [docs/catalog/cli.md](../catalog/cli.md)) is the API's only routine client. It is a
consequence of this ADR, not a new decision.
- **Contract.** It imports `contracts.ts` and calls nothing else. Its route table (`scripts/lib/catalog-cli/routes.ts`)
  names the same schema objects. `AdminRoute` now exposes `query`/`body` so `tower-catalog.test.ts` can compare the
  two tables field by field and by schema identity, in both directions. Every route has a command, and every command
  declares the routes it calls.
- **Secret.** The bash wrapper passes it on file descriptor 3, never in argv, the environment or the output. Hosts are
  limited to `openuniversity.si`, `thetower.si` (kept while it redirects) and `*-the-tower-si.vercel.app`.
- **Safety.** y/N or `--yes` on prod, and on every target for publish, unpublish, activate, approve, Home and confirmed
  deletes. The client refuses an unconfirmed change, so a command cannot forget to ask.
- **Idempotency and conflicts.** Keys are deterministic per intent (command, arguments, file hashes, body, the state
  read before an activation, UTC day). Mutations read `expectedRevision` just before they are sent. Only a PATCH whose
  fields nobody else touched is retried after a 409.
- **Exit codes** are fixed per failure class (409 = 3, 412 = 4, 422 = 5, 401/429/503 = 6, network = 7).
- **Tests.** `test/int/tower-catalog.int.test.ts` runs the CLI against the real handlers on PG18, from author and
  import to purge, with replays and a reorder.

## Consequences
- Publishing, unpublishing, Home edits and rollbacks are API calls that change the site on the next request after the
  commit, without a deploy. A content rollback is `POST /releases/:n/activate`; a code rollback is promoting the previous
  Vercel deployment (releases are untouched either way).
- Destructive work is always a dry-run first and leaves an audit trail; bytes are removed only after the rows are gone.
- New migrations: `0007_catalog_admin` (catalog_home, r2_pending_deletions, sources revision, imports `received`,
  `lesson_progress_lesson` index, release immutability trigger) and `0008_catalog_asset_fks`, both additive and applied
  to v1-preview, v1-staging and prod.

## Rule
Guardians: `src/admin/guard.test.ts`, `src/catalog/admin/*.test.ts` (contract, rules and status matrix, canonical hash,
tokens and open redirect, route files), and on PG18 `test/int/catalog-admin-routes.int.test.ts` — a case table keyed by
`ADMIN_CATALOG_ROUTES` that fails when a route lacks its cases: auth/429/503/envelope/no-store for all; audit in the
transaction (an injected audit failure rolls the mutation back), `revision_conflict`, Idempotency-Key required, replay,
mismatch and a concurrent race for the mutations — plus `catalog-admin-{publish,lessons,delete,content,flow}.int.test.ts`.
The media suites run unchanged.

E0 safe purge: course, lesson and edition deletion keep shared R2 bytes by default, including pending retries.
Only `--delete-bytes` checks every candidate on the peer admin API and supplies `deleteBytes=true` plus the exact
`checkedKeys` whitelist. The server never adds keys to that list during deletion or draining, and preserves keys
that gained a local reference. Peer failure or a referenced candidate retains every byte.
