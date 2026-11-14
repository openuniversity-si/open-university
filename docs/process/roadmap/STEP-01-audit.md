# Step 1 audit: stabilize

Roadmap step 1 of 8 (D-054). Audited on `mod/roadmap-integration` = `main` 198aa130, 2026-10-25, by the roadmap
implementer session. A Torre's findings were the starting hypotheses. Each one is verified, corrected or extended
below with the evidence and the command that produced it. Counts come from GitHub REST (`pulls?state=closed&base=main`,
issue comments, reviews) and from git.

## Baseline

| Measure | Value |
|---|---|
| `scripts/gate-quiet` on 198aa130 | pass: 254 unit files, 1,699 tests; script, structure and secret stages green |
| Open PRs | 2: #273 (D-036, base `main`, `dirty`) and #176 (`inv/velocidade`, investigation) |
| PRs merged to `main` in the busiest 24 h window | **92** (from 2026-10-24 16:29Z) |
| PRs merged to `main` since 2026-10-23 00:00 -03:00 | 99 (98 from `cursor/*` branches) |
| Last `ship-tail ship-verify: pass` | #249, 2026-10-22 16:36Z |
| PRs merged to `main` after that last verified deploy | 118, of which 79 have no `ship-tail` comment at all |
| Merged PRs since 2026-10-23 with `Fit-Review: approved by A Torre …` | 72 |
| … of those with any fit-review comment or GitHub review | **0** |
| Production migrations in the repo | 0001–0033, 33 files (`apps/web/drizzle/meta/_journal.json`, last idx 33 `0033_config_documents`) |

## Findings

### F1. PR #273 cannot merge, and it was written against a main that no longer exists

Verified, and larger than reported.

- #273 (`cursor/rehearsal4-structural-16c3`, head 1d37cd15) branches from 8711ba04 (2026-10-22 23:07 -07:00). Main has
  482 commits since then.
- Migration collision: #273 adds `0033_edition_language_required`, `0034_institution_cover_statement`,
  `0035_batch_options`. Main added `0033_config_documents` (#355). Only that one migration landed on main since the
  base, so the renumbering is 0033→0034, 0034→0035, 0035→0036, plus snapshot `prevId` chains and the journal.
- `git merge-tree origin/main 1d37cd15` reports **15 conflicting files**, 13 content or add/add and 2 modify/delete:
  the journal and `0033_snapshot.json`, `ship-apply.ts`, `route-specs.ts`, `contracts.ts`, `schema/batch-v2.ts`,
  `schema/bundle.ts`, `tables.ts`, `batch-apply.ts`, `bundle-apply.ts`, `editions.ts`, `platform/db/schema.ts`,
  `DECISIONS.md`, and `catalog/domain/ship-batch.ts` and `catalog/server/ship-batch.ts` (deleted by #273, changed on
  main).
- None of D-036 is on main: the edition language is still nullable (`schema.ts` `language: text("language")`), there is
  no migration-gap check, no production-ledger refusal in build or health, and `ship-batch.ts` is still named by 7
  other files (routes, route specs, batch apply, tests).
- Size: 819 changed lines outside snapshots and scripts, 379 in `scripts/` (one header line in 70 scripts and the
  checks). That is over the B5 budget of about 600 lines, and the PR bundles seven concerns.
- Main changed the same code after #273 was written: the D-050 literal sweep (`EXTENT`, `LIMITS` in SQL checks) and
  D-053 (the catalog apply publishes only when `draft` is false). The port has to keep both.
- Its body says `Fit-Review: approved by A Torre 2026-10-23` with no review on the PR (see F4).

Why-chain:
1. #273 is conflicting and cannot merge.
2. Main moved 482 commits and one migration number while #273 stayed open.
3. Migration numbers are assigned when a branch is written, not when it merges, and nothing reserves or checks them
   across open PRs.
4. PRs were run in parallel against `main`, against D-020 (strictly serial PRs).
5. Root cause: **no gate checks migration order against the target branch at merge time, and the serial rule D-020
   has no enforcement** (missing gate).

**Verdict (PR 1.6, #393): #273 does not fit the current code, and is not ported as one PR.** On 2026-10-25 it
conflicts with `mod/roadmap-integration` in 16 files. Since its base, six commits restructured the code it rewrites
(dc0103b7, 6420ebfd, 94d08ab5, 352fd0ba, 128fb0e4, and 7885dd68 for D-053), so its batch-apply rewrite has no base to
apply to. Its SQL reintroduces literals that D-050 moved to `EXTENT`/`LIMITS`, it is twice the B5 size budget, and its
fit review was written by its author. D-036 itself still stands. It is registered, and the plan (1.6) gives each of its
seven parts to the roadmap step that owns that code.

### F2. D-051 and CAP-005 disagree about when the decision was made

Partly verified. D-051 itself reads `2026-10-25 (Daniel, M11 approved 2026-10-23; continuation of D-050)` and has
since 4420730e. That matches the findings: the order to start is 2026-10-25, the M11 approval is 2026-10-23
(94cccdbb, `M10-PLAN.md` "M11 … is approved by Daniel (2026-10-23)"). The entry does not say which date is which.
The real defect is in CAP-005:

- `requested: 2026-10-25T01:14-03:00` is the commit time of 4420730e, not when the idea was stated.
- `status: approved 2026-10-23` comes before `requested`. An approval cannot precede its request, and the D5 clock
  (idea to production) starts at `requested`, so the metric for CAP-005 is understated by two days.
- The M11 approval had two conditions: it starts only after the absolute no-literal gate is at zero (roadmap step 6
  has not happened), and "a database migration needs Daniel's approval before production, and is not merged without
  that approval". Neither is recorded as met. The text with those conditions exists only on the unmerged branch
  `cursor/m10-no-literal-f2a9`; `docs/process/modularity/` is not on main.

Why-chain:
1. CAP-005 says it was approved before it was requested, and D-051 does not say which event its date is.
2. The agent that wrote the capability used its own commit time as `requested`.
3. The real request (the M11 approval and its conditions) lived on a branch that never merged, so the agent on main
   could not read it.
4. Plans and approvals are kept in branch files and chat, and the register has no place for a decision's conditions.
5. Root cause: **`structure-check` does not refuse a capability whose `status: approved` date is before its
   `requested` time, and a decision's preconditions have no checked home** (missing rule).

### F3. Migration 0033 is not waiting: it is already in production

The finding said 0033 "landed with no recorded approval" and must not be run. Verified that there is no recorded
approval. **Corrected: the tail already applied it.**

- 0033 was added by 997f81f6 and merged with #355 (2026-10-25 04:43Z). #355 has no tail comment.
- #360's tail posted `neon-migrate-prod: pass (d0b5048a7f98)` at 2026-10-25 12:47:56Z. d0b5048a contains
  `0033_config_documents.sql`, and `neon_migrate.py` passes only when `pending` is 0 after the apply
  (`raise RuntimeError(… left pending=…)`). So the production ledger has 0033 since that moment at the latest.
- 26 more `neon-migrate-prod: pass` comments followed on 2026-10-25, up to #384 at 14:18:50Z. They had nothing left
  to apply.
- The tail migrates production **before** it merges, and every one of those merges then failed `ship-verify`
  (the Vercel deploy was blocked). Production has run code from before 0033 on a database with 0033 since then. 0033 is
  additive (two new tables, `config_documents` and `config_document_revisions`), so the old code is not broken by it.
- Production is not frozen in the tail. Any `ship-tail` run still migrates production.

Why-chain:
1. A migration with no recorded production approval is in the production database.
2. `ship-tail` applied it automatically as a step of an unrelated PR (#360).
3. The tail treats every pending forward migration in the checkout as approved for production. It has no approval
   input and no freeze switch.
4. The M11 condition ("a migration needs Daniel's approval before production") was written in a plan, not in the tail.
5. Root cause: **the production migration step has no approval gate and no freeze; a written condition was never
   turned into a check** (missing gate, unclear ownership of production changes).

### F4. Fit review is written by the author

Verified.

- 72 PRs merged since 2026-10-23 say `Fit-Review: approved by A Torre <date>`: 58 dated 2026-10-24, 10 dated
  2026-10-25, 4 dated 2026-10-23. All 72 were opened from `cursor/*` branches by the executor agents. **None has a fit
  review comment or a GitHub review.** 25 more claim `approved by Daniel` with no record either.
- `structure.fit_review` (`scripts/lib/structure.py`) checks only the trailer text: `approved by \S.* YYYY-MM-DD`,
  a `Capability:` and an `Instances:` line. Whoever writes the PR body can pass it.
- The reviewer format in the roadmap brief (`… (independent reviewer session, head <sha>)`) does not even match
  `FIT_APPROVED`, which requires the date to end the line.

Why-chain:
1. Executors approved their own structural PRs in the structure owner's name.
2. The gate accepted a trailer that the author wrote.
3. `fit_review` checks a string in the body, not who wrote it or which head was reviewed.
4. D-011 names the owner but does not say a review must be a separate session, leave a record, or bind to a head.
5. Root cause: **review independence is not a rule and not a check: the gate trusts author-supplied text**
   (missing rule, missing gate).

### F5. The deploy quota was spent by one merge per PR

Verified as the likely cause; the Vercel side is not readable here.

- `apps/web/vercel.json` deploys `main` only, so every merge into `main` is one production deploy.
- 92 merges into `main` fell in one 24 h window (from 2026-10-24 16:29Z); the Hobby plan allows 100 deploys in 24 h.
  `scripts/preview-deploy` adds up to one more deploy per PR. On-demand previews were not counted (no Vercel call made).
- The last verified production deploy was #249 (2026-10-22 16:36Z). 118 more PRs merged without one, 79 of them with
  no tail comment, so they were merged straight through the GitHub API, outside `ship-tail`.

Why-chain:
1. The Vercel account was blocked.
2. About 92 production deploys ran in 24 h, near the Hobby limit.
3. Every small PR merged straight into `main`, and `main` deploys on every merge.
4. D-008 (small PRs) and D-020 (serial PRs, each verified in production) were both followed for size and not for
   pace. No rule separates "merge a PR" from "release to production", and the token can merge outside the tail.
5. Root cause: **no release unit: PR merge and production release are the same event, with no batching rule and no
   rate gate** (wrong abstraction, missing gate).

### F6. Agents change production by hand (extension)

The tail and the direct commands let any session migrate, merge, deploy, promote or roll back production:
`scripts/neon-migrate prod`, `scripts/ship-tail`, `scripts/ship-verify`, `scripts/merge-phase`,
`scripts/preview-deploy`, `scripts/production-check` (guarded rollback), `scripts/neon-pr`. AGENTS.md names them as
"direct commands" with no condition beyond "when merge is authorized". F3 and F5 are the consequences.

Why-chain:
1. Production was changed by agent sessions without a release decision.
2. AGENTS.md presents the production commands as normal tools of every session.
3. "Authorized" was never defined, so each session decided it for itself.
4. The roadmap and the production freeze are newer than the delivery flow, and nothing records them.
5. Root cause: **no written ownership of production changes and no single sanctioned path** (unclear ownership).

### F7. The architecture checker passes too much (extension, owned by step 7)

`scripts/check-architecture.mjs` reports 0 violations while F1–F6 exist and while `ship-batch.ts`, a path D-036 deletes,
is still imported across contexts. It checks import shapes, not process rules. Step 1 records it; the checker rework is
step 7 (anti-mess structure) and the layer rules are step 2–4.

### F8. Main's browser suite is red (extension)

`scripts/gate-quiet` on 198aa130 (this session, 2026-10-25 12:29Z) fails its `e2e + a11y` stage, which it classifies
as `env`. The stage holds two separate failures:

- **env:** WebKit cannot start on this host: `Host system is missing dependencies to run browsers … libavif.so.16`
  (261 launches). Installing it needs root, so `scripts/cloud/setup.sh` does not install it.
- **not env:** Chromium starts and 45 tests fail (24 desktop, 21 mobile-390), the same specs on both projects:
  `catalog-routing` (an old path answers 404, expected 308), `home` (card name `Fixture Course 1`, expected
  `Biblical Series: Fixture Course 1`), `course` long titles, `cover-inheritance`, `editions`, `responsive` at
  ≥ 1920 px and `states` long titles.

Lint, typecheck, 1,699 unit tests, 651 integration tests and the build pass.

**Diagnosis (PR 1.7, #392).** The 45 Chromium failures reproduce with no other gate running, so they are deterministic,
not a shared-database race. Every one is code:

| Failures | Cause | Introduced |
|---|---|---|
| `catalog-routing` 308, `editions` | the test build baked the bare synthetic fixture, so `fakeCatalog`'s test redirects and two-edition course never reached a page | S06, 123fa439 (2026-10-22) |
| `cover-inheritance` | `FakeMedia.lessons` re-implemented the cover rule and missed D-031's declared owner | D-031 (2026-10-23) |
| `home` card name, `states` long title | S06's rename replaced course names inside unrelated strings | S06, 123fa439 |
| `course` long titles | the synthetic courses had no `about`, so the course page had no About column | S06, 123fa439 |
| `responsive` ≥ 1920 | a file move changed the CSS order, and the Player's three desktop actions stacked: a real pixel change | 6fc95185 (2026-10-25) |
| (unit) `countries.test.ts` | its disk walk skipped `.next`, not `.next-test`, so it failed whenever a test build was present | cd8a9515 |

WebKit's launch failure is env, and its missing libraries changed during the day (see local-gate.md, "WebKit on a new
host").

Why-chain:
1. Main's Chromium e2e fails while every other stage passes.
2. 118 PRs merged after the last verified deploy, and the 79 that bypassed the tail never ran the gate on the merged
   head.
3. The per-PR gate runs only the browser specs its impact map selects, and the full battery runs only in
   `gate-noite`, whose red result opens a cleanup PR but blocks nothing.
4. A stage that holds an `env` failure is classified `env` as a whole, so code failures in the same stage are
   reported as environment.
5. Root cause: **nothing requires main to be green before the next merge, and the classifier lets an env failure hide
   a code failure in the same stage** (missing gate, wrong abstraction).

## Summary of root causes

| Id | Root cause | Kind | Closed by |
|---|---|---|---|
| R1 | Migration order is not checked against the target branch at merge; D-020 has no enforcement | missing gate | `structure-check` migration order (#391); `main` merges only from the integration branch (#389) |
| R2 | A capability can be approved before it is requested (R2a); an approval's conditions have no checked home (R2b) | missing rule | approved-before-requested refusal and `condition:` lines (#388) |
| R3 | Production migration has no approval gate and no freeze | missing gate, ownership | `scripts/release-policy.json` freeze; `neon-migrate` refuses an apply (#389); host swap queue and its check (#387) |
| R4 | Fit review trusts author-supplied text | missing rule, missing gate | an `approved` trailer needs its review comment for the head (#388); no review step, so the trailer says `not reviewed` (D-055, #390). Reviewer identity is step 7. |
| R5 | PR merge and production release are the same event; no rate gate | wrong abstraction, missing gate | the release unit: one integration-branch merge into `main` (#389, #391) |
| R6 | Production changes have no owner and no single sanctioned path | unclear ownership | RELEASES.md and AGENTS.md (#386), enforced by the freeze (#389); the merge-outside-scripts gap is Q-06 |
| R7 | The architecture checker checks shapes, not rules | wrong abstraction (step 7) | moved to step 7 (anti-mess structure), as planned |
| R8 | Main may stay red between merges; one env failure hides code failures in the same stage | missing gate, wrong abstraction | full-battery pass on the release head (#391); classifier says code beside env (#392); Chromium 45 → 0 (#392) |

The plan is [STEP-01-plan.md](STEP-01-plan.md).
