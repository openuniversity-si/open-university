# S2 plan

## Commits (sequential: they share `supply_chain_check.py`, `supply-chain.json` and `structure.py`)
- [ ] 1. audit.md (done)
- [ ] 2. plan.md
- [ ] 3. `config/registry/supply-chain.json` (+ generated types) and `scripts/lib/supply_chain_check.py` lockfile integrity: every `packages:` entry has an integrity hash and a registry in `supply-chain.allowed_registries`; wired into `structure.py` (D-025); unit ownership, script-test mapping; fixture test.
- [ ] 4. Dependency allowlist: `vendor-map.json` gains `transitive` (one map); the check refuses a lockfile package outside `packages` + `transitive`, and a retired vendor; fixture tests.
- [ ] 5. Key scopes: `supply-chain.agent_key_scopes` (secret names only); the check refuses an unknown or forbidden name; fixture tests.
- [ ] 6. Docs (D-069 item 13 row), retro.md.

## Premises
P-02 (forge-agnostic, low), P-41 (no literals, high: every value is registry). A pnpm lockfile v9 resolves entries without `tarball:` from the registry pnpm is configured with: medium; if wrong the registry check passes entries it should inspect. Mitigation: `.npmrc registry=` is read and must be allowed.

## Tests
Per commit: `scripts/tests/test_supply_chain_check.py` via `scripts/tests/supply-chain-check.test.sh`, plus `structure-check`. One final gate-dev.

## Known base defects
Timing-sensitive tests (tower-catalog cover concurrency, read-latency): not touched.
