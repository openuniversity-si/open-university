# GX-30 audit (read-only, base `ebab9368`)

Brief: plan.md §3.3 GX-30 + plan-v2 §4 row (batch-comment link from GX-12, `merge.json` read from GX-22, queue index in a new `train_queue.py`).

## Cited sources, verified on the base
| Cited | On base? | Evidence |
|---|---|---|
| `scripts/lib/train.py` queue (`:141-149` at GA3) | yes, now `train.py:150-158` | `Train.queue`: `open_changes` then `read` + `change` per open PR, every time |
| halt on base move (`:265-267`) | yes, now `train.py:290-292` | `TrainHalt('... moved after batch ... was built')` |
| break on first forge refusal (`:268-275`) | yes, now `train.py:294-300` | `break` after `pr.conflicted`; the members after the refused one wait for the next batch |
| `gate_batch.py:55-69` union | yes | `merge_union`, `plan` (`:72-96`); `scripts/gate-batch` exists but nothing calls it (F-10) |
| `train.tier2_command` | yes | default `["scripts/gate-dev", "--sha"]`, `config/registry/train.json:133` |
| `engine_role.CommandGate` | yes | appends the commit to the command; fresh build and test caches (`engine_role.py:163-190`) |
| `config/registry/merge.json` | **no** | GX-22 not launched (PR search 27/10); `merge.*` keys absent, `config.get` raises on unknown keys |
| tier-2 v4 verdict event (GX-12) | **no** | GX-12 not launched; today the tier-2 verdict on the log is the `engine.step.measured` `train:tier2` event |
| MQ1 critical-path order | harvested | `a1227c41` / `802fd273`: `merge_on_pass.order` = most transitive dependents in the unit graph, then oldest `pr.ready`; `merge_on_pass.py` is not on the base |

## Findings
1. **Union plan (F-10).** `gate-batch` takes PR refs and builds its own combined commit (`commit-tree` without fixed dates), so its sha differs from the train's combined commit (dated from parents, `train_git.combine`). The train's flake proof and tree proof key on the train's sha. So the tier-2 run must gate the train's own commit: `gate_batch.plan` needs a `--head` that is verified (same tree as the union) and used. `CommandGate` appends one commit; the members and base must reach `gate-batch` without breaking the rollback command (`gate-dev --sha`), so they travel in the environment (`GATE_BATCH_BASE`, `GATE_BATCH_MEMBERS`), which `gate-dev` ignores.
2. **App-only batch.** `gate_policy.select_dev_plan(['apps/web/src/...'])` is scoped `web-ui` with no `script tests` stage; `['scripts/lib/train.py']` selects `script tests`. The union plan inherits this.
3. **Refusal (F-16).** After member k is refused, members k+1.. were only proven on a head that contains k. Merging them unproven would break the tree proof. Safe reading of "merges the rest": merge the proven prefix, then rebuild the remainder on the new tip and judge it once (bounded by `train.rebuild_max`), all in the same batch call.
4. **Base move (F-16).** Same mechanism: rebuild the batch on the new tip, at most `train.rebuild_max` times, then halt as today.
5. **Queue cost (G-09/G-10).** Every queue build costs `open_changes` + 2 REST calls per open PR (the full log read pages). The drain rebuilds the queue after every batch. No adapter offers "events since"; `forge_github.py` is outside this unit. The index therefore uses an optional adapter capability `events_since(repo, since)`; an adapter without it (GitHub today) keeps the full build, which is also the rollback (`train.queue_since_last_batch` false). Follow-up for the forge lane: `GitHubAdapter.events_since` over `GET /repos/{repo}/issues/comments?since=`.
6. **Batch comment link.** `train.batch.green` / `.red` contracts are `additionalProperties: false` and owned by GX-37 (#706); no field can be added here. The tier-2 verdict's `event_id` is computable (`engine.step.measured` natural key) and is printed by the role and returned from `run_batch`; the payload field needs a v2 contract (contracts lane).
7. **Files outside the list that the goal needs:** `scripts/gate-batch` (the wrapper must accept `--tier 2`; unit `engine-gate-run`), `units/engine-train/unit.json` + `CODEOWNERS` (new module claim, allowed by the brief), `scripts/lib/generated/config_registry_train.py` (generated), `scripts/tests/covers/train.test.json` (new covers), `docs/units/GX30/`.

## Tests in scope
`scripts/tests/train.test.sh` (test_train.py), `train-role.test.sh`, `gate-batch.test.sh` (test_gate_batch.py; not edited, covered via test_train.py fixtures).

## Known base defects (not this unit)
`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh`, uid-65534 fs-encoding crash (GX-ENV); KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (FIX-modules #712).
