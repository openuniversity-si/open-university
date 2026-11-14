# NANO-UNBLOCK plan (base fbc09f28, PR #735, deadline 04:36Z)

Goal: after this merges, a PR whose own changes are clean passes the pinned gate in a fresh cloud session. Fix at the
cause what is cheap and safe (items 1-2 of the audit); route the rest through the gate's existing known-defect / env
route, visible in the report, listed in `backlog.md`. Engine-lane files only (`#730` holds the one site-lane fix).

## Commits (D-022 plan; `Plan: N` trailers tick the PR body)

| N | Commit(s) | Files it owns | Depends on | Runs |
|---|---|---|---|---|
| 1 | audit.md: inventory ranked by PRs blocked | `docs/units/NANO-UNBLOCK/audit.md` | - | a89b39ff; ranking rows when the inventory returned |
| 2 | plan.md | `docs/units/NANO-UNBLOCK/plan.md` | 1 (items 1-2) | 79f43a34 |
| 3 | Cloud env: one classified `FAIL env:` line when a registry read fails, never an unbound variable | `scripts/cloud/env.sh`, `scripts/cloud/setup.sh`, `scripts/tests/test_cloud.py` | 2 | parallel with 4 |
| 4 | Config store and GitHub limit wait, two commits: (a) `forge_rate.wait_hint` takes `x-ratelimit-reset` only when `x-ratelimit-remaining` is 0 (GitHub's documented rule), else the registry minimum plus jitter; (b) bootstrap owners never read the shared store, a failed remote read serves the last good read within `config.store_stale_max_s`, the CLI prints one line | (a) `scripts/lib/forge_rate.py`, `scripts/tests/test_forge_rate.py`, `scripts/tests/fixtures/forge-rate.json`; (b) `scripts/lib/config.py`, `config/registry/config.json`, its generated file, `scripts/tests/test_config_api.py` | 2 | (a) f6f78f0f; (b) parallel with 3 |
| 5 | The rest of the class: the gate-graph order race fixed at its cause (engine-lane test); every deferred item through the existing route and listed in `backlog.md` | `scripts/tests/test_gate_graph.py`, `docs/units/NANO-UNBLOCK/backlog.md`, the audit rows | 1 (inventory), KD route audit | after 3-4 |
| 6 | Retro | `docs/units/NANO-UNBLOCK/retro.md` | gate | last |

Edges: 3, 4a and 4b share no file (collision-free by design: 3 adds no registry key, 4a reuses
`github-client.secondary_wait_min_s`, only 4b touches the registry and its generated files). 3 does not need 4: its test
drives env.sh/setup.sh with a stub config.py that fails, so it proves the guard whatever the store does. 5 needs the
inventory and the KD route audit (real edges). Critical path: 2 (3 min) -> 4 (25 min) -> pinned gate (6 min) -> evidence dry run (2-3 local
merges, ~15 min, parallel slots) -> 7 (5 min) -> MERGE-READY: about 55 min from plan.md.

## Premises and blast radius
- P-46 (the PR body's premise).
- N1: the shared store overrides no `cloud.*` / `toolchain.*` key, so reading them from the registry changes no value
  (verified 02:20Z: overrides are `coordinator.max_sessions`, `train.enabled`). Radius: setup/env of every session.
  Not critical: verified, and `set_value` refuses a bootstrap key afterwards so none can appear unread.
- N2: GitHub's secondary-limit rule (Retry-After, else reset only at remaining 0, else at least one minute) is the
  documented one. Radius: every engine GitHub call's wait. Not critical: the waits get shorter and stay bounded by
  `github-client.limit_retries` and `max_wait_s`, both unchanged.
- N3: a stale read of at most `config.store_stale_max_s` is acceptable for runtime flags while GitHub refuses reads.
  Radius: flags read through the shared store (2 today). CRITICAL-adjacent (a kill switch flipped during an outage is
  seen late): the bound is one hourly limit window, the serve is printed on stderr, and a flag change through the
  checkout itself still drops the cache. Safest reversible option taken; recorded in the PR.
- N4: no threshold changes: `github-client.max_wait_s` (120), `limit_retries`, `secondary_wait_min_s`, the cache TTL,
  every test timeout stay as they are.

## Tests
- 3: `scripts/run test cloud` (new: a stub config.py that fails makes env.sh print one `FAIL env:` line and return 1;
  setup.sh exits 2 with one `FAIL env:` line; both show `unbound variable` on fbc09f28).
- 4b: `scripts/run test config` and the config API suite (new, fake clock: a bootstrap key costs no read of a failing
  forge; a failed read serves the last good read within the bound and raises past it; the CLI prints one line).
- 4a: `scripts/run test forge-rate` (new: a secondary refusal with a far `x-ratelimit-reset` and remaining > 0 waits the
  registry minimum, not the reset).
- 5: `scripts/tests/gate-graph.test.sh` (16 parallel runs green), `scripts/run test defects` / `gate-classify` if the route changes.
- One pinned gate at the end: `gate-dev --pr 735`; then the evidence dry run without `--pr` on local merges.

## Known base defects expected (not ours; owners)
Known env failures (claude-session, root-identity under sudo, config with no token, uid-65534 fs-encoding, script-test
TMPDIR), KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3, load flakes (gate-graph, catalog-cli
sync.test.ts, identity handler.test.ts): rows 4-6 of the audit decide each.
