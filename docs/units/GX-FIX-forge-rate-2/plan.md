# GX-FIX-forge-rate-2 — plan

Critical path, about 60 min: 1 audit → 3 forge_events route-aware publish/read → 5 gate_pin base tip → 6 new test → final gate → 8 retro.
The commits own disjoint files, so no edge between them is a file collision. Only the new test (6) has a real edge: it needs 3, 4 and 5.

| # | Commit | Files owned | Depends on | Targeted tests |
|---|---|---|---|---|
| 1 | audit.md, status.md | docs/units/GX-FIX-forge-rate-2/{audit,status}.md | none | none |
| 2 | plan.md, traceability.md | docs/units/GX-FIX-forge-rate-2/{plan,traceability}.md | 1 | none |
| 3 | A kind that lives in the file log is read and deduplicated from the file log alone (publish window + read); the script-tests stage makes 0 GitHub calls | scripts/lib/forge_events.py, scripts/lib/gate_test_cache.py | 1 | forge-events, gate-test-cache, forge-rate |
| 4 | Bounded limit retries (`github-client.limit_retries`); a per-run request counter (`github-client.count_file_env`) | scripts/lib/github_api.py, config/registry/github-client.json, generated module | 1 | forge-rate |
| 5 | Root cause: the pin takes the fetched tip of the PR's base REF, never GitHub's lagging `base.sha`; the advisory run needs a head that contains the base | scripts/lib/gate_pin.py, scripts/tests/test_gate_pin.py | 1 | gate-pin |
| 6 | New test `gate-forge-budget`: 80 script tests make 0 forge calls in the stage, bounded writes per run, a limit wait under a fake clock, the stale base.sha regression; rest_fake gets a read limit and read/write counters | scripts/tests/{gate-forge-budget.test.sh,test_gate_forge_budget.py,covers/gate-forge-budget.json,fixtures/gate-forge-budget.json,rest_fake.py} | 3, 4, 5 | the new test, rest-fake-ready |
| 7 | Forge counter printed at the end of the gate and in the final panel; docs | scripts/gate-local (env line), scripts/lib/gate_report.py, docs | 4 | gate-status |
| 8 | retro.md | docs/units/GX-FIX-forge-rate-2/retro.md | final gate | none |

Commits 3, 4 and 5 can run in parallel: they share no files.

## Premises
- P-42 (the D-065 events premise of the gate) is unchanged.
- The pinned base is the base branch tip, fetched from origin. Radius: every pinned gate. If a fetch fails, the run gets a classified `gate pin` abort and never a stale ref. CRITICAL: no. It touches no money, production or source of truth, and it is reversed by reverting the commit.
- GitHub's `base.sha` lags the base tip. Proven in audit.md, from live GETs on #705 and #714.

## Known base defects (not mine)
claude-session.test.sh, root-identity.test.sh, config.test.sh (RegistryMemo), the uid-65534 fs-encoding crash, and the hermetic/gate-db/TimeoutTest failures that GX-29 (#716) is fixing.

## Final gate
Run once at the end: `scripts/gate-dev --pr <N>` (pinned to the base tip, plus an advisory run of the head tooling).
