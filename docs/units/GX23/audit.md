# GX-23 audit — narrow web stage inputs (fail closed)

Base: `mod/roadmap-integration` eaeeb29d (contains GX-39 #705). Line numbers are on that base.

## How the web stage cache keys are built today

| Stage | Caller | Key function | Tree part of the key |
|---|---|---|---|
| lint | `scripts/lib/gate-fixed.sh:108` (`key --step lint --scope …`) | `gate_result_cache.key` (`scripts/lib/gate_result_cache.py:72-81`) | `tree_digest(root)` with no filter: every tracked or unignored file of the checkout (`:51-69`) |
| typecheck | `scripts/lib/gate-fixed.sh:109` (`key --step typecheck`) | same | same, whole tree |
| unit tests | `scripts/lib/gate-fixed.sh:124` via `gate_stage_key` (`scripts/lib/gate-runner.sh:121-124`) | `gate_result_cache.stage_key` (`gate_result_cache.py:89-97`) | `tree_digest(root, spec['inputs'])`, and `scripts/lib/gate-stages.json:83-93` declares `inputs: ["**"]`, i.e. the whole tree |
| integration tests | `scripts/lib/gate-fixed.sh:35` via `gate_stage_key` | same | `gate-stages.json:94-…` `inputs: ["**"]` |

Other key parts (unchanged by GX-23): the tier guard `gate_tier.cacheable(mode, TIER1_MODES)` (`gate_result_cache.py:43,76,92`; `scripts/lib/gate_tier.py:18-20`, tier 1 = `dev` only), the flags `session-cache.tier1_enabled` / `gate.stage_cache_enabled`, the key versions `session-cache.key_version` / `gate.stage_cache_version`, node and the toolchain pins (`TOOLCHAIN_PINS`, `:35-36`), the eslint/stylelint/typescript versions for lint/typecheck (`STEP_TOOLS`, `:37`), the scope, and the GX-39 seam `gate_keys.key_parts()` (`:80,96`; `scripts/lib/gate_keys.py:6-7`, empty until GX-28).

`step_cached` (`gate-runner.sh:104-118`) runs the command on an empty key, skips it on a hit, stores only after a pass. `gate_stage_key` swallows errors (`2>/dev/null || true`), so a raising key function means "run" for unit/integration; the lint/typecheck key calls end in `|| return 1`, so a raising key fails the gate loudly. Both directions are fail closed (never a false hit).

## Consequence (F-08, F-01)

All four keys cover the whole tree, so a base merge that touches only `scripts/**` or `docs/**` (most engine PRs, every RETRO) misses lint, typecheck, unit and integration: about 2-3 minutes of web work rerun for no input change.

## Fences

- Not editable here: `scripts/lib/gate-stages.json`, `scripts/lib/gate-fixed.sh` (E33/E34), `config/registry/gate.json` (no `gate.stage_cache_version` bump), `scripts/lib/gate_keys.py` (GX-28), `gate_report.py`, `gate-local`.
- So the narrowing lives in a new `scripts/lib/gate-stage-inputs.json` read by `gate_result_cache.py`; its own `gate-inputs.schema_version` (new `config/registry/gate-inputs.json`) is a key part of every narrowed key, which gives the one-time miss without touching `gate.json`.
- `gate_result_cache.py` and its tests are in `units/engine-gate-report/unit.json`; the two new files are claimed there.

## Premises

- GA-P10 (narrowing fails closed, medium): not in the register; register `P-10` is `aggregates-not-written-by-prs`, so it is not cited (D-A1). P-20 (graph selection tier 1, low) and P-46 (GA-PG1, pinned gate) are cited.

## Access trace

See [trace.md](trace.md): the read set outside `apps/web/**` per stage, from strace on the base in a throwaway worktree.
