# Production changes and releases

Status: D-054 (2026-10-25), amended by OU-DECOUPLE (D-105, D-110, D-111), GitHub/AWS delivery (D-314), and `apps/web`
return (D-319). This file owns the rule for who may change production and how a change reaches it. The original reasons
are in the step 1 audit ([F3–F6](roadmap/STEP-01-audit.md#f3-migration-0033-is-not-waiting-it-is-already-in-production)).

This repository holds both the engine of A Torre (gate, model, events, registry, services) and Open University's course
site (`apps/web`, returned with fresh history by D-319). Two deployment paths exist and must not be confused:

- **Engine AWS deploy (automated on `main`, D-314):** merging an approved PR into `main` through GitHub's merge queue
  rings `.github/workflows/deploy-doorbell.yml` (`scripts/deploy status` reads it). Nobody pushes to `main` or deploys
  engine infrastructure by hand.
- **Open University site production (protected by D-054 / D-105):** served from AWS (the Lambda `open-university-web`
  behind CloudFront, its data in RDS `tower-data`) with media on Cloudflare R2; its image is built by CodeBuild
  (`apps/web/deploy/build-image.sh`). No coding session deploys, promotes, rolls back, or writes production data by
  hand. Pausing the Open University site is the last step of OU-DECOUPLE, and Daniel takes it (D-105).

## No production change by hand

No agent session, human or coding agent, deploys, promotes, rolls back, pushes directly to `main`, or writes production
data by hand. A forbidden manual production change is any of:

- a direct push or manual merge into `main` bypassing GitHub's merge queue and required checks (`tower/gate`, `web`,
  `gate pinned to the base`, D-314);
- a manual build, deploy, or rollback of the site's Lambda image, or a change to its production settings or secrets;
- a write to Open University's production RDS database or R2 bucket (D-105 keeps that data: nothing deletes or modifies
  it, and Cloudflare is not changed).

The freeze is enforced, not only written (PS1, D-054, D-069 item 13). `production.forbidden_entrypoints` in
`config/registry/production.json` is the one list of entrypoints that change production. It is empty while no session
CLI exposes a direct production deploy command. An entrypoint added there refuses to run in a cloud session (a marker
of `production.cloud_session_markers` is set; `scripts/lib/production_guard.py refuse`), and `scripts/structure-check`
refuses a PR diff that adds a mention of one outside `production.invocation_allowed_paths`.

Until Daniel pauses the site:

- **Site production is frozen to sessions.** None of the manual actions above is done by a session; the Torre handles
  any authorized site operations, and the production database is not touched.
- A change site production would need is written down in `docs/process/host-swap-queue.md`, in order, with the check
  that proves it.
- Local work stays local. Engine tests use only the local PostgreSQL (`scripts/cloud/env.sh`), and no preview is built.

## Pull requests and releases (D-314)

- Every PR branches from `main` on GitHub (`openuniversity-si/open-university`) and targets `main`. It lands only
  through GitHub's merge queue after the required checks (`tower/gate`, `web`, `gate pinned to the base`) pass on the
  head and on the queue commit (`D-314`). There is no review step (D-055); the PR body carries the B5 trailers
  ([STRUCTURE.md B5](STRUCTURE.md#b5-structure-owner-and-fit-review)).
- A merge into `main` triggers the automated engine AWS deploy doorbell (`.github/workflows/deploy-doorbell.yml`); it
  does not by itself perform a manual site-production release or database migration.
- The older `mod/roadmap-integration` integration branch and `origin pr merge --expect-head` flow belong to the dormant
  Origin era (D-314) and are no longer used for live delivery.

## Event-driven release (D-065)

Site releases are rare and event-driven, never on a clock. In the dormant Origin-era event model
([EVENTS.md](EVENTS.md)), `release.ready` was recorded on a full-battery tip; while site production is frozen, nothing
triggers a manual site release.

## What enforces it

- **On GitHub (`D-314`):** `.github/rulesets/main.json` protects `main` and requires the merge queue with
  `tower/gate`, `web`, and `gate pinned to the base`.
- **Locally (`D-054`):** `scripts/release-policy.json` (`frozen`, production/release branch policy) and
  `scripts/lib/release_policy.py` refuse writes to the real production host while the policy is frozen (a loopback test
  fake is not production). Unfreezing site production requires an explicit PR setting `frozen` to `false` with Daniel's
  approval.
