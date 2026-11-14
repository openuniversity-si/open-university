## Plan

Cites D-067, D-069 and D-029. Gate files are not touched.

### Commits (dependency graph; no file is owned by two commits)
1. `docs/units/engine-vendors/audit.md` (done, this commit).
2. `docs/units/engine-vendors/plan.md` (this file). Depends on 1.
3. Battery: drop the repo-wide `config.check` assertion from `test_ports_model_ladder.py` (config's own unit and structure-check run it). Owns `scripts/tests/test_ports_model_ladder.py`. Test: `scripts/unit-battery engine-vendors` under `battery.unit_time_limit`.
4. Contract 1.0.0: manifest `contract` {entry `lib/adapters/__init__.py`, version `1.0.0`} listing the published surface in the entry docstring, and a contract test that every published name exists and that nothing else outside the unit is imported. Owns `units/engine-vendors/unit.json`, `scripts/lib/adapters/__init__.py`, `scripts/tests/test_ports_contract.py`. Depends on 3.
5. Regenerate outputs (`scripts/generate` targets that exist), retro. Owns generated files and `docs/units/engine-vendors/retro.md`. Depends on 4.

Commits 3 and 4 touch different files but 4's battery run needs 3, so they run in sequence (the work is small).

### Premises
- P-03 (units stay logical, no address for Python): blast radius medium. If wrong, the files would move to `units/engine-vendors/`; the manifest paths and a move commit change, nothing else.
- P-05 (literals migrate with the unit): low; the unit is already at zero.
- P-07 (expand->contract): low; the contract is new, no consumer changes.
- P-04: low.
- None CRITICAL: no production, money or source-of-truth change.

### Tests
Per commit: the unit's own test files. Final: one `gate-dev --pr N`.

### Known base defects
Timing-sensitive tower-catalog tests on 4 vCPU (owner: tooling-perf); not touched.


## Origin vendor visibility (2026-11-02)

Request: close the measured Origin vendor blind spot under D-069 item 7, within the existing engine-vendors unit.
Premises: none

Initial measurement on d909f85f0: 9 vendors; github and claude active, github-actions forbidden,
codex/cursor/neon/vercel/cloudflare-r2/figma slot. Indexed temporary probes produce 2 GitHub errors,
1 Origin URL error misattributed to cursor, and 0 Origin shell CLI errors. Untracked probes are not scanned.
Native offline structure-check: 0 errors, 17 warnings. Hermetic judges expose two existing errors:
FORGE-PORT audit R2 has two whys; R1 plan Requirement names a machine instead of an owner.

Implementation choice: preserve the cursor host detector and assign each overlapping endpoint occurrence to
its more specific vendor path. Separate URLs in the same string/line must still be detected independently;
overlapping tokens belonging to the same vendor retain their current behavior. Register Origin as the forge
behind forge_events, with both existing transport/adapter files exempt as adapters, the factory as selector,
and an empty baseline. Module imports are calls too. No schema change is needed.

The adapter directory invariant currently rejects registering either existing Origin module. Recognize a
pre-existing adapter when first registering its vendor, provided the base already contains that exact path;
new files and additions to existing vendors retain the directory restriction. Test both sides.

Commit plan:
1. Record the measured scope and implementation choices (this documentation).
2. Add specific endpoint ownership, existing-vendor registration proof, Origin catalog entry and regression fixtures.

Validation: complete vendor-ports suite offline with hermetic bootstrap; indexed URL/Python argv/shell probes;
actual adapter and selector behavior; vendor check against the base; native and hermetic structure warning/error
list comparison; local commit check. Push every commit, open draft PR, never merge it manually.
