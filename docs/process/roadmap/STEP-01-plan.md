# Step 1 plan: stabilize

Target: the integration branch is the only place work lands, production changes have one owner and one path, and each
root cause in [STEP-01-audit.md](STEP-01-audit.md) has a check that stops it from happening again. No visual or
behavior change to the site.

Every PR branches from `origin/mod/roadmap-integration`, targets it, has 3–8 commits, and ends with the B5 trailers
and `Fit-Review: pending independent review`. `gate-db` needs Neon credentials this session does not have. Database
changes are proven on the local PostgreSQL 18 integration tests instead, and each PR says so.

## PRs

| PR | What | Root causes | Enforcement it adds |
|---|---|---|---|
| 1.1 | This audit and plan, `STATUS.md`, D-054 in the register, the asset entry for `docs/process/roadmap/` | all (record) | `structure-check` covers the new docs (asset inventory, decision proof column) |
| 1.2 | Rules: [production changes](#production-changes) in `docs/process/RELEASES.md` and AGENTS.md; independent fit review in STRUCTURE.md B5; fix CAP-005 `requested` and make D-051's date say which event it is | R2, R4, R5, R6 | written owner and path (ownership doc) |
| 1.3 | `docs/process/host-swap-queue.md`: every production migration and data rewrite waiting for the host swap, in order, with its check | R3 | one queue file; a migration not in production is listed there |
| 1.4 | `structure-check`: a `Fit-Review: approved` line names an independent reviewer session and the head it reviewed; `ship-verify` refuses when that head is not the PR head or no matching review comment exists. A capability whose `status: approved` date is before `requested` fails. A capability header gets a `conditions:` field (STRUCTURE.md A5): each precondition of its approval, such as M11's "a migration needs Daniel's approval before production", is `open` or `met YYYY-MM-DD <evidence>`. `structure-check` refuses a capability marked `done` with an open condition, and `fit_review` refuses a PR body naming a capability whose `before-merge` condition is open. CAP-005 records M11's two conditions | R2, R4 | checker rules + script tests |
| 1.4b | D-055 (no review step): `not reviewed (<who> <date>: <reason>)` is a valid trailer; a claimed `approved` still needs the reviewer's comment for the head; B5, AGENTS.md, RELEASES.md | R4 | checker rules + script tests |
| 1.5a | Production freeze and release unit: `scripts/release-policy.json` (frozen until the host swap) and `scripts/lib/release_policy.py`; `neon-migrate` before an apply, every Neon write, the REST merge and `merge-phase` into `main`, the HTTP and CLI promote and `preview-deploy` refuse on the real host while frozen; a merge into `main` is refused unless its head is the integration branch | R3, R5, R6 | guard + script tests |
| 1.5b | A release merge needs that exact head to have a full-battery pass record (the `gate-noite` stages, every browser project, no stage failed); a new migration must be numbered after the target branch's last one | R1, R8 | gate checks + script tests |
| 1.6 | #273 (D-036): fit check against the current code. **Verdict (#393): not fit** (16 conflicts; the code it rewrites was restructured since; literals; 2× size; author-written fit review). D-036 is registered and its parts are carried below; #273 is not retargeted or merged | R1 | the migration-order check (1.5b) refuses #273's numbering |
| 1.7 | Main's red Chromium e2e: find the commit that broke each of the 45 tests and fix them. The classifier reports a stage's code failures even when the same stage also has an env failure (a stage with both is `code`, and the env lines are listed beside it) | R8 | classifier test in `scripts/tests/`; with 1.5's green-head check, a red integration branch cannot be released |

1.4, 1.5a, 1.5b and 1.7 change gate files, so their bodies cite D-054 (D-025).

Order: 1.1 → 1.2 → 1.3 → 1.4 → 1.5a → 1.5b → 1.6 → 1.7. 1.7 can move earlier if the red suite blocks a gate. 1.6 comes after 1.5b because 1.5b adds the migration-order check that it must
pass, and 1.3's queue receives its migrations.

## Carried from #273 (D-036)

Each part is written again on the code of the step that owns it, as small PRs, with D-036's proof linked. A carried
migration gets its number when it is written, after the integration branch's last one (`structure-check`, 1.5b).

| Part of D-036 | Roadmap step | Why there |
|---|---|---|
| An edition's language is backfilled from its course, then required (data rewrite + constraint; queue Q-02) | 2, single database package | a migration and a data rewrite of the one database package |
| `writeBundles` in batch apply; delete `POST /bundles/ship`, `ship-batch.ts`, the cover-kind alias, disallowed taxonomy entries | 3, use cases | one ship use case, one path |
| Batch apply phase timings, set-based writes, compile only changed courses, a 60 s representative-apply test; statement-level cover check (queue Q-03) | 3, use cases | the apply use case and its budget |
| A dry run stores chunks bound to the batch hash and its options, with a TTL (queue Q-04) | 3, use cases | the ship use case's staging |
| `structure-check` refuses an unreferenced route and a re-export alias; every script declares its side effects | 7, anti-mess structure | checker rules |
| `gate-db` waits until the Neon branch is ready and records each step's time | 8, host portability | the release host's database gate |
| A production build and `/api/health` refuse when the production ledger is behind the commit | 8, host portability | the release pipeline's guard |

## Enforcement per root cause

| Root cause | Check that stops it recurring | PR |
|---|---|---|
| R1 migration order not checked; D-020 unenforced | a new migration must be numbered after the target branch's last one; `main` merges only from the integration branch | 1.5b |
| R2a capability approved before requested | `structure-check` refuses `status: approved` dated before `requested` | 1.4 |
| R2b approval conditions have no checked home | capability `conditions:` field; `structure-check` refuses `done` with an open condition; `fit_review` refuses a PR naming a capability with an open `before-merge` condition | 1.4 |
| R3 production migration has no approval gate or freeze | `neon-migrate prod` refuses while `scripts/release-policy.json` is frozen | 1.5a |
| R4 fit review trusts author text | the trailer names a reviewer session and head; `ship-verify` checks the head and the review comment | 1.4; 1.4b: no review step (D-055), so `approved` needs its review comment and the author writes `not reviewed (...)` |
| R5 PR merge is a release | `merge-phase` into `main` refuses a head that is not the integration branch | 1.5a |
| R6 no owner of production changes | `docs/process/RELEASES.md` and AGENTS.md (ownership doc), backed by the 1.5a freeze | 1.2, 1.5a |
| R7 checker checks shapes, not rules | moved to step 7 (anti-mess structure), where the checker is rebuilt | step 7 |
| R8 main may stay red; env hides code | a release merge needs a full-battery pass on that exact head; a stage with a code failure is classified `code` | 1.5b, 1.7 |

## Production changes

The rule 1.2 writes, in short:

- No agent session deploys, promotes, rolls back, or runs a production migration or data rewrite by hand. That
  includes `ship-tail`, `ship-verify`, `merge-phase`, `neon-migrate prod`, `neon-pr`, `preview-deploy`, `vercel` and
  `production-check` rollback.
- Production is frozen until the host swap at the end of the roadmap (step 8). Pending production changes wait in
  `docs/process/host-swap-queue.md`.
- Work merges into `mod/roadmap-integration`. A release is one merge of that branch into `main`, so one production
  deploy per release and not one per PR.
- Fit review comes from a reviewer session that did not write the PR. The review is a PR comment bound to the head SHA,
  and the trailer names that head.

## Out of scope for step 1

- The architecture checker rework (R7): step 7.
- The full reviewer identity check (a reviewer key or account separate from the executor's): step 7. Step 1 binds the
  review to a comment and a head.
- The sanctioned release pipeline itself: step 8. Step 1 only freezes the old path.

## Metrics

| Measure | Before | Target after step 1 | After step 1 (2026-10-25) |
|---|---|---|---|
| Open PRs that cannot merge into their base | 1 (#273) | 0 | **1, target not met.** #273 has a fit verdict (not fit, #393), and D-036's parts are re-planned into steps 2, 3, 7 and 8. Closing it is the structure owner's call. |
| Merged PRs with an author-written fit review and no review record | 72 (since 2026-10-23) | 0 new; the gate refuses one | 0 new. `structure-check --review` and `ship-verify` refuse an `approved` trailer without its review comment (#388, #390). Under D-055 the trailer says `not reviewed`. |
| Production migrations applied without a recorded approval | 1 (0033) | 0 new; recorded in the queue | 0 new. 0033 is Q-01, and `neon-migrate` refuses an apply while frozen (#389). |
| Ways an agent session can change production | 7 commands | 0 while frozen | 0 through the scripts (6 write paths refuse, #389). A merge made outside them is queued as Q-06, a GitHub ruleset for the owner. |
| Main merges per PR | 1 | 1 per release | 0 main merges since the roadmap began. `main` accepts only the integration branch, with a full-battery pass on its head (#389, #391). |
| Chromium e2e failures on the integration branch | 45 | 0 | 0 (#392): desktop 244 passed, mobile 230 passed. WebKit is env: it needs root on this host, and local-gate.md has the procedure. |
