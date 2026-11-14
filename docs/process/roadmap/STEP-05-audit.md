# Step 5 audit: vendors (Vercel Blob, Mux)

Roadmap step 5 of 8 (D-054). Audited on `mod/roadmap-integration` 2858142b (step 4 closed, #460), 2026-10-26, by the
roadmap implementer session. A Torre's baseline audit (main 198aa130) was the starting hypothesis. Each finding is
verified, corrected or extended below with exact counts and file lists.

## How the counts were taken

- **Importer**: a file with an `import … from "<pkg>"`, `import "<pkg>"` or `import("<pkg>")` of the package or one of
  its subpaths, found with `rg` over `apps/web/` and `scripts/` (not `node_modules/`). A **production importer** is not
  a `*.test.ts`, `*.int.test.ts` or `*.test-helpers.ts` file.
- **Vendor SDK**: a package whose job is to talk to one hosted service or to bind the app to one host's product
  (`@vercel/blob`, `@mux/*`, `media-chrome` as Mux's player shell, `aws4fetch` as the R2 signer). A **library** runs in
  the process and names no host (`zod`, `sharp`, `pg`, `drizzle-orm`, `better-auth`, `react`).
- **Blob host user**: a file that imports `src/media/server/blob-host.ts` or writes `blob.vercel-storage.com`.

## Baseline

| Measure | A Torre (198aa130) | Verified (2858142b) |
|---|---|---|
| `@vercel/blob` production importers | `media/server/blob.ts`, `storage.ts` | **2**: `src/media/server/blob.ts` and `fidelity/references/storage.ts` (`storage.ts` reaches it through `blob.ts`). Declared in `devDependencies` although `blob.ts` is server code |
| Blob code paths | media | **2** adapters: the media store (`createBlobMediaStore`, selected by `MEDIA_STORAGE`, default `blob`) and the fidelity reference store (`createVercelBlobStorage`, selected by `FIDELITY_STORAGE`, then `MEDIA_STORAGE`, default `blob`) |
| Blob environment names read by code | — | **5**: `MEDIA_STORAGE`, `FIDELITY_STORAGE` (blob or r2 switches), `TOWER_MEDIA_BLOB_READ_WRITE_TOKEN`, `TOWER_FIDELITY_BLOB_READ_TOKEN`, `TOWER_FIDELITY_BLOB_READ_WRITE_TOKEN` |
| The legacy Blob host | in `next.config` `remotePatterns` | **1** constant (`media/server/blob-host.ts`), registered into the media domain as `legacyHost` (`public-hosts.ts`), so it is accepted by `mediaUrlSchema`, `productionMediaPolicy`, `mediaPublicHosts` and therefore by `next.config.ts` `remotePatterns` **and** the CSP `img-src`; `object-url.ts` maps a Blob URL to its key |
| Blob host users | — | **17** files: 4 production (`blob-host.ts`, `blob.ts`, `object-url.ts`, `public-hosts.ts`), 13 tests and fixtures (`test/fixtures/admin-catalog.ts`, `test/int/{catalog-admin-content,catalog-media,media-r2,media}.int.test.ts`, `src/media/{domain/object-store,domain/objects,server/admin,server/storage,testing/fake}.test.ts`, `scripts/lib/{media-migrate,check-architecture}.test.ts`), plus 4 tests that write the host as a literal (`prepare.test.ts`, `r2.test.ts`, `scripts/tests/test_production_check.py`, and `object-store.test.ts` again) |
| Blob URLs in seed content | — | **0**: `content/media-fixtures.json` holds 151 URLs, all on `media.openuniversity.si`; `content/catalog/*.json` holds none |
| Dead Blob-era code | — | `createMediaStore` (0 production callers), `getMediaStorageEnv` in `media/server/storage-env.ts` (0 production callers; only `kernel/env.test.ts`) |
| Mux dependencies | `@mux/mux-video`, used only by bundle-check and Playwright | **2** runtime dependencies, `@mux/mux-video` 0.31.5 and `media-chrome`, both with **0** importers. `bundle-check.ts` only greps the build for the string `"mux-video"` |
| Mux test-only uses | — | `playwright.config.ts` sets `MUX_SIGNING_KEY_ID` and `MUX_SIGNING_PRIVATE_KEY` (nothing reads them); `e2e/player-states.spec.ts` counts `mux-video` elements; `test/int/catalog.int.test.ts` inserts two `provider = 'mux'` rows |
| Mux in the database | — | `lesson_videos_provider` allows `('youtube', 'mux')`; the partial index `lesson_videos_mux_external` exists only for non-YouTube rows (`schema.ts:324-325`, migration 0023). **Amended in PR 5.3:** three Mux asset columns, `playback_id`, `playback_policy` and `resolution_tier` (migration 0005), which no YouTube row fills; the catalog's table shape and four fixtures named them |
| Mux in docs | — | ADR-11 says the Mux engine "stays in the repository, paused"; its files are gone (14 paths in `muxTombstones`) |
| Vendor rules in the checker | 0 violations reported | **2** incident rules: `L7.one-store` (four package names, only under `media/server/`) and `L1.mux-tombstone` (a list of 14 deleted paths). No rule covers `fidelity/`, `scripts/` or any other folder; no rule says which module owns a vendor; no rule refuses an unused or undeclared dependency |
| Dependencies with 0 importers | — | runtime: **2**, both Mux (`@mux/mux-video`, `media-chrome`); dev: 8 tools a CLI or a config reads without an import (`@types/*` ×4, `@vitest/coverage-v8`, `eslint`, `stylelint-config-standard`, `typescript`) |

Kept on purpose, not a vendor use: the e2e no-video guard (`e2e/fixtures/no-video-policy.ts` blocks `mux.com` and
`litix.io` requests and media resources; AGENTS.md "No video in tests") and the secret scanner's names and patterns
(`scripts/lib/bundle-scan.ts`: `BLOB_READ_WRITE_TOKEN`, `vercel_blob_rw_…`, `MUX_*`). The scanner protects against a
leak of a token that still exists in the Vercel project's environment until the host swap removes it (plan Q-11).

## Findings

### F1. Vercel Blob is still a live storage adapter, twice

Verified and extended. A Torre found the media adapter. There is a second one: the fidelity reference store
(`fidelity/references/storage.ts`) imports `@vercel/blob` directly, outside `media/`, and is the **default** when
`FIDELITY_STORAGE` and `MEDIA_STORAGE` are unset. The media adapter is also the default of `mediaStorageMode` (`blob`
when `MEDIA_STORAGE` is unset), and `optionalReadStore` returns no R2 reader unless `MEDIA_STORAGE=r2`. The admin and
catalog write store (`createWritableMediaStore`) is already R2 only, so the Blob media adapter is reached only through
`createMediaStore`, which has no production caller.

Why-chain:
1. Two Blob adapters, five Blob environment names and a `blob` default remain after the switch to R2.
2. The R2 switch (2026-10-11) was added beside Blob behind a mode flag "until prod is verified", and the flag's default
   was never flipped or removed.
3. Nothing records when a switch is finished: the media README still says "default blob until prod is verified", and
   no decision or queue entry owns the retirement.
4. D-029 (no backward compatibility) is enforced for tables and assets (`docs/structure/assets.json`), but not for code
   paths selected by an environment flag; a flag keeps a dead adapter compiling and tested.
5. **Root cause: there is no declared owner per vendor.** No file says "Blob is retired" or "R2 is the media store and
   `media/server/r2.ts` is its only driver", so neither the checker nor a reviewer can refuse the second adapter, the
   fallback or the import from `fidelity/`.

### F2. The legacy Blob host is part of the media domain's accepted hosts

Verified and extended. The host is not only in `next.config.ts`: `public-hosts.ts` registers it as `legacyHost`, so the
domain's `mediaUrlSchema` accepts a Blob URL as a valid stored cover, `productionMediaPolicy` resolves release covers
against it, and both `remotePatterns` and the CSP `img-src` allow it. `storedObjectKey` (`object-url.ts`) and the
fidelity R2 store map a Blob URL to its object key, so URLs written in the Blob era still resolve.

Why-chain:
1. A Blob URL is a valid cover URL in the domain, the image config and the CSP.
2. The host switch kept old rows readable instead of rewriting them (`media:migrate-r2 --rewrite-host` exists and
   rewrites only the host, but the code still accepts both).
3. The production database could not be read or rewritten from a session, so the code was made to accept both.
4. There was no place to queue a production rewrite and drop the compatibility in the same change; the host swap
   queue (D-054) now is that place.
5. **Root cause: compatibility with stored data was solved in code instead of in a queued data rewrite**, and no rule
   refuses a second accepted host.

Data the rewrite must cover (none of it is read here; production is frozen): `catalog_media.url`, the `cover` JSON of
`authors` and institutions, the immutable `catalog_releases.payload` snapshots (an old release with a Blob URL can no
longer be activated once the host is refused), and `fidelity_reference_image.blob_url` in `tower_tooling`. The
production hard check already accepts only `media.<site>` covers (`scripts/lib/production_check.py`
`is_real_cover_url`), which suggests the active release is on R2; the queue entry measures it before the rewrite.

### F3. Mux is a dead dependency family with test-only and schema leftovers

Verified and corrected. `@mux/mux-video` has 0 importers, not "used by bundle-check and Playwright": bundle-check greps
the build output for its name, and Playwright sets two signing variables nothing reads. `media-chrome`, Mux's player
shell, is also declared and has 0 importers. The schema still accepts `provider = 'mux'` and keeps a Mux-only index.
ADR-11 still describes a paused Mux engine whose 14 files are deleted.

Why-chain:
1. Two Mux packages stay in `dependencies`, two Mux variables in the e2e environment, a Mux provider in the schema.
2. The engine switch to YouTube (ADR-11, v02) deleted the engine and guarded the deleted paths, but kept "paused" as the
   status, so its dependencies and data shape were left for a return.
3. The guard chosen was a tombstone list of file paths (`L1.mux-tombstone`): it proves the files stay deleted, not that
   the vendor is gone.
4. Nothing compares `package.json` with the imports: a dependency nobody imports is invisible to lint, typecheck,
   build and the checker.
5. **Root cause: dependencies are not declared data.** There is no list of which packages the app uses, what each is
   (vendor, library, tool) and which module may import it, so an unused or retired vendor cannot fail a check.

### F4. The checker's vendor rules are incident rules

Verified. `L7.one-store` lists four packages and only looks under `media/server/`; it did not see `fidelity/`'s
`@vercel/blob` import. `L1.mux-tombstone` lists paths. Both pass today with the Blob adapter and the Mux dependencies
in place, which is A Torre's "the checker is too permissive" for this step.

Why-chain:
1. 0 violations while a vendor SDK is imported from two folders and two vendor packages are unused.
2. Each rule was written for the incident that produced it (one store in media, the Mux removal).
3. The rules hold their facts inline (package names, paths) instead of reading a declaration.
4. There is no declaration to read (F3's root cause).
5. **Root cause: no vendor map**, the vendor equivalent of step 4's context map.

## Root causes → enforcement (summary)

| Root cause | Enforcement (plan) |
|---|---|
| No declared owner per vendor (F1, F4) | `scripts/lib/vendor-map.json`: every dependency of `apps/web/package.json` declared as `vendor`, `library` or `tool`; each vendor names its one driver module. `L3.vendor-driver` refuses an import of a vendor package outside its driver, everywhere (`src/`, `scripts/`, `fidelity/`, `e2e/`, `test/`) |
| Dependencies are not declared data (F3) | `L3.dependency-declared`: a package in `package.json` and not in the map, or in the map and not in `package.json`, fails; a `vendor` or `library` with 0 importers fails |
| Retired vendors can come back (F1, F3) | the map's `retired` list (`@vercel/blob`, `@mux/*`, `media-chrome`): present in `package.json` or imported anywhere fails; replaces `L1.mux-tombstone` |
| Compatibility solved in code (F2) | D-062: one accepted media host, `MEDIA_PUBLIC_HOST`; the legacy host contribution is deleted from the domain; the data rewrite is queued (Q-08, Q-09) and a test fails when a second accepted host is registered |
| A finished switch has no owner (F1) | D-062 and the host swap queue; the media README and F03 describe R2 only |
