# engine-env plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/engine-env/audit.md`).
2. Plan (this file).
3. Battery within its limit: `toolchain_manifest` reads each registry value once per load and `artifact` takes a loaded manifest; tests pass it.
4. Zero literals: `config/registry/env.json` (six entries), readers in `env_manifest`, `toolchain_manifest`, `session_identity`, generated types.
5. Contract document (`docs/units/engine-env/contract.md`), as engine-wrappers did.
6. Retro (`docs/units/engine-env/retro.md`).

## Dependency graph and owned files
`1 → 2 → {3, 4} → 5 → 6`. 3 owns `toolchain_manifest.py` (artifact/load/checksum_key), `test_preflight.py`, `test_toolchain_pins.py`; 4 owns `config/registry/env.json`, `env_manifest.py`, `session_identity.py`, the generated file, and the one-line timeout in `toolchain_manifest.py`. Both touch `toolchain_manifest.py`, so they run in sequence (3 then 4). The steps are small; the coordinator executes them directly.

## Premises
Premises: P-03, P-04, P-05, P-07.
- (high) P-03 units stay logical: files stay in place. Wrong: moving later is a manifest edit plus alias regeneration.
- (medium) P-05 literals migrate with the unit: six registry entries, no inline fallback.
- (medium) P-07 expand->contract: no contract field added; a later addition is additive.
- (low) P-04 size budget: 1,299 lines, under the ceiling.
- **CRITICAL**: none (no money, production or source of truth).

## Tests
Per commit: `scripts/unit-battery engine-env`, `scripts/structure-check`, `scripts/generate --check`. One final `gate-dev`.

## Known base defects
`config.get` costs about 50 ms a call (store replay each time); owner engine-config. This unit reduces its call count; the cache is theirs.
