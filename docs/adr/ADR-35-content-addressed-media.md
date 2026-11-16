# ADR-35 — Content-addressed media

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Status: proposed (E2; additive database expansion before merge).

The stage text names ADR-29, already allocated to disposable PR databases; ADR-34 went to the DB gate. This decision uses the next free number, 35.

One content identity, SHA-256, determines the immutable global R2 key `m/<sha256>.<ext>`.
Keys contain neither an owner nor an environment. `media_objects` records the format, content type,
byte count and dimensions in each database. URLs are derived from that identity and the configured public media host.
R2 PUT uses `If-None-Match: *` and `public, max-age=31536000, immutable`.
R2 server-side copy uses its atomic `cf-copy-destination-if-none-match: *` extension and replaces cache metadata.
An existing object's checksum is verified before registering it in another database; ETags are not SHA-256 checksums.

`course_assets`, `lesson_assets` and `subarea_assets` gain nullable foreign keys to the registry.
Authors and Home rows gain cover foreign keys (including university OG images), preserving their release semantics.
The media API is the only routine upload path, including author/university/OG covers; those CLIs no longer use R2 credentials.
`POST /api/admin/media/check` preflights at most 100 hashes and registers verified content already in R2.
`POST /api/admin/media/objects` accepts a prepared image and its expected SHA-256.
`POST /api/admin/media/attach` links registered content to an asset owner using the database alone.
The legacy multipart owner endpoint remains an API entry point into the same registry.
CLIs strip metadata and hash the prepared bytes before preflight; repeated content sends zero image bytes.

All media transactions use a single checked-out pool client, including BEGIN, advisory locks, writes and COMMIT.
E0 already fixed the original pool transaction bug; E2 retains that helper for backfills and attachments.
Hash conflicts, missing bytes or mismatched metadata abort registration/backfill.

## Expansion and rollback

Migration `0018_content_addressed_media` adds only a table, nullable columns and foreign keys.
The data migrator copies and verifies content first, then registers objects and backfills references in one
transaction per database. It writes a durable source/old→new mapping before writes, supports dry-run and resume,
and revalidates the source snapshot under table locks before committing. A rerun changes no completed references.
Old `url`, `pathname`, `sha256`, width/height and cover JSON stay unchanged. New uploads fill the legacy descriptor
as well as the new reference, with the `m/` URL. The pre-E2 deployment reads every migrated row unchanged; its schema
rejects `m/` pathnames, so it stays a safe rollback target only until the first post-E2 upload to an asset owner.
Immutable catalog release JSON is not rewritten: the new reader resolves registered author/university covers by hash.
Rollback to the pre-E2 deployment reads the original legacy URLs; no database contraction or R2 deletion is needed.
Legacy columns can be removed only in a future, separately authorized contract phase.

No `m/` object is deleted by owner deletion or purge: references can also exist in another environment or an older release.
Cross-environment and release-aware garbage collection belongs to E5. Old `covers/` objects remain in place.

## Cost and verification

ADR-31 already disables Next image optimization globally and at `MediaImage`; this change preserves direct delivery.
Changing these URLs therefore adds zero Vercel transformations (Hobby includes 5,000/month).
The migration writes at most one R2 Class A copy per distinct content, approximately 2,689 operations and 313 MiB;
reads/checks are Class B. No paid resource or new credential is required.
See [Vercel limits](https://vercel.com/docs/image-optimization/limits-and-pricing),
[unoptimized delivery](https://vercel.com/docs/image-optimization/managing-image-optimization-costs),
[R2 conditional copy](https://developers.cloudflare.com/r2/api/s3/extensions/) and
[R2 pricing](https://developers.cloudflare.com/r2/pricing/).

Acceptance includes real-pool concurrency and rollback tests, checksum/metadata rejection, resumable migration,
zero-byte repeated uploads, preview→production checks and normalized initial server HTML parity (HTTP; PR and main with fixed data). Hydrated HTML and pixels are deferred to the end-of-day gate-noite report per Daniel, 2026-10-19 18:05 BRT.
Image URLs normalize only with proven SHA-256 equality; pixels remain report-only. Evidence lives outside the repository
under `auditoria/relatorios/e2-aceite/` and `auditoria/relatorios/e2-paridade/`.
