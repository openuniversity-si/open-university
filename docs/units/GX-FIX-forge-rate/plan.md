# GX-FIX-forge-rate — plan

Launch 18:33 BRT 27/10, deadline MERGE-READY ≤ 90 min. Decision D-070, Premises P-42. Never merged by this session.

## Commits (graph)
1. audit.md (done) → 2. plan.md (this) → 3, 4, 5 → 6 → 7.
- **3. Rate-aware client.** `scripts/lib/forge_rate.py` (new, units/engine-github), `github_api.py` (request path),
  `config/registry/github-client.json` (+9 keys, generated module), `scripts/tests/rest_fake.py` (secondary limit,
  content-write counter, comment ids, PATCH comments: new functions + 2 lines in `_dispatch`), `test_forge_rate.py` +
  `forge-rate.test.sh` + covers. Tests: `forge-rate`, `rest-fake-ready`, `config`, `forge-events`.
- **4. Batch + route the events.** `forge_events.py` (a `batched()` port scope; a `RoutingAdapter` chosen by
  `adapter_from_config`), `config/registry/forge-events.json` (`forge-events.kind_routes`), `gate_test_cache.py`
  (`record_durations` = one publish), the other per-item loops in scripts/lib (quarantine, slo, stall_report,
  defect_router, defects, coordinator) wrapped in `port.batched()`. train.py untouched (GX-30 follow-up). Tests:
  `forge-events`, `gate-test-cache`.
- **5. Sticky gate-status.** `forge_github.upsert_comment` (no POST after a failed PATCH unless the comment is gone (404);
  a session-cache map (repo, PR, first line) → comment id under a lock so concurrent runs find one comment);
  `gate_status.push` non-forced live edits are best effort (`max_wait_s` 0). Tests: `forge-rate`, `forge-events`.
- **6. Guard test.** `test_forge_rate.py` class: AST/grep scan of scripts/lib and scripts/* for a GitHub write outside
  `github_api._request` (urllib/requests/http.client to GitHub, `gh api -X`, `gh pr create|comment|merge`, `curl -X`);
  allowlist `scripts/tests/forge-write-allowlist.json` (owned by this unit, empty). A planted bypass fails it.
- **7. Docs + retro.** `docs/operations/forge-events.md` (write budget, where measurement events live, sticky comments,
  STATUS edit-in-place), retro.md.

Commits 3/4/5 touch disjoint files except `test_forge_rate.py` (3 creates it, 5/6 add classes): run in order 3 → 4 → 5
→ 6; critical path ≈ 3 (15 min) + 4 (15) + 5 (10) + 6 (8) + 7 (5) + gate (~10) ≈ 65 min. Sub-agents: none for code (one
writer, the shared files are small and serial); the audit inventory used one read-only sub-agent.

## Routing of measurement events (why the file adapter)
`engine.step.measured` is the only per-test/per-step kind; it goes to the existing `FileAdapter` (`.gate/events`,
JSON Lines per channel, flock-locked) by `forge-events.kind_routes`; every other kind stays on the configured adapter.
- The proxy refuses REST git-data writes, so a log ref would need `git push` of a commit built locally per append: a
  new mechanism, a race between sessions on the ref, and a fetch on every read. Too big for a class-fix unit.
- The readers keep working: `RoutingAdapter.read` returns the main log plus the routed kinds' local log for the same
  channel, so `gate_test_cache.last_durations` (latest per test), `slo.step_stats` (orders by time) and lessons see
  them. On a fresh checkout the local log is empty and ordering falls back to declared order, the same graceful
  degradation `measured_durations` has today when the read fails.
- Lost: cross-session duration history (an optimisation only). Follow-up if wanted: a per-session summary event.

## Premises
- P-42 (cited by the brief). Local: the secondary limit counts every POST/PATCH/PUT/DELETE (conservative: the budget
  counts all four); radius low (a too-strict budget only delays writes, the cap turns long waits into clear errors).
- CRITICAL? none: no production, no money, no source-of-truth change.

## Tests and gate
Targeted per commit (above). One `scripts/gate-dev --pr <N>` at the end (pinned base verdict + advisory head run).
Known base defects (GX-ENV): claude-session.test.sh, root-identity.test.sh, config.test.sh RegistryMemo flake, uid-65534 crash.

## Follow-ups (not here)
Per-role GitHub identities (torre-gate App for train and gate writes); train.py per-PR emit loop (GX-30); lock writes
(GX-FIX-train-lock).
