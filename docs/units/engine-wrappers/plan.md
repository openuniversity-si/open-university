## Plan

Commits (sequential; each owns disjoint files):
1. `docs/units/engine-wrappers/audit.md` — audit findings.
2. `docs/units/engine-wrappers/plan.md` — this plan.
3. `scripts/tests/tower-media.test.sh` — run the 21 cases concurrently in their own directories so the battery fits `battery.unit_time_limit` (limit untouched). Targeted test: `bash scripts/tests/tower-media.test.sh`, `scripts/unit-battery engine-wrappers`.
4. `docs/units/engine-wrappers/contract.md` — the unit's published surface (the five commands), why the manifest `contract` slot stays empty, and generated outputs via `scripts/generate` (no hand-written aggregate).
5. `docs/units/engine-wrappers/retro.md` after the final gate.

Premises: P-03 (units stay logical; confirmed, medium: with a physical move the wrappers' paths would break every caller), P-04, P-05 (no literals in the unit: verified zero, low), P-07 (no contract change: the executables keep paths and behaviour, high — callers are ~40 sessions). CRITICAL: none.

Single final gate: `scripts/gate-dev --pr N`. Known base defects: tower-catalog cover concurrency and read-latency timing tests (not changed).
Deferred, not improvised: `scripts/tower-catalog` and `tower-factory` compare the node major to a literal 22; reading `toolchain.node_version` would break the wrapper tests that copy wrappers into temp checkouts and is the toolchain unit's value (T1). The checker does not flag it.
