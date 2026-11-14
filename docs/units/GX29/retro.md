# GX-29 RETRO — hermetic network, DB residue, covers trace

## 1. Brief quality
- Cited `config/registry/cloud.json` as "new": it already exists on the base (engine-cloud). Keys went into it; `gate-trace.json` was new and pre-claimed by `units/engine-gate-report`.
- Branch: the brief said `mod/gx29`, the harness designated `claude/gx29-hermetic-network-t66m63`; the designated one was used (one branch, one PR #716).
- "Dev gate with network denied" was not defined for a shell; and the brief forbade manifest edits while the unit check requires a manifest for every production file and every import edge (see 3).

## 2. Audit and plan
- Held: `tower_test_f02` is the bootstrap database `postgres.py ensure` re-creates; no test-owned fixture leaks beyond throwaway names. Plan items 2–5 were independent except 3→5 (both edit `hermetic.py`).
- Broke: the first plan assumed a new `deny-network.cjs` file; the unit check refuses a production file of no unit and manifests were off limits, so the hook is embedded in `hermetic.py` and written to the temp directory (`_NODE_HOOK`).

## 3. Execution (failure → class)
- Proxy on the loopback carried traffic out of the Node denial → class: "loopback is not offline"; fixed by dropping proxy variables in `shell_env`.
- `net.connect` hands `Socket.connect` an already normalized `[options, cb]` → the first Node hook let everything through; test spawns a real Node child.
- Lazy `config.get` after `sitecustomize` drops the tooling modules → `ModuleNotFoundError: forge_events` in the first lookup; `install()` now reads the loopback hosts eagerly.
- Engine literal census (LT1): 9 findings in new code/tests (numbers, hosts, URL); fixed in one commit by reading hosts/limits from the registry and removing indexes. Baselines are GX-38/39's, untouched.
- Two harnesses in one process (shell PYTHONPATH + the test's own import) made `TimeoutTest` fail (pre-existing: reproduced on the untouched base with PYTHONPATH set); `_state['run']` now unwraps the first wrapper.
- Slot interpreters have their own Python: fonttools in the main interpreter did not help; a seeded wheelhouse (`cloud.offline_seed_paths` entry `wheels`) lets each slot install offline.
- Timeline (BRT, 17:4x–19:xx): audit/plan docs, DB residue, network denial, seed, trace, then three offline gate runs (11.5 min, 9.4 min, final).

## 4. Gate
- Offline run 1 (head 4c3f9b5f..a6135c5e): script tests (hermetic TimeoutTest, literal census) and browser inventory (fonts) failed → fixed above.
- Offline run 2 (8de6e522): everything passed except structure check / units test: new file of no unit, and two import edges that need `requires` lines in `units/engine-gate-run` (→ engine-test-support, for `gate-fixed.sh` calling `test_db.py sweep`) and `units/engine-hermetic-tests` (→ engine-gate-plan, for `hermetic.py` calling `gate_script_tests.trace_check`). The file was removed (embedded hook); the two edges are manifest edits left to the coordinator per the brief.
- Known defects hit: see the PR STATUS.

## 5. Lessons
- Brief template: say whether a "new" registry file exists and who pre-claimed unit paths; state when new import edges need `requires` edits and who makes them (owner: coordinator/GX-38).
- A shared helper for "build a child environment" (proxy drop, harness, offline flag) now exists: `hermetic.shell_env`; `scripts/lib/gate-local` should adopt an `--offline` switch calling it (owner: gate-run lane) instead of the `eval "$(… shell-env)"` entry used here.
- The covers trace needs the covers of helper tests: a test named by several manifests is judged against their union (done); long term, one manifest per Python test (owner: GX-08 follow-up).
- `LT1` messages should name `config.get` alternatives for hosts in tests; a `tests.outside_host` registry entry would remove the per-test constant (owner: tests registry).
