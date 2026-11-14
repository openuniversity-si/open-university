# KF2 plan

## Plan
- [ ] 1. docs: audit.md + plan.md (this) — owns docs/units/kf2/*
- [ ] 2. Shared address reader `apps/web/scripts/lib/ou-addresses.mjs` (+ Node resolve hook, scope from the units registry) with a hermetic test — owns that file and its test
- [ ] 3. countries.test.ts derives the expected specifier from the reader instead of a literal — owns countries.test.ts (after 2)
- [ ] 4. Node-run generator loads the hook (`--import`) from `generate_intents.py` and `intents:generate`, path through the config registry; python test — owns generate_intents.py, aggregates.json, package.json, test_aggregates.py (after 2)

Commits 3 and 4 run in parallel after 2 (disjoint files).

Premises: P1 module.registerHooks exists in pinned Node 22.23 (verified: node v22.23.3). P2 tsconfig paths are the only address source (verified, vitest uses it). No CRITICAL premise.
Targeted tests: ou-addresses test, countries.test.ts, `scripts/tests/test_aggregates.py`; then one gate-dev.
Known base defects: the two above (owner: KF2).
