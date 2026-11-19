# ADR-28 — Full local gate within 90 seconds

Status: superseded by D-314 (the gate runs on GitHub Actions and judges the tests a diff touches; the 90 s budget became D-064 (f)'s 180 s warning).

Status: accepted, 2026-10-18. Extends ADR-24. Scope: build/test infrastructure only.

## Problem

Three full clean-source runs on post-E0 main `ebc207b` took 212.963, 189.635 and 200.483 seconds on the 8-core / 15 GB box.
Integration took 108/103/114 seconds; lint 37/31/29 seconds. Unit already took 8/7/6 seconds. Every run executed
1,071 unit tests in 111 files, its 45-test coverage pass in 5 files, 464 integrations in 22 files, and the same three shell
suites (13 merge checks, 16 media host checks, and the retry assertions). Serial orchestration and repeated fixture relation
rewrites dominated. A subsequent run also falsely detected Next-generated preview keys as source secrets.

## Decision

Keep every check and full-suite exact-head merge authorization. Parallelize independent stages after frozen install, collect
all background exits and group logs. Keep database verification dependencies ordered. Run the existing builds concurrently
in their separate dist directories; build and test results are never skipped or trusted from a previous head.

Limit unit to two workers to avoid starving the longer integration/build stages. Prepare independent fixture texts and covers
concurrently through the existing real pool and repository. Use four integration workers, one migrated PostgreSQL template per run and a fresh database per file. Validate the local
container target first, propagate it to CLI subprocesses, and tear down all names under the run's random prefix. Retain the
global gate lock because schema/parity and nightly E2E still use the launcher database. Test assertions retain their scope;
advisory-lock leak checks inspect the current database rather than unrelated workers' locks.

Reset small fixtures with ordered deletes in a transaction and reset sequence values to their versioned starts. Truncate
only the immutable release table and its referencing audit table. Keep triggers, constraints, SQL isolation and durability
settings enabled. Add regression coverage for fixture state, the template boundary and orchestration failures.

Scan full history and every tracked/unignored source file (including local modifications and new source); exclude generated
ignored build output by constructing the source scan tree from Git's file list. Preserve relative source paths for approved
allowlists. Test that dirty and untracked source secrets are still rejected and logs stay redacted.

Print per-stage elapsed time and complete wall time including checkout and cleanup. Warn prominently above 90 seconds;
correctness always remains blocking. Heavy opt-in nightly operations retain their scope and are outside this budget.
Do not introduce GitHub Actions, paid services, app rendering changes, production data changes or changed-files merge gates.

## Validation and consequences

Require three consecutive complete runs at the final PR head within 90 seconds, compare test/file counts to the baseline,
then run `gate-local --pr` and merge only with `merge-phase`. Existing test assertions and coverage thresholds remain;
additional infrastructure tests increase counts. Operational details: local gate.

Concurrency increases peak resource use while reducing elapsed time. Template creation needs CREATEDB on the existing
local test role. A correctness failure in any concurrent stage blocks the pass even when other stages succeed. The timing
warning exposes regressions and contention without weakening correctness checks. No application rollback or migration is
required for this infrastructure change; a normal Vercel rollback remains available for the merge deployment.

Tolerance updated to 90 s by Daniel on 2026-10-18 at 01:28 BRT; the separate E3/E4 course-delivery goal remains 60 s. All checks are preserved.

Note (GX-26, 2026-10-28): the single budget is the `gate.ceiling_s` 180 s ceiling (D-064 (f)), a warning only, never a failure. It supersedes the 90 s figure above; the text above is kept as history.
