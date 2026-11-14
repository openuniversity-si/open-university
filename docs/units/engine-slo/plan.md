## Plan

Unit files stay in place (no address form for Python, UNITS.md); the rest of the definition of done is delivered.

Commits (dependency graph: 3 before 4; 1 and 2 are docs):
1. [x] audit.md (owns docs/units/engine-slo/audit.md).
2. [x] plan.md (owns docs/units/engine-slo/plan.md).
3. [ ] Battery under `battery.unit_time_limit`: `scripts/lib/slo.py` `settings()` reads only names not overridden; `scripts/tests/test_slo.py` reads each registry value once per process, builds each fixture log once. Test: `scripts/tests/slo.test.sh` and `scripts/unit-battery engine-slo`.
4. [ ] Manifest: `battery` command and `decisions`. The `contract` slot stays empty: `unit_battery.plan` resolves its entry through `@ou` addresses, which a Python unit does not have, so a filled slot turns the battery red (`the contract entry lib/slo.py is not a file of engine-slo`). The published surface is documented in audit.md (`scripts/lib/slo.py`: `settings`, `fold`, `percentile`, `evaluate`, `run`, `dashboard`); owns `units/engine-slo/unit.json`. Test: `scripts/units check`, `scripts/generate --check`.
5. [ ] retro.md (owns docs/units/engine-slo/retro.md), after the gate.

Premises (blast radius): P-03 logical units, files stay (medium: if a Python address form lands later, the move is a manifest-path change); P-04 size budget (low: unit is 5 files, under `units.size_ceiling`); P-05 literals migrate with the unit (low: already zero); P-07 expand->contract (low: contract 1.0.0 is new, no consumer). None CRITICAL.

Targeted tests: `scripts/tests/slo.test.sh`, `scripts/unit-battery engine-slo`, `scripts/units check`, `scripts/generate --check`; one final `gate-dev`.
Known base defects expected: timing-sensitive tower-catalog cover concurrency and read-latency tests (owners: catalog lane).
