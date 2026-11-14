# U4 engine-slo audit (read-only; cheap evidence only)

Brief: migrate unit `engine-slo` (D-067): contract, battery, zero literals, hermetic tests. Base `mod/roadmap-integration` @ a2c09043.

| Area | Evidence | Consequence |
|---|---|---|
| Physical form | `docs/architecture/UNITS.md`: units stay logical (S1, P-03); `@ou/<id>` addresses exist only for TypeScript units, and "a unit outside the TypeScript project (the engine's `scripts/` units) has no address" | Files do not move: `scripts/dashboard`, `scripts/slo` are public executables and `scripts/lib/slo.py` is a library with no address form. Deliver manifest contract, battery, literals, tests. |
| Importers | `rg 'slo'` over scripts, docs, config, units: only `scripts/slo`, `scripts/dashboard`, the two tests, `config/registry/slo.json` (`x-readers`), `gate-script-tests.json` and `docs/structure/assets.json` | Published surface = `scripts/lib/slo.py` (module; B1 reuses `fold()` and `percentile()`). No other unit imports it. |
| Literals | `scripts/lib/slo.py` reads 13 names through `config.get`; no `x-literal-sites` entry names the unit's files | Already zero literals and zero allowlist; nothing to shrink. |
| Battery | `scripts/unit-battery engine-slo` was red: 44.45 s against `battery.unit_time_limit` (10 s). Profile of `test_slo.py`: 24k `config.get` calls (each replays the registry and the change store, ~2.4 ms), 184 `make_log` builds, 562 schema validations | Fix in the unit's tests (see plan); the per-call cost of `config.get` belongs to `engine-config` (lesson for its owner). |
| Generated outputs | `scripts/generate --check` clean on the base | Regenerate after the manifest change; expect no drift. |
| Lessons | `scripts/lessons for-area scripts/lib/slo.py`: none applied | none |
