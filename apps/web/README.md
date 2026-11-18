# Open University — the site (`apps/web`)

The course site served at https://openuniversity.si (D-319): a Next.js App Router app with its own lockfile, Node 22
(`.node-version`) and the pnpm that `package.json#packageManager` pins, through Corepack. It runs on AWS (the Lambda
`open-university-web` behind CloudFront, its data in RDS `tower-data`) with its media on Cloudflare R2
(`media.openuniversity.si`). Nothing in it relates to a retired vendor (D-318; `scripts/retired-vendors` at the
repository root proves it).

Every command runs inside `apps/web`; none reads a file outside it.

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev                 # http://localhost:3000
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm test:int            # against PostgreSQL: TEST_DATABASE_URL (source ../../scripts/cloud/env.sh && pgtools_start)
```

On a pull request or a merge-queue entry that touches `apps/web`, the `web` check
(`.github/workflows/web.yml`) runs these same commands against a PostgreSQL service.

The environment it reads in production: `SITE_ENV=production` (indexable site, admin acts on production), `SITE_URL`,
`AUTH_URL`, `AUTH_SECRET`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, `APP_DATABASE_URL`, the R2 keys (`R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID_RO`, `R2_SECRET_ACCESS_KEY_RO`, and the RW pair for the admin media writes), `TOWER_ADMIN_MEDIA_SECRET`
and `TOWER_MEDIA_REVALIDATE_SECRET`. `BUILD_SHA` at build time is the commit the site shows. `FIGMA_FILE_KEY` is read
only by the fidelity tooling.

The media store (`src/media/server/r2.ts`, D-323 step 2) is chosen by `MEDIA_STORE`. Unset (or `r2`) keeps Cloudflare
R2 exactly as before, with the `R2_*` keys above (`R2_REGION`, default `auto`; `R2_ENDPOINT` only for a local test
server). `MEDIA_STORE=s3` uses Amazon S3: `MEDIA_S3_BUCKET` (the media bucket, `tower-media-<account>-us-east-1`) and
`AWS_REGION` (the Lambda sets it), virtual-hosted URLs `https://<bucket>.s3.<region>.amazonaws.com/<key>` signed for
service `s3`, and the runtime role's own credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_SESSION_TOKEN`, set by Lambda); no long-lived key, and read and write both go through the role, whose policy
decides. Any other `MEDIA_STORE` value is refused. Public URLs stay on `MEDIA_PUBLIC_HOST` (`media.openuniversity.si`)
in both modes. The migration and bulk tools (`media:migrate-r2`, `media-content-migrate`) and the fidelity harness keep
reading R2 by name.

The Lambda image: `deploy/build-image.sh <repository> <tag>...` builds this app with its frozen lockfile and the
image of `deploy/Dockerfile` (the Next.js standalone output behind the AWS Lambda Web Adapter). The CodeBuild project
`open-university-web` runs it on a commit of `main`; production changes are the Torre's (D-054,
`docs/process/RELEASES.md`).
