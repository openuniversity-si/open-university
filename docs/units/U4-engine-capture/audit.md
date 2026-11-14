# U4 engine-capture: audit (read-only)

Base: `origin/mod/roadmap-integration` a2c09043 (includes LR1 #575, CO1 #576). The earlier branch (#560) is not reused.

## Findings

- Unit `engine-capture`: 10 paths, about 470 lines (well under `units.size_ceiling`; no `unit.oversize`).
- Physical form: `scripts/` units have no `@ou` address (UNITS.md: "A unit outside the TypeScript project (the engine's `scripts/` units) ... has no address until it has its own directory"). Importers (`scripts/lib/*.mjs` among themselves, `scripts/tests/*`, `scripts/gate-local`, `scripts/lib/ship_verify.py`) name the files by path, and `scripts/cloud-webkit` is an executable entry. Per the brief, the files stay in place; the rest of the definition of done is delivered.
- No manifest has a `contract` yet; the schema (`contracts/units/unit.v1.json`) takes `{entry, version}`, `entry` a file of the unit.
- Public surface (exports imported by other units today): `capturePage`, `installCaptureRoutes`, `readFreshHealth` (capture-page.mjs), `chromiumArgs` (chromium-args.mjs), `rasterParity` (raster-parity.mjs), `auditInherited` (prune-inherited-audit.mjs), and the python `DirectImageNormalizer`. Importers outside the unit: `scripts/tests/*` (engine-test-support), `scripts/lib/ship_verify.py`/`delivery_test.py` (engine-production).
- Literals (tunables spelled inline): navigation timeout 45000, session wait 20000, image wait 30000/45000, viewport widths 390/1440, scroll steps 700/800, viewport height 1000, JPEG noise tolerance 3, production base URL, capture paths, locale/timezone, docker image tag, probe attempts 100, shm size. The no-literals checker judges only registered names, so these are invisible to it today; they are moved to `config/registry/capture.json` and read through one reader.
- Tests: the unit's tests (`production-capture`, `media-parity`, `prune-inherited`) belong to `engine-test-support`; not edited. The unit battery runs only `scripts/tests/*.test.sh` for engine units, so the unit needs a test file of its own.
- Lessons (`scripts/lessons for-area`) cannot run in this checkout as a Python file (it is a shell wrapper): nothing applicable found.

## Evidence
`scripts/units check`: 104 manifests valid. `python3 scripts/lib/unit_battery.py engine-capture`: green, 0 tests (nothing owned).
