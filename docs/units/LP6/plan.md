# LP6 plan: planner role session and wake path (mirrored in the PR description)

Unit LP6 of the live-planning program (D-071, plan.md §2 row LP6). Branch `mod/lp6` → `mod/roadmap-integration`.
Effort ≈ opus · 1.5 h (deadline 2× = 3 h after launch).

## Commit plan

1. Audit (`docs/units/LP6/audit.md`).
2. Plan (this file).
3. Role lease and sole-writer append: `scripts/lib/planner_role.py` (`PlannerRole(engine_role.LockedRole)`, append
   through `plan_live`'s signatures, fetch/merge/retry, module main `append`), `config/registry/planner-lp6.json` (lock,
   lease, producer, retries, remote) + generated module + one manifest line, `scripts/tests/test_planner_role.py`
   (two concurrent writers against a temp bare repo).
4. Wake path: `scripts/lib/adapters/planner_wake.py` (port, dry-run adapter), `planner_wake_claude.py`, wake keys in
   `planner-lp6.json`, `planner_role.py` `wake` (candidates from `plan.candidate.v1`, context budget), tests.
5. Ownership fix (added after commit 4): `scripts/lib/adapters/**` belongs to `engine-vendors`, so LP2's
   `scripts/lib/adapters/planner_wake*.py` claim in `engine-coordinator` made the two wake files owned twice
   (D-067 (6)); drop that claim so they belong to `engine-vendors` like every other adapter (+ CODEOWNERS).
6. Runbook `docs/process/live-planning.md` §5 "Role" only.
7. RETRO (`docs/units/LP6/retro.md`).
8. Real `plan_live` (LP3 merged after commit 7): its `append` folds against the program docs and contracts of the same
   checkout, so the log branch starts from `planner-lp6.log_branch_base` instead of an orphan, the clone borrows the
   checkout's objects, and an integration test appends through the real module.

## Dependency graph and critical path

`1 → 2 → 3 → 4 → 5 → 6 → 7 → 8`. 3 and 4 share `planner_role.py`, `planner-lp6.json` and the test file (collision edge kept:
sequential, ≈ 25 + 20 min); 5 depends on 3-4 for the names it documents (real). The steps are small and share one
vocabulary, so this session executes them directly; sub-agents would re-derive the same context (same call as CO1).
Critical path ≈ 5 + 5 + 25 + 20 + 10 + 10 min + one gate (≈ 6-10 min) ≈ 85 min.

| Commit | Files owned |
|---|---|
| 3 | `scripts/lib/planner_role.py`, `config/registry/planner-lp6.json`, `scripts/lib/generated/config_registry_planner_lp6.py`, `units/engine-coordinator/unit.json` (one line), `scripts/tests/test_planner_role.py` |
| 4 | `scripts/lib/adapters/planner_wake.py`, `scripts/lib/adapters/planner_wake_claude.py`, + the files of 3 |
| 5 | `units/engine-coordinator/unit.json` (one line removed), `CODEOWNERS` (generated) |
| 6 | `docs/process/live-planning.md` §5 |
| 7 | `docs/units/LP6/retro.md` |
| 8 | `scripts/lib/planner_role.py`, `config/registry/planner-lp6.json` + generated, the test file, runbook §5, plan, retro |

## Design

- **Lease**: `PlannerRole` is an `engine_role.LockedRole` (existing API, read-only use): `run(owner, correlation_id)`
  takes `planner-lp6.lock_ref` for `planner-lp6.lock_lease_s` through the `forge_events` port, `drain` appends each
  pending change and `renew`s before each one, so a writer that lost the lease halts (`RoleHalt`) before it writes.
  Another holder → `busy`, nothing written.
- **Sole-writer append**: in a working clone of `planner.log_branch`: fetch, start from the remote tip, read the head
  (`plan_live.read_log`), set `version`/`parent`, `digest` (`plan_live.digest`), `plan_live.append`, commit, push. On a
  non-fast-forward: fetch + merge (merge commit; never force, never rebase); re-check `parent` against the merged log:
  still the head (the race touched another program or file) → push the merge; stale (another writer appended to the
  same program) → abort the merge, drop the unpublished attempt and rebuild on the new head. At most
  `planner-lp6.append_retries` retries.
- **Wake port**: `wake(message)`; message = the candidates (`plan.candidate.v1`, `disposition == candidate`, validated)
  and the input refs, cut to `planner.decision_context_max_tokens`. Adapters: `dry-run` (writes the message under
  `planner-lp6.wake_dry_run_dir`), `claude` (registry argv + the planner session id from the env var the launcher
  provides; runner injected; no secret).
- **Switch**: `planner.enabled` stays false; with it false the real `append`/`wake` print that and do nothing;
  `wake --dry-run` always works.

## Premises

Premises: P-48 (plan log on `plan/live`, one writer), P-50 (the planner session can be woken by events). CRITICAL: none
(no money, production or source of truth: the log stays git on GitHub; the switch stays off).

## Tests

Targeted: `python3 -m unittest scripts/tests/test_planner_role.py`, `scripts/config check`, `scripts/generate --check`,
`scripts/structure-check`, `scripts/program check live-planning`. One final `scripts/gate-dev --pr <n>` from a clean
base-tip checkout.

## Known base defects

claude-session, root-identity, config `RegistryMemo` / flaky `config.test.sh`, cloud uid-65534 fs-encoding (env).
