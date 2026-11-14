# engine-production audit (U4)

Read-only findings, base `mod/roadmap-integration` c0e748c8.

- Unit: 14 paths (`scripts/production-check`, `scripts/preview-deploy`, `scripts/preview-policy.json`, `config/registry/production.json`, the libs `production_check.py`, `production_guard.py`, `site_health.py`, `html_normalize.py`, and six tests), 1773 lines, under `units.size_ceiling` 1500 per production lines (`unit_check.oversize` returns nothing; no `unit.oversize`).
- Physical form: S1 keeps units logical and U3a addresses come from a unit's home (deepest common directory). These files sit directly under `scripts/` and `scripts/lib/`, shared with other units, so the unit has no `@ou/` address; `scripts/production-check` and `scripts/preview-deploy` are the public entry contract and keep their paths. Nothing moves.
- Contract slot: `contract.entry` is checked through the unit's address; with no address a filled slot turns the battery red (measured by the engine-wrappers U4). The slot stays empty; the surface is recorded in `contract.md`.
- Literals: `config_check.literal_findings` reports none and no registry `x-literal-sites` entry names these files, so the allowlist for the unit is already zero.
- Battery: `scripts/unit-battery engine-production` was red at 12.12 s against `battery.unit_time_limit` (10 s). `production-guard.test.sh` took 9.8 s, of which `test_cli_exit_codes` 4.5 s: the test built the clean environment with `config.get('production.cloud_session_markers', ROOT)` inside a comprehension, one registry read (about 36 ms) per environment variable, 176 reads. The CLI itself runs in 0.14 s.
- Hermeticity: the tests use temporary repositories, fake PATHs and stubs; no network, no production script is run.
