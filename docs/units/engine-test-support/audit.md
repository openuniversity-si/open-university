# engine-test-support: audit (U4)

Evidence from the base `mod/roadmap-integration` (a2c09043).

- **Physical form.** `scripts/units addresses` gives the unit no `@ou/` address (engine units live under `scripts/`;
  U3a defines no address form for Python/shell). Per the U4 brief the files stay in place; the executables under
  `scripts/` keep their paths.
- **Import graph (who uses the unit's files).** `scripts/tests/rest_fake.py`: `invoker-tooling`, `gate-db`,
  `merge-phase` script tests, `test_claude_session.py`, `test_forge_events.py`. `scripts/tests/root_probe.py`:
  `test_root_identity.py` (own). `scripts/tests/fixtures/media-key-contract.json`: `test_production_check.py`,
  `apps/web/src/media/domain/objects.test.ts`. `scripts/tests/delivery_test.py`: `delivery.test.sh`.
  Published surface = `rest_fake.py` and `media-key-contract.json`.
- **Contract slot.** `unit_battery.plan` resolves `contract.entry` against the unit's address home; with no
  address the contract step is red. Filling `contract` now would turn the battery red, and `unit_battery.py` belongs to
  `engine-battery`, so the slot stays empty and the surface above is recorded here.
- **Literals.** The unit has no `x-literal-sites` entry; `tests.unhermetic_sites` held one stale site
  (`scripts/tests/test_claude_session.py:random`, structure-check warned it no longer offends). Removed: zero now.
- **Battery.** `scripts/unit-battery engine-test-support` was red: `script-tests` 60 s against
  `battery.unit_time_limit` 10 s (never loosened). Slowest: claude-session 16.8 s, gate-optimization 9.2 s,
  test-db 9.1 s. Two tests also failed on base: `gate-isolation` (2) and `invoker-tooling` (2).
- **Failure class.** Both failures are one class: a test builds a hand-picked partial copy of the repository
  (`scripts/lib`, `config`) that lags the library (missing `contracts/`, `gate_select.py`, `adapters/`).
- **Size.** Unit is far below `units.size_ceiling`; not oversize.
