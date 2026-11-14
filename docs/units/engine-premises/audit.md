# engine-premises audit (U4)

Read-only findings, base `mod/roadmap-integration` c0e748c8.

- Unit: 6 paths (`scripts/lib/premises.py`, `scripts/lib/decision_premises.py`, `scripts/premises`, `scripts/tests/premises.test.sh`, `test_premises.py`, `test_decision_premises.py`), 1,016 lines, far under `units.size_ceiling` (no `unit.oversize`).
- Physical form: S1 keeps units logical (P-03 `validated`, answer `measurement:S1`); U3a addresses come from a unit's home directory. These files sit directly under `scripts/` and `scripts/lib/`, which other units share, so the unit has no `@ou/` address; the files and `scripts/premises` keep their paths and behaviour. Importers (`structure.py`, `lessons.py`, `defects.py`, `local_checks.py`) are unchanged.
- Contract slot: stays empty (a filled slot is red without an address, measured in the engine-wrappers U4). The published surface is `scripts/premises` and the `premises` module functions other units import, recorded in `contract.md`.
- Literals: `config_check.literal_findings` reports none for these files; no `x-literal-sites` entry names them. The allowlist for the unit is already zero.
- Battery: `scripts/unit-battery engine-premises` was red at 60.7 s against `battery.unit_time_limit` (10 s) with one failing test.
  - Slow: `premises.setting` called `config.get` on every read (352 reads per register load), and each `config.get` replays the config store (about 12 s per `load`). Fixed in the unit by reading each registry value once per process (same for `decision_premises.setting`).
  - Failing: `Repository.test_repository_register_is_valid` expected P-03 to be answered by `A Torre`; P-03 was settled by spike S1 (`measurement:S1`, `validated`). Registered defect KD-4db6e693. The test now asserts P-03's real status and answerer and keeps `A Torre` for the other five.
- Hermeticity: tests run on fixture registers in temp directories, no network.
