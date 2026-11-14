# LP6 retro: planner role session and wake path

1. **Brief.** Clear on scope, seams and files. Two things were wrong or missing: the manifest claim it relied on
   (`scripts/lib/adapters/planner_wake*.py` in `engine-coordinator`) collides with `engine-vendors`' `adapters/**`, which
   no glob can exclude; and `planner.json` had none of the role's keys (lock, lease, retries, remote, wake), so a per-unit
   `planner-lp6.json` was needed, not optional. The harness branch (`claude/...`) and the brief's branch (`mod/lp6`)
   differed again (S7/L12); the brief won.
2. **Audit and plan.** Premises held: `engine_role.LockedRole` covered the lease without a wrapper; LP3's `plan_live`
   signatures were enough to code against with a stand-in (LP3 had not merged by the gate). The plan gained item 5
   (ownership fix) after commit 4; 6 → 7 items, no other change. No sub-agents: the steps shared one file set.
3. **Execution** (UTC, 27/10): audit 18:55, plan 18:56, lease + append 19:00, wake 19:02, ownership fix 19:04, runbook
   19:04, base merge 19:04 (35 commits behind: LP5, LP7, GX-05 merged meanwhile; clean). Failures and their class:
   (a) literal census refused numbers in code and test (`[-400:]`, exit codes, `parents[2]`, timeouts, dates): only
   0/1/-1 are allowed; fixed with one registry key and derived values. (b) a real concurrent push loses with
   `cannot lock ref` / `failed to update ref`, not only `non-fast-forward`: the race test found it; the lost-race
   markers include both. (c) structure-check before commit 4 ran on untracked files, which it does not see (it reads
   `git ls-files`), so the double claim reached a pushed commit; fixed in commit 5.
4. **Gate.** Run 1 on `246ec27a` (merge of base `0bc49fea`), `gate-dev --pr 714`, pinned base tooling, 93 s wall
   (91 s gate total): scoped plan (scripts, config, docs; no web stages owed). PASS generated drift 0.4 s, no GitHub
   Actions 0.02 s, schema compat 0.8 s, secret scan tree 2.5 s / history 6.2 s, structure check 11.3 s; script tests
   52.0 s: 13 of 14 PASS, FAIL `generate.test.sh` = known base defect **KD-024bbecb** (`intents-doc.ts`
   ERR_MODULE_NOT_FOUND: the map marks the test `modules: false`, so the gate checkout never installs `node_modules`;
   the same test passes on this head with them, 23 tests OK); gate evidence FAIL = env (forge write 403 for this
   session's credential). Both are named in the MERGE-READY comment. `test_planner_role.py` is run by no gate stage:
   Python tests run only through a mapped `*.test.sh`, the map is closed to LP units and GX-08 has not merged (run by
   hand: 15 tests OK, five repeats of the race tests green).
   After the retro, LP3 merged (base `26125b34`): the real `plan_live.append` folds against `docs/programs/<p>/plan.md`
   and `contracts/programs` of the same checkout, so an orphan `plan/live` (runbook §2's first step, the role's first
   version) could never take an append. Found by running the role against the real module, before the final gate;
   fixed in commit 8 (log branch cut from `planner-lp6.log_branch_base`, integration test through the real module).
5. **Lessons.** (a) Run `scripts/structure-check` after `git add`, never on untracked files (owner: Padrão / commit-check
   local stage, which could add the index's new paths). (b) A prep unit that claims a path for a later unit should add a
   stub there and run structure-check, so a double claim fails in the prep PR (CANDIDATE posted; owner: the live-planning
   prep template). (c) Role tests need an in-memory forge lock; one in `forge_events.MemoryAdapter` would end the
   per-test fakes (CANDIDATE, GX-17). (d) Push-race detection should share one marker list across the engine (CANDIDATE,
   GX-02). (e) The brief's "Python tests are run by the existing python-test discovery" was false on the base: a new
   test file is run by no stage until GX-08's sidecars land, so its first green is by hand only (owner: brief template /
   A Torre; until GX-08, every new Python test needs a mapped wrapper decided at launch). (f) `generate.test.sh` should
   be `modules: true` in the script-test map, and a failing script test should be parsed into `failingTests` so a known
   defect is matched (CANDIDATE, gate owner). (g) A unit coding against a parallel unit's stub must re-run against the
   real module as soon as it merges; the stub's docstring did not say where `append` reads the program from (owner:
   prep-unit template: a stub names every file its body will read).
