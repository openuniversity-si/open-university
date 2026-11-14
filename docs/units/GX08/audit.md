# GX-08 audit — test map from per-test headers

Base `4bc4dd04` (`mod/roadmap-integration`). Read-only evidence, no suite run.

## Cited sources, verified on the base
- `scripts/lib/gate-script-tests.json`: `version 1`, `fallback` (4 selector files), `tests` (80 entries: `script`, `covers[]`, `modules` bool; 2 have `modules: true`). The brief says 79; `ls scripts/tests/*.test.sh` is 80 and `load()` enforces map == directory, so 80 is the number migrated.
- `scripts/lib/gate_script_tests.py`: `load()` (JSON, validates, checks against `discover()`), `select()`, `select_plan()`, `modules_required()`, CLI `select|modules`.
- `scripts/lib/gate_test_cache.py`: reader is `gate_script_tests.load()` (lines 69, 132). The key mixes in the entry `{script, covers}` and the sha256 of every file matching the script, its covers and `gate.test_cache_common_inputs`.
- Other readers of the JSON path: `config/registry/production.json` (production guard path list, line 50), `units/engine-gate-plan/unit.json`, `CODEOWNERS` (generated), `scripts/tests/engine-capture.test.sh` (a comment), `test_gate_script_tests.py`, `test_gate_test_cache.py`, `defect_router.py` (calls `load`, not the path). `scripts/gate-local` calls the CLI only.
- Registry: `config/registry/gate.json` has neighbours `gate.script_tests_concurrency` / `_log_lines`; generated module `scripts/lib/generated/config_registry_gate.py`.

## Findings
1. **Key trap.** The test file itself is a key input. A header added to a `.test.sh` changes its sha256, so every key would change, which breaks the acceptance "keys unchanged by the migration". Fix: the cache hashes a `.test.sh` with its header lines removed (same parser as the loader), so adding, moving or editing only a header never invalidates a result whose covers did not change; a covers change still does because the covers list is in the key.
2. **`modules` has no home** in `# gate-covers:`. It is a second declaration; 78 tests are `false`. Decision: `# gate-modules: true` line, only where true, default false, prefix registered as a third key (`gate.script_tests_modules_prefix`).
3. **Fallback** (selector files) must leave the JSON: `gate.script_tests_fallback`. It still names the JSON path today; the entry is replaced (the JSON is gone) and `scripts/lib/gate_script_tests.py` / `gate-local` / `gate-runner.sh` stay.
4. **Overlap handling.** GX-03/GX-05/GX-02 may add `.test.sh` files or JSON entries before this merges. `--migrate` reads the JSON, so a rerun after merging the base converts them; a test with a header and no JSON entry is kept as is (idempotent). Only after the JSON is deleted does the header alone count.
5. **Common-input side effect.** `gate_test_cache.py` is a common input of every key, so editing it once invalidates all keys regardless of the migration. The equality test therefore compares the two data sources with the same code.
6. **Structure check.** `structure.py` has no `.test.sh` rule; one call `gate_script_tests.check(root)` is added.

## Known base defects (not in scope, owner GX-ENV)
`claude-session`, `root-identity`, `config` (RegistryMemo) script tests and the uid-65534 fs-encoding crash fail on the base without any PR.

## Addendum 15:20 (plan-v2 scope)
Findings 1 (key trap) and 2 (`modules` header) disappear with sidecar manifests: no test file changes, `modules` is a field of the manifest, and the entry that enters the cache key (`{script, covers}`) is byte-identical, so every key is unchanged. A one-off check on the base for all 80 tests (keys from the legacy JSON versus keys from the generated manifests, same code, same tree) gave 80/80 equal. `gate_test_cache.py` needs no change: it reads only through `gate_script_tests.load()`; its docstring still names the deleted JSON (GX-03 owns that file; left for a later touch). Finding 6 (structure rule) moves to `gate_script_tests.check` and its test.
