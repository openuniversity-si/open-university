# CONTROL-STORE status

## environment
- 02/11 (continuation): `scripts/plan note --pr 1084 --program engine --from CONTROL-STORE --affects all --kind engine --evidence 86c993b1d "environment ok: diary reachable"` succeeded (rc 0, event id returned).
- `GET https://forge-webhook.example.workers.dev/` answers HTTP 200 with no credential printed.
- Control-plane tests from `services/control-plane`: `node --test test/core.test.mjs test/events.test.mjs test/origin.test.mjs` -> tests 43, pass 43, fail 0.

## resolved
- RESOLVED 02/11: the first session's GitHub 429 (`write budget asks to wait 837 s, more than github-client.max_wait_s (120 s)`) no longer applies. The diary write succeeded in the continuation session, so the budget has reset; do not re-diagnose it.
- The earlier blocker (gate-dev, diary notes, `gh pr ready`, `pr-ready` pending the 429) is superseded: those steps run in the continuation.
