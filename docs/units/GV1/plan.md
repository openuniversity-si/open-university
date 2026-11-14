# GV1 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/GV1/audit.md`).
2. Plan (this file).
3. Status renderer: `scripts/lib/gate_status.py` pure rendering (start table with ETA, live rows, final table, collapsed events) + registry keys + unit tests.
4. Publisher: find-by-marker comment, edit in place, bounded update rate, state file under the logs; CLI `start|stage|final`; tests with a fake REST client.
5. Call sites: `step()` start/end, `gate-local` start after the plan, `gate_report.py` final with the verdict; never fails the gate; shell test.
6. Contract (additive) + docs (`docs/operations/local-gate.md`, EVENTS.md note) + generated outputs.

## Dependency graph and owned files
`1 → 2 → 3 → 4 → 5 → 6`. 3 and 4 share `gate_status.py`, so they run in sequence; 6 (docs/contract) touches no code file.
Execution is done by the coordinator directly: the steps are small and sequential on one module, so sub-agents would cost more than they save.

| Commit | Files owned |
|---|---|
| 3 | `scripts/lib/gate_status.py`, `config/registry/gate.json`, `scripts/tests/test_gate_status.py` |
| 4 | `scripts/lib/gate_status.py`, `scripts/tests/test_gate_status.py` |
| 5 | `scripts/lib/gate-runner.sh`, `scripts/gate-local`, `scripts/lib/gate_report.py`, `scripts/tests/gate-status.test.sh`, `scripts/lib/gate-script-tests.json` |
| 6 | `contracts/**`, `docs/**`, generated outputs |

## Premises
Premises: none registered. Working premises:
- **CRITICAL**: none (no production, money or source of truth; a failed comment write never changes the verdict).
- (high) A status write failure must never fail or slow the gate: all calls are `|| true`, bounded by a REST timeout.
- (medium) Local report history is enough for ETAs; with none, the row shows "no history".
- (low) Parallel stages update one state file: serialized with flock.

## Targeted tests, then one final gate
3/4: `test_gate_status.py`, `config.test.sh`. 5: `gate-status.test.sh`, `gate-local.test.sh`, `gate-failures.test.sh`. 6: `scripts/generate --check`, `schema-compat`. Then one `gate-dev`.

## Known base defects expected
`scripts/tests/generate.test.sh` (`intents-doc.ts`), `scripts/tests/premises.test.sh` (`measurement:S1`).
