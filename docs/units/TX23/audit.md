# TX23 audit: expected lists derived inside tests

Base: `mod/roadmap-integration` at `891b835a`. Principle T2: adding a stage, a test or a selector edits no expected list inside another test. All three cited sites still hold on this base. Baseline runtime assertion counts (every `TestCase.assert*` call, `subTest` loops included): `test_gate_areas.py` 580 in 24 tests, `test_gate_report_skips.py` 62 in 8, `test_gate_script_tests.py` 107 in 15.

## F1 `scripts/tests/test_gate_areas.py:44-49`: four copies of registry groups

`SECRETS`, `WEB`, `BUILDS`, `E2E` repeat `always` and the `web-check`, `builds`, `e2e` groups of `scripts/lib/gate-areas.json` by stage name (`DEV` is already `policy.DEV_STAGES`). They feed 12 case rows, `test_package_json_...` (:197, :208) and `test_scoped_report_...` (:246). A stage added to `always` or to a group (#732 adds `pr metadata`; also m671, m736) fails every row until this file is edited. The case table is the real test (which path selects which area groups); the stage names inside a group are not.

Fix: build the lists from `gate_areas.load()` (`always`, `groups[...]`). The cross-check that the dev battery equals `policy.DEV_STAGES` (`test_front_plan_is_the_dev_battery_plus_a_new_deploy`, :160) stays, and a new property asserts that `always` plus the groups cover `order` exactly once and in order, so a registry edit that drops or duplicates a stage is still refused.

## F2 `scripts/tests/test_gate_report_skips.py:132`: pinned `BEFORE_SPLIT` sha256

The digest covers the whole event list of a fixture run. The part that moves with the stage registry is the `input_hash` of the verdict: `gate_proof.verdict_payload` hashes `[sha, mode, expected_stages]`, and `expected_stages('dev')` is `policy.PLANS['dev']`. Every stage-adding PR changes it and re-pins (#732 does). Everything else in the bytes is fixed by the fixture.

Fix: build the expected events inside the test, from the fixture and the registry (`forge_events.subject`, `step_payload`, `port.build`, the step prefix and tier modes from `config`, `input_hash` from `PLANS['dev']`) and compare them to `gate_events` structurally and as serialized bytes. A changed field, key, order, value or event id still fails; a new stage does not.

## F3 `scripts/tests/test_gate_script_tests.py:24-64` and `:79-86`: exact selections and the `modules: true` set

- `setup`, `new-lib-python` and `admin-cli` pin the exact tuple of tests chosen for a path. Any new test whose `covers` match (4 PRs so far) edits them.
- `test_only_web_package_tests_ask_for_installed_modules` pins the three `modules: true` tests by name.

Fix: an oracle in the test reads `scripts/tests/covers/*.json` directly and computes the expected selection for each case path (a path outside `scripts/` counts only when a manifest covers it; a path no manifest covers is the full suite). The `modules` set is checked by property: a test asks for installed modules exactly when a covers glob names `apps/web/scripts/**` (it runs the web package) or its script runs `scripts/generate --check` (kept as is). Each case also keeps the explicit relation (`chosen` is a proper subset of the suite for scoped rows, equal to it for full rows).

## Out of scope

`gate_areas.py`, `gate_report.py`, `gate_script_tests.py`, any registry and the covers manifests (TX20, TX11, TX26 and engine-gate-plan own them).
