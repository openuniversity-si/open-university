# GX-30 RETRO (train: union plan, proven-prefix merge, rebuild on base move, queue index)

PR #717, branch `mod/gx30`, base `mod/roadmap-integration` at ebab9368 (unchanged during the session).

## 1. Brief quality
- Clear on scope, files, keys and acceptance. Two cited sources did not exist on the base: `config/registry/merge.json` (GX-22 not launched) and the tier-2 v4 verdict event (GX-12 not launched). Plan item 8 waits on GX-22; the batch link uses the only tier-2 verdict on the log today (`engine.step.measured` `train:tier2`).
- Missing: the train's `batch` events are `additionalProperties: false` contracts owned by GX-37, so "the batch comment links the verdict event_id" cannot be a payload field from this unit. Kept as `Train.verdicts` + the printed batch line; the field needs a v2 contract.
- Missing: `train.tier2_command = ["scripts/gate-batch", "--tier", "2"]` needs `scripts/gate-batch` to accept `--tier` (unit engine-gate-run, not in the file list) and needs the members, which `CommandGate` (appends one sha) cannot pass. Solved with `GATE_BATCH_BASE` / `GATE_BATCH_MEMBERS`, which the rollback command ignores.
- Missing: the brief does not say that every new number in a test is an engine literal (LT1 census) and that the per-unit baseline is frozen for this unit (only GX-38/39 may edit it). That cost one gate run (below).
- "Queue rebuilt from pr.ready events newer than the last batch" needs a repository-wide "events since" read that no adapter offers and `forge_github.py` is outside the unit. Built as an adapter capability; GitHub keeps the full replay until the forge lane adds `events_since` (`GET /repos/{repo}/issues/comments?since=`).
- Branch: the harness named `claude/gx-30-…`, the brief `mod/gx30`; the brief's name was used (one branch, one PR).

## 2. Audit and plan
- Premises: P-14 / P-15 untouched (no measurement possible without a real batch). GA-PG3 (P-47) applies only to item 8.
- The plan held: 8 items, serial (all code items share `train.py` / `test_train.py`; no sub-agents, a split would have cost more than it saved).
- One reading choice: "a simulated forge refusal merges the rest" is implemented as merge the proven prefix, then rebuild the rest on the new tip and judge it once (bounded by `train.rebuild_max`), never merging an unproven head.

## 3. Execution (commit times, container clock)
| Commit | Time | Item |
|---|---|---|
| adcc4a0c audit | 21:02 | 1 |
| d0f547b4 plan | 21:02 | 2 |
| 1f93239b union plan | 21:06 | 3 |
| 5410bf44 rebuild + proven prefix | 21:08 | 4 |
| ecaa5209 queue index | 21:10 | 5 |
| 7c89dd03 critical path + verdict link | 21:12 | 6 |
| 59cf8ee0 literal class fix + engine-units | after gate 1 | 6 |
| b5e8abff RETRO | after gate 2 | 7 |
| 94d72a19 merge of base 81a28fb9 (covers-list conflicts, both sides kept) | coordinator 21:07 | — |
| b5a3bf53 merge of base d889e6a1 (GX-22, merge.json) | coordinator, GX-22 merged | — |
| e186cf08 train reads merge.json | after GX-22 | 8 |

Failures and their classes:
1. A test expected the first bisection probe of 3 members to be 1 member; `first_red` probes the middle (2). Test error, fixed before commit.
2. Gate 1, structure check (class code): the LT1 literal census counted 28 new `2`s, 12 `3`s and others in `test_train.py`, and new `2`/`3` in `scripts/gate-batch`; one `40` disappeared. Root cause class: tests that write PR numbers and counts directly. Class fix: one fixture helper (`Fixture.make`) numbers PRs, counts are derived from fixtures (`READS_PER_PR`, `CHAIN`), the shell tier branch passes words to Python, which validates them. Census equals the list with no baseline edit.
3. Gate 1, structure check: `train.py` imports `units` and engine-train did not declare engine-units (D-067 U2). Fixed in the same commit.
No second failure from either cause.

## 4. Gate
- Run 1 (7c89dd03, pinned to ebab9368): FAILED: structure check (literal census, above) + script tests `gate-db.test.sh` (`ModuleNotFoundError: forge_events`), `hermetic.test.sh` (timeout test 0 != 1), `invoker-tooling.test.sh`: the known base defects of the brief (KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 family; FIX-modules #712, GX-ENV). Gate evidence post: 403 (class env, the cloud token).
- Run 2 (59cf8ee0, pinned to ebab9368): stages 7/7 PASS, script tests 76/81 with the 5 failures adjudicated known (KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3); exit FAILED only on the evidence post (403, class env). The three gate-context failures passed standalone on base and head.
- Run 3 (94d72a19, pinned to 81a28fb9): PASSED, 7/7 stages, 84/84 script tests, no known defect needed, 158.9 s. MERGE-READY was posted, then withdrawn on the coordinator's 21:13 correction (no partial merge; item 8 first).
- Run 4 (daa8c69e, pinned to d889e6a1): FAILED on one script test, `gate-result-cache.test.sh` ("expected [6] got [0]: a corrupt marker runs the stage again"), gate class **env**; the advisory run of the same head in the same invocation passed it. Not a known defect. Investigation (incident, cause outside this unit):
  - Mechanism: the test's private `mktemp -d` directory (`/tmp/tmp.JHptwgEQlY`) disappeared while the test ran: `FileNotFoundError .../logs/unit_tests.stage.json`, then `flock: cannot open lock file .../logs/output.lock`, and `runs()` read 0 because `$work/ran` was gone too. The test only removes it in its own EXIT trap.
  - Not this change: the test was selected only through its `config/registry/*.json` cover (train.json changed); it reads no `train.*` or `merge.*` key and runs none of `train.py`, `train_queue.py`, `gate_batch.py`, `scripts/gate-batch` or `engine_role.py`. Every temp dir this unit's code and tests create is its own (`mkdtemp`, `gate-batch`'s own `$work`). Standalone it passed 5/5 on daa8c69e and 3/3 on the base d889e6a1.
  - Owner: the deleter of another process's temp dir during parallel script tests is not found by grep (no `/tmp` sweep, `find -delete` or exported `work` in `scripts/`); routed to the driver/env lane (GX-29 hermetic, GX-ENV) as an open class: a script test's temp dir must be namespaced per test run (e.g. `TMPDIR` per test in `gate_test_cache.py`) so no concurrent test or sweep can remove it.
- Run 5 (final): see the MERGE-READY comment.

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| Literal census found by the gate, not before | Add `python3 scripts/lib/literal_census.py` to the brief's "targeted tests" for any unit touching `scripts/` (it is in `commit-check --local` only as a gate-budget check, `no_registered_literals: gate`) | brief template (coordinator) |
| Tests write PR numbers | `Fixture.make`-style helper in shared test fixtures for every forge test (test_train_role, test_coordinator) | engine-train / engine-coordinator lanes |
| New import of another unit not declared | `structure-check` before the first push of a code commit, not only on the body | brief standard v2 (4) already says so; I ran it only on the body: follow it |
| Contracts closed to new fields block "link X" asks | Briefs that ask for a new event field name the contract owner and version bump | planning coordinator |
| No repository-wide "events since" | `GitHubAdapter.events_since` | forge lane (forge_github.py) |
| Two coordinator messages 6 min apart reversed "mark ready" (21:07 → 21:13); I acted on the first and posted MERGE-READY, then withdrew it | A MERGE-READY only when every plan item is ticked (the `pr.ready` rule already says so: it was not emitted, "items not ticked: 8"); the session should have held to that over the message | unit sessions / coordinator |
| A test's temp dir deleted under it during the parallel script-test stage (run 4) | Per-test `TMPDIR` in `gate_test_cache.py` run, removed after the test | driver lane (gate_test_cache.py / GX-29) |
| `config/registry/merge.json` lists only merge-phase, merge_behind and commit_check as `x-readers`; train.py now reads two keys | Add `scripts/lib/train.py` to the `x-readers` of `merge.require_exact_head` and `merge.max_behind_base` | merge.json owner (GX-22 lane) |
