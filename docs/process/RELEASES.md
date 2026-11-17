# Production changes and releases

Status: D-054 (2026-10-25), amended by OU-DECOUPLE (D-105, D-110, D-111). This file owns the rule for who may change
production and how a change reaches it. The reasons are in the step 1 audit
([F3–F6](roadmap/STEP-01-audit.md#f3-migration-0033-is-not-waiting-it-is-already-in-production)).

This repository is the engine of A Torre (gate, train, events, registry, services). Production is Open University's
site, served from AWS (the Lambda `open-university-web` behind CloudFront, its data in RDS `tower-data`) with its media
on Cloudflare R2, and built from its own repository (D-318). Open University left this repository (D-111). Its
archive is commit `567176bb` (D-110). The engine has no production deploy of its own. Pausing the Open University site
is the last step of OU-DECOUPLE, and Daniel takes it (D-105).

## No production change by hand

No agent session, human or coding agent, deploys, promotes, rolls back, or writes production data by hand. A
production change is any of:

- a merge into `main`: it rings the engine's AWS deploy (`.github/workflows/deploy-doorbell.yml`, D-314);
- a build, deploy or rollback of the site's Lambda image, or a change to its settings or secrets;
- a write to Open University's RDS database or R2 bucket. D-105 keeps that data: nothing deletes or modifies it, and
  Cloudflare is not changed;
- a merge commit on `main` made in any other way, such as a GitHub merge.

The freeze is enforced, not only written (PS1, D-054, D-069 item 13). `production.forbidden_entrypoints` in
`config/registry/production.json` is the one list of entrypoints that change production. It is empty, because the
engine has none. An entrypoint added there refuses to run in a cloud session (a marker of
`production.cloud_session_markers` is set; `scripts/lib/production_guard.py refuse`), and `scripts/structure-check`
refuses a PR diff that adds a mention of one outside `production.invocation_allowed_paths`.

Until Daniel pauses the site:

- **Production is frozen.** Nothing above is done by a session; the Torre makes the site's changes, and the database
  is not touched.
- A change production would need is written down in the host swap queue, in
  order, with the check that proves it.
- Local work stays local. Engine tests use only the local PostgreSQL (`scripts/cloud/env.sh`), and no preview is built.

## The release unit

A pull request is not a release.

- Every PR branches from `mod/roadmap-integration`. It merges there with a merge commit on the exact head
  (`origin pr merge --expect-head`, AGENTS.md Delivery flow). There is no review step (D-055). The PR's trailer says so
  ([STRUCTURE.md B5](STRUCTURE.md#b5-structure-owner-and-fit-review)), and `scripts/structure-check --review <pr>`
  accepts it.
- A release is one merge of the integration branch into `main`. While production is frozen there is none.

## Event-driven release (D-065)

A release is rare and triggered by an event, never by a clock. `release.ready` ([EVENTS.md](EVENTS.md)) fires when
about 1,000 PRs have merged since the last release, or at a milestone, on a tip the full battery passed. While
production is frozen, `release.ready` is only recorded.

## What enforces it

`scripts/release-policy.json` is the only switch (`frozen`, the production and release branches).
`scripts/lib/release_policy.py` refuses every write to the real production host while the policy is frozen. A loopback
test fake is not production. Frozen or not, a merge into `main` is refused unless its head is `mod/roadmap-integration`
of this repository (`delivery.merge_allowed_bases`, read by `scripts/lib/release_policy.py`; the GitHub REST merge
that also enforced it left with D-293). Unfreezing is a PR that sets `frozen` to
`false`.

The scripts cannot stop a merge into `main` made by hand, with `origin pr merge` or the Origin web UI. Until Origin
itself restricts merges into `main` (host swap queue Q-06), whoever does it breaks this rule.
