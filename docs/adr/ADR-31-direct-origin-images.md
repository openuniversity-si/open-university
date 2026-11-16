# ADR-31 — Direct origin images, no metered optimizer

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Accepted 2026-10-18, H1. Vercel Hobby exhausted image optimization and returned
`402 OPTIMIZED_IMAGE_REQUEST_PAYMENT_REQUIRED`. No paid plan or service is authorized.

Use the existing immutable R2 files and CDN, as Home cards and billboards already do.
Disable Next optimization globally and explicitly in MediaImage, retaining its markup,
dimensions, CSS, alt, placeholder and lazy behavior. No runtime resizing endpoint or new
resource. Existing ingestion budgets bound downloads; precompress future uploads locally.
The four acceptance pages' 26 distinct originals returned 200: p95 297 KiB, max 311 KiB
(legacy exception); no re-encoding or catalog modification is needed for recovery.

This avoids a per-transformation quota as the catalog grows. It does not claim unlimited
free storage/operations: keep R2 within its existing free allowance; egress is free.
Do not introduce Cloudflare Images/Transformations, imgix or another metered replacement.
The local gate guards component output, imports, config and built HTML in both targets.

Ship verification has an explicit `--direct-images` mode for the expected transport change.
Canonicalization only replaces an optimized img URL with its identical R2 source and
removes that image's transport-only sizes/srcset. It retains CSS, dimensions, alt and content,
and rejects a srcset pointing elsewhere. Default delivery parity remains strict.
Eight production page/viewport combinations must decode all visible images, receive real
200 image responses and match recovered-reference HTML, geometry and source SHA-256. Reference-only routing
resolves unavailable optimizer requests to the same original bytes and records each rewrite;
it is not presented as an unmodified screenshot of the broken production deployment.
Production verification does no rewriting and auto-rolls back on failure. Tests cover that path.

H1's first production verification received 134 image GET 200 and HTML 8/8, but exact PNG
comparison triggered rollback. Repeating the old deployment against itself reproduced up to
3/255 RGB differences in JPEG thumbnails, with unchanged source bytes and layout. This is
Chromium raster noise; exact PNG equality is not a reproducible baseline. The corrected check
requires identical fetched SHA-256, image rectangles, object-fit/position, radii and normalized
HTML, and allows at most 3/channel **only inside those unchanged images**. Any alpha change,
pixel outside image rectangles, changed source bytes, geometry or larger delta still fails.
The report exposes exact equality, changed-pixel count and maximum delta rather than claiming
bit-identical screenshots. Unit fixtures exercise each rejection, and image failures still roll back.

Rollback: Vercel Instant Rollback to the captured prior deployment; no DB/content changes.
That deployment still has the exhausted optimizer, so rollback restores code rather than
fixing image availability. Keep H1 or a corrected direct-delivery release in production.

Sources: [Next unoptimized](https://nextjs.org/docs/app/api-reference/components/image#unoptimized),
[R2 pricing and free allowance](https://developers.cloudflare.com/r2/pricing/).
