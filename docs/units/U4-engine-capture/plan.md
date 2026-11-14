# U4 engine-capture: plan

Premises: P-03 (high: units stay logical for `scripts/`; if wrong the files must move later, importers use paths), P-04, P-05 (literals migrate with the unit), P-07 (contract expand->contract). No CRITICAL premise (no money, production or source-of-truth change).

## Commits (serial: they share `unit.json` and the registry)
1. Audit and plan (this file).
2. `config/registry/capture.json`, `scripts/lib/capture-config.mjs` (lazy per-setting read through `config.py get`), the 8 capture scripts read every tunable from it.
3. Manifest paths and `battery.command`, `scripts/tests/engine-capture.test.sh`, contract doc, generated outputs.
4. Retro after the gate.

**Plan change (after step 2):** the manifest `contract` field is not written. The unit battery resolves the contract entry under the unit's `@ou` address home, and no `scripts/` unit has one, so a `contract` would turn the battery red. The contract and its version live in `contract.md` until the unit has a home.

## Tests
Per commit: `node --test` on the three existing capture tests + the new one; `scripts/units check`; `scripts/unit-battery engine-capture`. One final `gate-dev`.

## Known base defects
Timing-sensitive catalog tests (cover concurrency, read latency): not touched.
