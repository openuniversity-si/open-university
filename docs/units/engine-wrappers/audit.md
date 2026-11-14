# engine-wrappers audit (U4)

Read-only findings, base `mod/roadmap-integration` a2c09043.

- Unit: 7 paths (`scripts/run`, `tower-catalog`, `tower-media`, `tower-factory`, `factory-bench`, and the tests `tests/run.test.sh`, `tests/tower-media.test.sh`), 330 lines, far under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical and U3a addresses are generated from a unit's *home* (deepest common directory). These files are executables directly under `scripts/`, which other units share, so the unit has no `@ou/` address and the executables are the public entry contract (they keep their paths).
- Contract slot: `contract.entry` is checked through the unit's address. With no address, a filled slot makes the battery red (`the contract entry run is not a file of engine-wrappers`, measured). The slot stays empty; the published surface is the five commands, recorded in `docs/units/engine-wrappers/plan.md`.
- Literals: `config_check.literal_findings` reports none for these files and no registry `x-literal-sites` entry names them, so the allowlist for the unit is already zero.
- Battery: `scripts/unit-battery engine-wrappers` was red at 10.79 s against `battery.unit_time_limit` (10 s). `tower-media.test.sh` alone took 10.1 s: 21 sequential wrapper starts, each a node start. `run.test.sh` takes 0.7 s.
- Hermeticity: both tests use stubs (fetch preload, curl tripwire) and no network.
- Lessons: `scripts/lessons` is a shell script (not importable); no area lesson applied beyond D-069 item 14 (never loosen the limit, make the test faster).
