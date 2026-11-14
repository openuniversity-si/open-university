# TX26 audit

Goal (T3, cost scales with the change): adding or editing `scripts/tests/covers/<t>.json` selects test `<t>` and the covers-map check, not the whole script suite.

Re-verified on base `891b835ae` (mod/roadmap-integration), all cited evidence still holds:

- `config/registry/gate-tests.json:23-29` `gate-tests.fallback` lists `scripts/tests/covers/**` next to the selector code (`gate_script_tests.py`, the registry file, `scripts/gate-local`, `scripts/lib/gate-runner.sh`).
- `scripts/lib/gate_script_tests.py:131-134` `select()` returns the whole suite with `selector changed: <path>` for any path matching a fallback glob, so a manifest edit is treated as a change to the selector code.
- `scripts/lib/gate_script_tests.py:56-78` `load()` already fails closed: a malformed manifest raises `cannot read ...`, a script test without a manifest raises `no covers manifest ...`, a manifest without a script test raises `covers manifest without a script test`. `check()` wraps it. `select()` calls `load()` when no mapping is passed, and `scripts/gate-local:328` turns a raise into a red gate.
- The covers-map check is `scripts/tests/test_gate_script_tests.py:155` (`tests.check()` on the real tree), run by `scripts/tests/gate-script-tests.test.sh`. It is the test a manifest change must also select.
- A manifest `scripts/tests/covers/<t>.json` belongs to `scripts/tests/<t>.test.sh` (`manifest_path`, line 31).

Design findings:

1. A covers manifest is data about one test; only the selector code decides which tests run. So manifests leave the fallback and `select()` maps a manifest path to its own test. The selector code, the registry file, `gate-local` and `gate-runner.sh` stay in the fallback.
2. A manifest whose test does not exist (a removed test, a stray file) is not mapped: it falls through to the existing behaviour (full suite), and `load()` raises `covers manifest without a script test` in the same run.
3. The map check test path becomes a registry key (`gate-tests.map_check`) so `scripts/**` holds no new literal.
4. A new `test_gate_script_tests_covers.py` holds the new cases because `test_gate_script_tests.py` belongs to TX23. It needs its own `.test.sh` runner and covers manifest to be selected at all.
