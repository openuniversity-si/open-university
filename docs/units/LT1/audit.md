# LT1 audit: unregistered literals in `scripts/` (enforcement audit 26/10, rule 1, fix R3)

Base: `origin/mod/roadmap-integration` at `a2c09043` (includes LR1 #575 and CO1 #576). Read-only evidence; no suite run.

## The gap, confirmed
- `scripts/lib/config_check.py` (module of `scripts/structure-check`, called at `scripts/lib/structure.py:482`) judges
  only identifiers that spell a **registered** parameter (`Names.match`); its docstring says "Names that are not
  registered are never judged". A new `TIMEOUT = 30` or `"https://api.example.com"` in a new file passes.
- `config.literal_check_excludes` (`config/registry/config.json`) defaults to `["scripts/tests/", "scripts/lib/generated/"]`,
  so tests are not scanned although D-069 item 3 and the brief cover them. `scripts/lib/generated/` stays out: the
  generated drift stage (`scripts/generate`, G1 #507) owns it.
- Measured on the base: turning the tests on for the existing registered-name rule yields **0** new errors
  (`check_literals` with the excludes reduced to `scripts/lib/generated/`, 1.2 s). The tightening is free for that rule.

## What exists and is reused (no second mechanism)
| Need | Existing piece | Use |
|---|---|---|
| Which files are engine files | `config_check.engine_files` (roots, excludes, suffixes, shebangs from the registry) | the census scans exactly these files |
| Registered-name literals, fallbacks, `x-literal-sites` | `config_check.check_literals` | unchanged |
| Shrink-only per-area list, D-063 style | `structure.baseline_files` / `check_absolute_baseline` over `scripts/lib/absolute-literals-baseline/<area>.json` (`files` → `<kind> <json value>` → count) | generalized to `structure.baseline_areas(root, base, folder)`; the engine list is the subfolder `engine/`, one file per unit |
| Area of a file | U0 `scripts/lib/units.py` `unit_of(path)` (D-067) | the area is the owning unit; unowned files (fixtures) fall in a registry-named area |
| Registry format and reading | `config/registry/config.json`, `config.get(name, root)` | every rule (numbers allowed, patterns, allowed values, folder, unowned area) is an entry |
| Local fast check | `scripts/lib/local_checks.py` `no_registered_literals` | unchanged in this PR (budget ~5 s); the gate runs the full census |

The apps/web census (`apps/web/scripts/lib/absolute-literals.ts`, `readExceptions`, `writeExceptions --write`) reads
only `*.json` directly inside `scripts/lib/absolute-literals-baseline/`; `structure.baseline_files` globs the same
non-recursively and `git ls-tree` lists a subfolder without `.json`. A subfolder `engine/` is therefore invisible to
the D-063 census, its drift test and `check_shared_literals` (D-064 c): no collision with the apps/web list.
`units/engine-structure/unit.json` already owns `scripts/lib/absolute-literals-baseline/**`.

## Census prototype (base + this rule, tests included, generated excluded)
- 3,010 offenders in 213 files, 31 areas (30 units + 1 unowned fixture): number 2,656, url 139, absolute_path 129,
  host 48, duration 30, port 8. Census wall time ≈ 1.8 s over 507 tracked files of `scripts/`.
- Noise found and fixed in the prototype, not baselined: f-string format specs (`{n:02d}` read as a duration),
  ANSI escapes (`\033[0m`), `\thttps` escapes, `${X:-54322}` defaults hidden by a broad `${...}` strip (now only
  positionals, lengths, redirections and the `:-` operator are removed, so the default is counted).
- Not settings, allowed by a registry entry (never in code): `/dev/null`, `/dev/std{in,out,err}`, `/usr/bin/env`.

## Item 4 (docs describing the registry as a `parameters` list)
Searched every tracked file outside `apps/web` and `node_modules` (`"parameters"`, `['parameters']`, `parameters:`,
"list/array of parameters"): **no hit**. `docs/process/principles/D-069.md:257`, D-068 (`docs/domain/DECISIONS.md:70`)
and `scripts/lib/config.py:3` already describe JSON Schema `properties`; the test helpers named `**parameters` build
`'properties': parameters`. Nothing to correct on this base; recorded here as evidence.

## Gate files touched (D-025)
`scripts/lib/config_check.py` and `scripts/lib/structure.py` are structure-check modules. Authority: D-068 (6) (the
structure check refuses engine literals), D-069 items 1 and 3, D-025 for the gate change; cited in every commit.

## Known base defects expected
- tower-catalog cover concurrency ("expected 6 to be 7") and read-latency ("10,000 courses in under a second") on
  4 vCPU: timing-sensitive, owned by the catalog lane; never changed here.

## Lessons
`scripts/lessons for-area scripts/lib/config_check.py config/registry/config.json scripts/lib/absolute-literals-baseline`:
none applied for this area.
