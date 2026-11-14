# TX26 plan

Commits (each green alone; trailers `Plan: N`, `Decision: D-070`; one push each):

1. Audit and plan docs. Files: docs/units/TX26/*. No tests.
2. `select()` maps `covers/<t>.json` to `<t>` plus the map check; `covers/**` leaves the fallback; registry key `gate-tests.map_check`. Files: scripts/lib/gate_script_tests.py, config/registry/gate-tests.json (+ generated registry docs if `scripts/generate --check` names them). Targeted: gate-script-tests.test.sh, gate-select.test.sh.
3. New cases: scripts/tests/test_gate_script_tests_covers.py, scripts/tests/gate-script-tests-covers.test.sh, scripts/tests/covers/gate-script-tests-covers.json, unit path additions in units/engine-gate-plan/unit.json (+ `scripts/generate codeowners`). Targeted: the new test.
4. Retro and replay evidence. Files: docs/units/TX26/retro.md.

Graph: 1 -> 2 -> 3 -> 4 (3 needs the selector of 2 to assert on it).

Premises:
- P-46 (the covers manifests are the only per-test map; no PR edits an aggregate). Radius: medium. Holds: `load()` still validates every manifest.
- CRITICAL: a manifest edit must never skip validation of the map. Mitigation: the map check test is always selected with it, and `load()` raises inside `select()` itself on any malformed, missing or stray manifest.
- No other file in `config/registry` or `scripts/**` reads `gate-tests.fallback`.

Single final gate: pinned offline `gate-dev --pr 746` on the exact head.
