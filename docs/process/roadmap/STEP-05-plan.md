# Step 5 plan: vendors (Vercel Blob, Mux)

Target: Vercel Blob and Mux are gone from the code, the dependencies, the image config, the CSP, the schema, the tests
and the docs; R2 is the only object store and `media.openuniversity.si` the only accepted media host; every dependency
of `apps/web` is declared in a vendor map, each vendor SDK is imported only by its one driver module, and the checker
refuses a retired vendor, an undeclared or unused dependency, and a vendor import outside its driver. No visual change:
covers are already served from `media.openuniversity.si`, so the rendered pages stay the same. No backward
compatibility (D-029): what production still stores in the Blob era is rewritten by a queued data step, not accepted by
the code. Root causes and counts: [STEP-05-audit.md](STEP-05-audit.md).

Every PR branches from `origin/mod/roadmap-integration`, targets it, has 3–8 commits, stays under the B5 size budget
(≤ ~600 changed lines without tests and generated files), and ends with `Capability: CAP-010` and
`Fit-Review: not reviewed (Daniel 2026-10-25: no review step)` (D-055). `gate-db` needs Neon credentials this session
does not have; a PR with a migration is proven on the local PostgreSQL 18 integration tests and says so. Production
data is never read or written here: each rewrite is a host swap queue entry (D-054).

## Target (D-062)

### The vendor map

`scripts/lib/vendor-map.json` lists every package of `apps/web/package.json` (`dependencies` and `devDependencies`):

- `kind`: `vendor` (talks to one hosted service or binds the app to one host's product), `library` (runs in the
  process, names no host) or `tool` (a CLI, a config preset or types; may have no importer).
- `driver` (vendors only): the one module that may import it, for example `aws4fetch` → `src/media/server/r2.ts`.
- `retired`: packages that may not be declared or imported anywhere: `@vercel/blob`, `@mux/*`, `media-chrome`.

Rules (PR 5.7, no baseline):

| Rule | Fails when |
|---|---|
| `L3.vendor-driver` | a file anywhere under `apps/web/` or `scripts/` (production or test) imports a vendor package and is not its `driver` |
| `L3.dependency-declared` | a `package.json` dependency is missing from the map, a map entry is missing from `package.json`, or a `vendor` or `library` has 0 importers |
| `L3.vendor-retired` | a `retired` package is in `package.json` or imported anywhere; replaces `L1.mux-tombstone` |

`L7.one-store` (four packages, `media/server/` only) is folded into `L3.vendor-driver` and deleted. A test may reach a
vendor only through its driver or a fake, never by importing the SDK.

### One media host

`MEDIA_PUBLIC_HOST` is the only host `mediaUrlSchema`, `productionMediaPolicy`, `mediaPublicHosts`, `remotePatterns`
and the CSP accept (plus the dev and test R2 bridge `TOWER_MEDIA_PUBLIC_HOST`, which is not a production host).
`registerMediaHosts` loses `legacyHost`; `object-url.ts` maps only bucket URLs. A test fails when a second production
host is accepted.

### Data the code no longer accepts (queued, D-054)

| Queue | What | Check before / after |
|---|---|---|
| Q-08 | rewrite Blob-host media URLs to `media.openuniversity.si` (`media:migrate-r2 --target prod --rewrite-host`, which HEADs every key in R2 first), then publish a release so the active release carries only R2 URLs | count rows of `catalog_media`, cover JSON and the active release payload whose host is not `media.openuniversity.si`; after: 0, and the production hard check passes |
| Q-09 | tooling migration `0002_fidelity_object_key` on `tower_tooling` (`pnpm tooling:migrate`): every stored reference URL becomes its object key in `the-tower-fidelity` | count rows on a Blob host and HEAD every active key before; after: every row matches the key check and `fidelity:references` reads the active set |
| Q-10 | migration `0035_lesson_video_provider`: `lesson_videos.provider` accepts only `youtube`; drop `lesson_videos_mux_external` and the Mux columns `playback_id`, `playback_policy`, `resolution_tier` | count `provider <> 'youtube'` rows and rows with a value in those columns; both must be 0 before, else stop and escalate |
| Q-11 | delete the retired environment variables from the release host: `MEDIA_STORAGE`, `FIDELITY_STORAGE`, `BLOB_READ_WRITE_TOKEN`, `TOWER_MEDIA_BLOB_READ_WRITE_TOKEN`, `TOWER_FIDELITY_BLOB_READ_TOKEN`, `TOWER_FIDELITY_BLOB_READ_WRITE_TOKEN`, `MUX_*`; revoke the Blob and Mux tokens; then step 8 deletes the scanner names in `scripts/lib/bundle-scan.ts` | the host's environment lists none of them |

Order at the host swap: Q-08 and Q-09 before the first deploy of this step's code (the code refuses a Blob URL), Q-10
with the migrations, Q-11 after the deploy is verified.

## PRs

| PR | What | Root cause it closes | Enforcement added |
|---|---|---|---|
| 5.1 | This audit and plan, D-062, CAP-010, queue entries Q-08–Q-11 | — | D-062 entry (`test pending`) |
| 5.2 | Mux out of the app: `@mux/mux-video` and `media-chrome` removed from `package.json`; the Playwright `MUX_*` variables and `PLAYBACK_ORIGIN`, the bundle-check `mux-video` scan and the `mux-video` locator removed; ADR-11 amended (Mux removed, not paused) | F3 | `L1.mux-tombstone` keeps the files out until 5.7; `pnpm install --frozen-lockfile` |
| 5.3 | `lesson_videos.provider` accepts only `youtube` and the three Mux columns are dropped (migration 0035, schema, the catalog's table shape, the int test's Mux rows replaced by a refusal); Q-10 gets its migration name | F3 | the database check, proven on the local PostgreSQL integration tests |
| 5.4 | The media store is R2 only: `blob.ts`, `createMediaStore`, `mediaStorageMode`, `storage-env.ts` and `MEDIA_STORAGE` deleted; `optionalReadStore` reads R2 whenever read credentials exist; the media README follows (done, #464) | F1 | intents' database and code citations follow (`intents.test.ts`) |
| 5.5 | One media host (done, #465): `legacyHost` deleted (`blob-host.ts` keeps `legacyObjectKey` for the fidelity store until 5.6, which deletes the file); the URL schema, the policy, `remotePatterns` and the CSP accept `MEDIA_PUBLIC_HOST` only; every fixture and test on the public host | F2 | a media domain test that a second production host is refused |
| 5.6 | Fidelity references on R2 only (done, #466): stored by object key (tooling migration `0002_fidelity_object_key` renames `blob_url` and rewrites every URL to its key); `createVercelBlobStorage`, `FIDELITY_STORAGE` and `TOWER_FIDELITY_BLOB_*` deleted; `blob-host.ts`, `object-url.ts`, `storedUrlKey` and `objectKeyFromUrl` deleted; `@vercel/blob` removed from `package.json`; F03 and the media README describe R2 only. `fidelity:migrate-r2` stays: it is the only writer of the mask art | F1 | the key check in `tower_tooling`, proven on the local PostgreSQL integration tests |
| 5.7 | The vendor map and `L3.dependency-declared`, `L3.vendor-driver`, `L3.vendor-retired` with no baseline, over every file of `apps/web` (done, #467); `L1.mux-tombstone` and `L7.one-store` deleted, their fixtures kept as cases of the new rules | F3, F4 | the three rules |
| 5.8 | Close: D-062 proven, CAP-010 done, the step's metrics | — | — |

If a PR exceeds the size budget it is split in place (5.5a, 5.5b) and recorded on this plan.

## Metrics (step start → target → step end)

| Measure | Start (2858142b) | Target | After step 5 (PR 5.8) |
|---|---|---|---|
| `@vercel/blob` production importers | 2 | 0 | 0; `L3.vendor-retired` refuses a declaration or an import |
| Blob adapters | 2 | 0 | 0 (media PR 5.4, fidelity PR 5.6) |
| Blob environment names read by code | 5 | 0 | 0 (the variables leave the host with Q-11) |
| Accepted production media hosts | 2 | 1 | 1, `MEDIA_PUBLIC_HOST` (PR 5.5) |
| Files that use the Blob host | 17 | 0 | 2 tests: the refusal proof and the 0002 rewrite proof |
| Mux packages in `package.json` | 2 | 0 | 0 (PR 5.2) |
| Mux values in the schema | 1 provider, 1 index, 3 columns | 0 | 0, migration 0035 (PR 5.3, queued as Q-10) |
| Vendor URLs stored in `tower_tooling` | every reference image | — | 0: object keys, tooling migration 0002 (PR 5.6, queued as Q-09) |
| Dependencies declared in a vendor map | 0 of 31 | 31 of 31 | 28 of 28 (3 packages removed) |
| Vendor rules reading a declaration | 0 (2 incident rules) | 3 | 3, no baseline (PR 5.7); the 2 incident rules deleted |
| PRs | — | about 8 | 8 (#461–#468) |
