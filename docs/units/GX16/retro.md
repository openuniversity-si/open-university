# GX-16 retro

## Result
Pinned `gate-dev --pr 731` on head 2bd8b8a4: PASSED, 66.9 s (script tests 38.6 s, structure 11.7 s), advisory report-only run PASSED, no known defects hit. Targeted: `test_gate_status.py` 28 OK, `test_github_cli.py` 15 OK, `gate-pin.test.sh` 20/20, `test_gate_forge_budget.py` and `test_gate_gc.py` OK (all with `OU_CONFIG_STORE=file`, see env notes).

## Observable (honest numbers)
- Real gate, base tooling (the pinned run applies the base's gate_status, i.e. the before behaviour): `forge: 6 writes, 21 reads` on a 67 s gate. The 4-7 min gate of the brief was not reproducible here (the gate takes ~1 min in this cloud box), so the "25 calls on 4-7 min" comparison is not re-measured; the new code removes writes by construction: no edit at stage start, no second `begin` edit or `pending` status, edits at stage end at most once per 60 s (was 15 s), one comment for all heads of a PR instead of one per head and mode.
- The counter now records `W|R METHOD endpoint` per request in the count file (`github_api.by_endpoint`); it is available to GX-10 as `github-client.count_file_env`.

## Brief
- Much of the goal was already on the base (#718/#720: sticky upsert, no PATCH->POST duplicate, secondary-limit wait); audit.md listed it, so `secondary_limit_retries/backoff_s` were not added as duplicate keys (`limit_retries`, `secondary_wait_min_s` exist). The brief's key names were stale: a brief should be checked against the registry before it names keys.
- The brief did not say gate_pin.py posts an "advisory" comment through `gate_status.marker_line`; one-comment-per-PR would have overwritten the status comment. Caught by `gate-pin.test.sh` in the gate, fixed (advisory keeps its own marker).

## Execution
Failures, by class: (1) unregistered numeric literals in code and tests (structure check, LT1) and a module call outside its adapter (github_cli from gate_status): fixed together in one commit (sha width is `gate.status_sha_chars`, named regex groups, test numbers derived, redaction moved into the forge adapter). (2) A semantic collision with gate_pin (above). (3) PR body had no D-022 checklist: fixed in the body.
Env: first gate attempts aborted on missing toolchain (ran `scripts/cloud/setup.sh`) and on the shared config store being unreadable without a token / 429 block (`OU_CONFIG_STORE=file`; also made `setup.sh` report "missing host tool: python3" falsely). Not changed here.
Gate runs: 3 pinned runs: (1) structure literals, (2) literal baseline + D-022 plan + gate-pin, (3) PASSED.

## Lessons
- Run `scripts/structure-check` and the tests of every caller of a changed seam (`rg marker_line`) before the first gate: would have saved two gate runs (owner: unit author; a pre-gate `scripts/run test` of covers of touched modules is a gate-excellence candidate).
- `setup.sh` should say the config store is unreadable instead of "missing host tool: python3" (owner: GX-ENV).
