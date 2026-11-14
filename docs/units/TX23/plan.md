# TX23 plan

Lane engine-lane only (`scripts/units owner` maps all three tests to engine-gate-plan / engine-gate-report). No code under test, no registry, no covers manifest changes. No new literal except where the unit baseline shrinks.

## Commits (dependency graph: 1 -> {2, 3, 4} independent -> 5)

| # | Commit | Files | Targeted test |
|---|---|---|---|
| 1 | docs: audit and plan | `docs/units/TX23/{audit,plan}.md` | none |
| 2 | areas: derive groups from `gate-areas.json`, partition property | `scripts/tests/test_gate_areas.py` | `scripts/tests/gate-areas.test.sh` |
| 3 | report skips: build the expected events from the fixture and the registry, drop `BEFORE_SPLIT` | `scripts/tests/test_gate_report_skips.py` | `scripts/tests/gate-report-skips.test.sh` |
| 4 | script tests: covers oracle, `modules` property | `scripts/tests/test_gate_script_tests.py` | `scripts/tests/gate-script-tests.test.sh` |
| 5 | docs: mutation evidence, assertion counts, retro | `docs/units/TX23/{evidence,retro}.md` | none |

Each of 2-4 is green alone. If a literal baseline shrinks it is rewritten in the same commit (`literal_census.py --write <unit>`, own unit only).

## Premises

- P-46 (T2: expected lists derived from their registry). Blast radius: the three tests only.
- CRITICAL: no changed assertion gets weaker. Per change, three mutations of the code under test that the old assertion caught are run against the old and the new test; both must fail. The mutation script and its output go in `evidence.md`.
- Held at risk: a derived list that reads the registry the code also reads can not catch a wrong registry edit by itself. Mitigation: the independent `policy.DEV_STAGES` cross-check, the partition property, and the oracle/builder written from the covers manifests and the fixture, not from `gate_*` helpers under test.
- Census: the report-skips duration is `timedelta(seconds=1) // timedelta(milliseconds=1)` (0, 1 only), not a new `1000`.

## Final gate

One pinned `scripts/gate-dev --pr 749` on the exact head (offline path: `OU_CONFIG_STORE=file`), then MERGE-READY. Note for #732: after this merges, its hunks at `test_gate_areas.py:46` and `test_gate_report_skips.py:132` disappear; take the base versions at its next base merge.
