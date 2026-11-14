# TX32 audit: web path aliases derived from the unit manifests

Base: `origin/mod/roadmap-integration` at `891b835ae` (2026-10-28).

## Evidence re-check

| Brief claim | On this base |
|---|---|
| The aliases are hand-written; each PR adds one 3-line alias by hand | **No longer holds.** The `@ou/` keys are already generated from `units/*/unit.json`: target `addresses` (`config/registry/generate.json:126-136`), renderer `scripts/lib/generate_addresses.py:10-15`, map `scripts/lib/unit_addresses.py:107-126` (U3a, `ca301ea28`). `scripts/generate --check` (`scripts/lib/generate.py:81-104`) already fails with `apps/web/tsconfig.json: differs from its regeneration; run scripts/generate addresses`. |
| Every unit PR edits `apps/web/tsconfig.json` | **Holds.** The target's `output` is `apps/web/tsconfig.json` itself (`config/registry/generate.json:134`), so a PR that adds a web unit must commit the regenerated `paths` into the hand-written project file; the 26 open U4 PRs all touch it. |

So the class to remove is "the generated map lives inside a hand-written file", not "the map is hand-written".

## Readers of the `paths` (every one must follow the move)

| Reader | file:line | Lane | How it finds the file |
|---|---|---|---|
| generator `addresses` | `config/registry/generate.json:134` | unowned | `output` |
| architecture checker aliases | `scripts/lib/architecture/tree.mjs:109-119` | engine | registry `units.tsconfig_files` (`config/registry/units.json:194-198`) |
| unit size map aliases | `scripts/lib/unit_map.py:88-100` | engine | registry `units.tsconfig_files` |
| gate db-area import rule | `scripts/lib/gate_areas.py:152-159` | engine | registry `gate-areas.db_tsconfig` (`config/registry/gate-areas.json:72-80`) |
| unit addresses project dir | `scripts/lib/unit_addresses.py:52-55` | engine | `dirname(addresses.output)`: unchanged (`apps/web`) |
| vitest aliases | `apps/web/vitest.config.ts:33-35` | tooling | literal `./tsconfig.json` |
| Node address reader | `apps/web/scripts/lib/ou-addresses.mjs:14` | tooling | literal `tsconfig.json` |
| architecture tests fixtures | `apps/web/scripts/lib/check-architecture.test.ts:13-16`, `architecture-engine.test.ts:14-17` | unowned | inject the real file as `apps/web/tsconfig.json` |
| intent tables test fixture | `apps/web/scripts/lib/intent-tables.test.ts:8-11` | tooling | same |
| tsc, Next, ESLint | `apps/web/tsconfig.json` | tooling | follow `extends` natively |

## Engine readers that break if only the registry moves (prerequisite)

- `scripts/lib/unit_battery.py:82-85`: the per-unit types project `extends` `unit_addresses.project()[0]`, the addresses output. Moved to a paths-only file it would lose `strict`, `jsx`, `moduleResolution`: a weakened check. It must extend the project tsconfig (a registry key), not the map.
- `scripts/tests/test_unit_battery.py:31,129`: asserts that `extends` equals the addresses output.
- `scripts/tests/test_aggregates.py:149`: reads `apps/web/tsconfig.json` paths by literal.
- `scripts/tests/test_gate_areas.py:366-369,402,454`: feeds the real `apps/web/tsconfig.json` as the db tsconfig by literal.

All four are engine-lane (`scripts/units owner`), so they go in a separate small engine-lane PR that is correct both before and after the move; this tooling-lane PR then flips the output.
