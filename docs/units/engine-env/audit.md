# engine-env audit (U4)

Read-only findings with the cheap evidence that backs each. Base `a2c09043` (mod/roadmap-integration).

## Scope
`units/engine-env/unit.json`: 15 paths (env-check, env-update, env_manifest, preflight, session_identity, toolchain_check, toolchain_manifest, five Python tests, four `.test.sh`), 1,299 production lines, requires engine-cloud, engine-config, engine-github. Under `units.size_ceiling`, so no `unit.oversize`.

## Physical form
`docs/architecture/UNITS.md` (S1, P-03): units stay logical. `scripts/units addresses` gives an address only to units inside the TypeScript project; every engine unit is outside it, and none has moved. Decision: files stay in place; the executables keep their paths (the public entry contract). Nothing is moved, so no shim exists to delete (D-029).

## Contract slot
`unit_battery.plan` resolves a manifest `contract.entry` through the unit's TypeScript address and reports the step red when there is none ("the contract entry ... is not a file of <unit>"). Adding `contract` to a Python unit turns its battery red, and the fix belongs to engine-battery, not here. The importer graph (computed with `rg` over `scripts/`): `preflight.require` (ship_tail), `session_identity.{exclusive_lock,open_lock}` (gate_suite, gate_noite, ship_verify, neon_pr), `toolchain_manifest.{toolchain_dir,load,artifact,install_id,versions}` (credentials, test_db, cloud/toolchain, cloud/postgres), `toolchain_check` (structure). Decision: leave `contract` empty, record the surface here and in the PR, and wait for a Python address form.

## Battery
`scripts/unit-battery engine-env` is red: 42.3 s against `battery.unit_time_limit` (10 s). Per-test timing: `test_preflight` 27.8 s, `test_toolchain_pins` 10.2 s. Profile of `toolchain_manifest.load()`: 2.5 s, 47 `config.get` calls at about 50 ms each (each call replays the config store), 497 recursive calls, because `checksum_key` called `versions()` (7 gets) once per tool. Class: a unit function that reads the registry once per item, not once per call.

## Literals
`config_check` flags no registered literal in these files and no `x-literal-sites` entry names them, so the allowlist is already zero. Unregistered tunables remain: subprocess timeouts 30 s (version probe), 60 s (pnpm view), 120 s (pnpm audit), 900 s (build smoke) and the uid/gid range 100..1000. File modes are security semantics, not tunables, and stay.

## Tests
All four `.test.sh` pass; they are hermetic (no network, fixtures, `OU_TOOLCHAIN_DIR` tmp roots). No flake seen. `test_pinned_vercel_cli_starts` runs the installed CLI (about 0.4 s).

## Lessons
`scripts/lessons for-area scripts/lib/preflight.py`: none applied.
