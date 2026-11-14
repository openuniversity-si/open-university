# GX-FIX-registry plan (D-070)

Critical path: 1 -> 2, about 10 min; no parallel edges (2 reads 1 only for the docs).

1. Audit and plan docs (docs/units/GX-FIX-registry/**).
2. sitecustomize installs the rules, then drops the tooling's scripts/lib modules and path entry; an import hook pins any later `config` to the tests store. Guard test in `scripts/tests/test_hermetic.py` (fixture root with an extra registry key, child with this checkout's hermetic dir).
3. Retro (docs/units/GX-FIX-registry/retro.md).

Premises: P-42. Targeted tests: test_hermetic.py, hermetic.test.sh, hermetic-expectations.test.sh, test_config.py. One final gate. Known env failures: claude-session, root-identity, config RegistryMemo (GX-ENV).
