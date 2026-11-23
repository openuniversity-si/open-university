# Host swap queue

D-054. Production is frozen ([RELEASES.md](../process/RELEASES.md)). Every production change the code needs and
production does not have is listed here, in the order it runs. Nothing here runs by hand.

Production was Open University's site, which left the repository (D-111). Its queue held Q-01–Q-05 and Q-07–Q-11: the
database migrations from 0033 on, the media and fidelity rewrites to R2, the first release deploy and the retirement of
the old blob and Mux tokens. It is archived with Open University at `567176bb` (D-110,
`git show 567176bb:docs/process/host-swap-queue.md`). Those items run only if Open University comes back, from its
archive and through a release pipeline of its own. The engine has no database migration journal, so
`scripts/structure-check` has no migration to hold against this file.

## Queue

### Q-06. Restrict merges into main on the forge

- not a migration: a repository setting on the selected forge (`forge-events.adapter`, today Origin), made by the
  repository owner (Daniel); agent tokens cannot change it
- why queued: the scripts refuse a non-release merge into `main` (`scripts/lib/release_policy.py`), but a plain
  merge through the forge's own client or web UI does not run them (RELEASES.md, "What enforces it")
- setting: a rule on `main`, where the forge offers one, that allows only a pull request from `mod/roadmap-integration` to merge, with a merge
  commit, and blocks force pushes and deletions
- check: a test PR from any other branch into `main` shows as blocked; the release PR is mergeable

### Q-13. Build the site from apps/web and retire the old vendors' variables and data (D-318, D-319)

- not a migration of this repository: production steps of the Torre, in this order; each has its check, and a red
  check stops the order there (nothing below it runs). No value of a secret is ever printed.
- why queued: since D-319 the site's source is `apps/web` of `main`, cleaned of the retired vendors (D-318); the
  running image `lambda-251b64f` still comes from the archived `dsbello/the-tower` and still reads their variables.

1. **R2, bare keys.** The code reads media only at `https://media.openuniversity.si/<pathname>` with `<pathname>`
   under `covers/` or `m/`, and fidelity references at the object URL of `<pathname>` in `the-tower-fidelity`; it names
   no copy prefix. For every pathname P of the blob manifest: in `open-university-media`, P must hold the manifest's
   sha256 (server-side copy from the copy prefix of its store where P is absent); the same in `the-tower-fidelity`.
   Check: every P present with its sha256, no P outside `covers/` and `m/` for the two public stores, and no P that the
   two public stores both hold with different bytes (either stops the step and is reported).
2. **RDS `tower_v1`, the stored URLs** (one transaction): `catalog_media.url` becomes
   `https://media.openuniversity.si/` || `pathname` where the URL is on a public blob host and its path equals
   `pathname`; `authors.cover->>'url'` and `home_rows.cover->>'url'` keep their path and take the host
   `media.openuniversity.si` (revision + 1). `tower_tooling.fidelity_reference_image.blob_url` takes the object URL of
   the same pathname in `the-tower-fidelity`. Check: the inventory query (rows on a blob host, per table) returns
   nothing in either database. The releases and projections are content-hashed snapshots and are not edited.
3. **A new catalog release** so the active release carries the new URLs: `apps/web/tooling/tower-catalog release diff
   --target prod` shows only media hosts changing, then `release create --note "D-318: media on
   media.openuniversity.si" --target prod`. Check: `release list` shows it active.
4. **`SITE_ENV=production`** added to the secret `open-university/web-env` and to the Lambda's environment, beside
   the old variables (the running image still reads them). Check: the Lambda's configuration has `SITE_ENV`.
5. **The CodeBuild project `open-university-web`** takes the buildspec of D-318's report to the Torre (17/11/2026): the source is a
   fetch of `SRC_SHA` (a 40-hex commit of `main`) from `https://github.com/openuniversity-si/open-university`, the
   build runs `scripts/retired-vendors` and then `apps/web/deploy/build-image.sh`, and pushes `lambda-<sha7>` and
   `live`. The ECR source image `src-251b64f` is no longer read. Check: the build SUCCEEDED, its log shows
   `retired-vendors: 0 reference(s)` and both tags are in ECR.
   Every release since D-364 starts only after `GITHUB_TOKEN="$(gh auth token)" apps/web/deploy/promotion-guard.sh
   <SRC_SHA>` exits 0 (the commit's newest `full-suite` run is green); any other exit starts no build.
6. **The Lambda `open-university-web`** runs `lambda-<sha7>` (update-function-code, wait for function-updated). Check:
   `LastUpdateStatus` Successful and the `ImageUri` of the new tag; then a CloudFront invalidation of `/*` on
   E20KHUP9NU9TI4.
7. **Smoke**: `https://openuniversity.si/`, `/api/health`, a course page and `/robots.txt` answer 200 (robots allows
   `/`, no `X-Robots-Tag: noindex`); a cover URL of the HTML on `media.openuniversity.si` answers 200; neither the
   HTML nor the `Content-Security-Policy-Report-Only` header names a blob host. The rollback is step 6 with
   `lambda-251b64f`.
8. **The old variables leave** the Lambda and the secret: every name that matches a pattern of
   `structure.retired_vendor_terms` (one, today), `BLOB_READ_WRITE_TOKEN` and the three `TOWER_MEDIA_BLOB_*`; and,
   unread by the new code, `MEDIA_STORAGE`, `CATALOG_MODE`, `MUX_SIGNING_KEY_ID`, `NEXT_PUBLIC_MUX_DATA_ENV_KEY`.
   Check: the configuration names none of them, and step 7 passes again.
9. **Then** the blob stores and the R2 copy prefixes may be deleted (the Torre's, after step 8 is green).
- also: `services/runner/github/web.yml` is installed as `.github/workflows/web.yml` (D-087), and after its first green
  run the merge queue may require the check `web`.

### Q-12. Pause the Open University site (D-105)

- not a migration: the last step of OU-DECOUPLE, taken by Daniel after the archive exists and the removal has merged
- action: the least destructive one that takes the site offline, announced on the PR first. The RDS and R2 data are not
  deleted or modified, and Cloudflare is not changed
- check: the site no longer serves
