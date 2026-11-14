# CONTROL-ROUTE — status (blockers the diary could not take)

## B1 — no events token (broken environment), 02/11 11:39 BRT

The brief says this cloud environment has `$TOWER_EVENTS_TOKEN`. It does not: `env` lists no `TOWER_EVENTS_TOKEN`
(only `OU_CREDENTIALS`, `TOWER_NEON_*`). Every diary write fails:

```
$ scripts/plan note --pr 1083 --program engine --from CONTROL-ROUTE --affects all --kind engine --evidence d7f797f5 "started: branch mod/control-route, draft PR #1083 opened"
forge_control.ControlError: no events token: set $TOWER_EVENTS_TOKEN
```

Diary notes this unit would have written are kept below, in order, until the token exists.

- engine d7f797f5: started: branch mod/control-route, draft PR #1083 opened

## B2 — control plane unreachable from this session (proxy policy), 02/11 11:41 BRT

```
$ curl -sS https://forge-webhook.example.workers.dev/status
curl: (56) CONNECT tunnel failed, response 403
$ curl -sS "$HTTPS_PROXY/__agentproxy/status"   # recentRelayFailures
"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
"host": "forge-webhook.the-owner.workers.dev:443"
```

The environment's network policy does not allow `*.workers.dev`. The meter's control-queue read is therefore proven
with a fake of `GET /status` shaped like the live document (`services/control-plane/src/core.js` `status()`), and the
first real read happens on a machine that reaches the Worker.

- engine: decision: the meter's control-queue path is tested against a fake of the Worker's /status; the real read is the post-merge activation step

## B3 — the gate cannot record its verdict (same missing token), 02/11 11:58 BRT

```
$ scripts/gate-dev --pr 1083        # head e49f55bd
gate proof: v3 verdict (the run has no proof binding (no commit or no recorded base))
FAIL gate evidence: forge_events could not record the verdict: no events token: set $TOWER_EVENTS_TOKEN (class env)
GATE: FAILED
```

`.gate/records/reports/e49f55bd…/dev-20261102T145844/bypass.json`: `bypass=D-151`, all 8 stages marked PASS without
running (pr metadata, no GitHub Actions workflows, secret scan tree/history, structure check, generated drift, schema
compat, script tests). The bypass proves nothing about the battery; the hand-run suites and the real gate run with
`GATE_BYPASS=0` (PR body) are the evidence. `scripts/pr-ready` publishes through the same journal.

## B4 — pr.ready cannot be emitted (same missing token), 02/11 12:16 BRT

```
$ scripts/pr-ready --pr 1083 --body docs/units/CONTROL-ROUTE/plan.md      # head 0d8ef7a3
forge_control.ControlError: no events token: set $TOWER_EVENTS_TOKEN
$ gh pr ready 1083
HTTP 403: GitHub GraphQL is not available from Claude Code sessions; use the REST API ...
$ gh api -X POST repos/openuniversity-si/open-university/pulls/1083/ccr/ready_for_review
{"draft":false}
```

PR #1083 is out of draft (REST route), 0 behind the base, but no `pr.ready` reached the train: whoever has
`$TOWER_EVENTS_TOKEN` runs `scripts/gate-dev --pr 1083` then `scripts/pr-ready --pr 1083 --body docs/units/CONTROL-ROUTE/plan.md`
on the head. The pinned gate on 0d8ef7a3 gave the B3 failure again (bypass D-151, verdict not recorded).

- engine 0d8ef7a3: PR #1083 out of draft; pr.ready blocked by the missing events token (B4); not merged
- lesson docs/units/CONTROL-ROUTE/retro.md: RETRO committed

## environment — proved working, 02/11 (continuation CONTROL-ROUTE-2, head 82445d3c2)

The `the-tower` environment now carries `$TOWER_EVENTS_TOKEN` (present, 64 characters, value not printed) and the proxy
lets the control plane through. B1, B2 and the token half of B3/B4 are closed.

```
$ scripts/plan note --pr 1083 --program engine --from CONTROL-ROUTE --affects all --kind engine --evidence 82445d3c2 "environment ok: diary reachable"
6f0b0aa13a0cbd33d3a25438f1693f9ff5991b81abd79e80c7ba92b10052765e        # event id, exit 0
$ curl -sS -o /dev/null -w 'HTTP %{http_code}\n' https://forge-webhook.example.workers.dev/status
HTTP 200
```

The diary notes kept above (B1, B2, B4) were replayed on PR #1083's channel, each exit 0.

## gate and suites — continuation, 02/11

- `scripts/gate-dev --pr 1083` on 081e5ad6e, first run: bypass D-151 (8/8 stages marked PASS), then
  `FAIL gate evidence: forge_events could not record the verdict: control plane unreachable: The read operation timed out (class env)`
  (`service.control_timeout_s` = 10 s). Three `GET /status` right after answered 200 in 0.66–1.06 s. Rerun once:
  `gate evidence: gate.passed 65c9efde8d20 on PR #1083 (+8 engine.step.measured)`, `pr.ready: emitted #1083 head=081e5ad6`,
  `GATE: PASSED (bypass=D-151)` in 10.4 s. One timeout in two writes: still open, not this unit's code (the Worker's
  write latency, CONTROL-STORE's area).
- The 13 script tests session 1 saw red on base and head, rerun now that the token exists (7 at a time):
  `forge-rate` now passes. `forge-events` exposed a **defect of this branch**: `test_declared_demands_and_proofs_match_the_tree`
  still expected `service_runner.py` as a forge-operation consumer, which e49f55bdc removed from `operation_demands.json`
  (fails on this head, passes on `fab6e204d`). Fixed in b030a7cc1. Session 1's "passes alone on both" missed it.
- Known base defects, identical on `fab6e204d`, not fixed here: `forge-events.test.sh` still exits 1 on both because
  `test_operation_integration.py` does `from scripts.tests.test_forge_events import …` (`ModuleNotFoundError: No module named 'scripts'`
  under `parallel_tests.py`); `commit-check`, `defect-lifecycle`, `gate-forge-budget`, `gate-isolation`, `gate-local`,
  `gate-pin`, `lessons`, `plan-tick`, `planner-role` (600 s timeout, `ForgeCompatibilityError`), `pr-creation-path`,
  `train-role`. `shellcheck` is still not on PATH (gate stage `shellcheck` class env).
