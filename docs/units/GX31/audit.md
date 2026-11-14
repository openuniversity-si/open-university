# GX-31 audit (read-only, base `891b835a`)

Brief: plan.md §3 GX-31 + plan-v2 §4 row: the reuse lookup lives in a new `scripts/lib/train_reuse.py` (not in
`gate_report.py`), the switch is `train-reuse.reuse_attested_proofs` in a new `config/registry/train-reuse.json` (D-B8).
The base moved after launch (132af477 → 891b835a, #739 GX-20); nothing in this unit's files changed with it.

## Cited sources, verified on the base
| Cited | On base? | Evidence |
|---|---|---|
| GX-30 judge path, `train.py` | yes | `Train.run_batch` → `self.tier2(port, commits[-1])` `train.py:318`; `tier2` → `engine_role.LockedRole.judge` `train.py:271-272`; bisection probes `self.judge(port, 'bisect', …)` `train.py:398` |
| `LockedRole.judge` | yes | `engine_role.py:136-151`: renew, measure, `self.gate.run(commit, env)` always, `record`, `last_verdict` = the measured event's id |
| `CommandGate` fresh caches | yes | `engine_role.py:186-215`: a fresh `GATE_BUILD_CACHE_DIR` and `GATE_TEST_CACHE_DIR` per run, "P-02 strict, D-065 (5)" |
| GX-28 attestation | yes | `gate_keys.toolchain_id()` / `attestation()` `gate_keys.py:15-35` (installed versions + effective registry, cached per process; fail closed) |
| v4 proof binding | yes | `gate_proof.bind` `gate_proof.py:139-160`: `head_tree`, `base_sha`, `plan`, `selection_digest(plan, batch)` (`:79-82`), `toolchain_id` (GX-28), `gate_version` = tree of `HEAD:scripts` at the tool root (`:122-124`), `input_digest` = `gate_digest.input_digest(...)` (`gate_digest.py:13-18`, order fixed by the contract) |
| v4 payload | yes | `gate_proof.proof_payload` `:227-238` copies `head_tree, base_sha, base_tree, gate_version, toolchain_id, input_digest, lane_id`, `selection.digest`; `version_of` / `proof_version` `:64-74` |
| tier 2 command | yes | `train.tier2_command` → `scripts/gate-batch --tier 2 <combined>` → `gate-local --dev --sha <head> --plan-file plan.json` (`scripts/gate-batch:9-35`); gate-local reads `base` from the plan file (`gate-local:170-173`) and the selection from `plan.json["selection"]` (`gate-local:389-393`); `gate_batch.plan(root, base, shas, head)` `gate_batch.py:81-107`; tier is 2 (`gate_tier.derive`, `gate-tier.batch`) |
| verified events | yes | GitHub adapter keeps only comments whose `author_association` is in `forge-events.github_trusted_associations` (`forge_github.py:57,126-131`); the port validates every envelope and recomputes `event_id` (`event_contracts.py:67-82`, `forge_events.py:319-341`) |
| box-local events | yes | `forge-events.file_kinds` = `["engine.step.measured"]`: the routing adapter stores them in the local file log (`forge_events.py:148-200`); the train's flake evidence `green_runs` reads these (`train.py:208-213`) — box-local, never proof |
| `train.json` | yes | not edited (plan-v2 §5.2); new keys go to `config/registry/train-reuse.json` (D-B8) |

## Findings
1. **Tier 2 never reuses today.** `judge` always calls `gate.run` (`engine_role.py:143`); `CommandGate` gives each run fresh caches. Rebuilding an unchanged batch (GX-30 rebuild, `train.py:300-335`) re-runs every stage. The switch-off behaviour to keep byte for byte is exactly this path.
2. **The key is computable before the run, by the train, from git and the attestation.** For a judged commit the train knows the base and the member heads (`self.prefixes`, `train.py:314`). `gate_batch.plan(ROOT, base, heads, commit)` gives the same `selection` gate-local binds; `plan` is `dev` (gate-batch runs `gate-local --dev`); `gate_version` is `gate_proof.gate_version(ROOT)` (the train's checkout is the tool root of `CommandGate`); `toolchain_id` is `gate_keys.toolchain_id()` in the train process (same container, same registry). So the train recomputes `input_digest` itself and never trusts a digest it did not compute.
3. **Where a proof can come from.** Only a `gate.passed` at the v4 proof version on the repository channel (pr null), stored by a remote adapter that filters by trusted author association; never a file-log event (box-local) and never a `.pass` / result-cache marker (tier 1). Every field must match: `input_digest`, `head_tree`, `base_sha`, `plan`, `selection.digest`, `toolchain_id`, `gate_version`, and `tier` = `gate-tier.batch`.
4. **Producer gap (not this unit).** `gate_publish.repository_run` / `publishes` exist (GX-12) but `gate_report.main` still publishes only with a PR (`gate_report.py:211-213`, `should_publish`); the caller wiring was handed to the `gate_report.py` owner (GX-12 retro lesson (c)). So on the base no tier-2 run writes its v4 verdict to the repository channel yet, and in the real environment the lookup finds nothing and tier 2 runs (fail closed, today's behaviour). `gate_report.py` stays closed (plan-v2 §4); the wiring is a multi-line change, not a one-line seam. Recorded for the coordinator: reuse becomes observable in production when that wiring lands.
5. **Cost of the lookup.** The repository channel is the log issue (`forge-events.github_log_issue`); reading it is `read` on one channel through the port, a few REST pages per tier-2 run, against a gate run of minutes. An adapter error, an unset log issue or any missing input fails closed (run).
6. **Bisection probes** go through the same `judge`; a probe whose prefix already has a matching proof is green by the same rule (the key includes its own prefix members' selection).

## Tests in scope
`scripts/tests/test_train.py` (`scripts/run test train`, covers sidecar `scripts/tests/covers/train.json`). New: `scripts/tests/test_train_reuse.py` + `scripts/tests/train-reuse.test.sh` with sidecar `scripts/tests/covers/train-reuse.json` (GX-08: never edit `gate-script-tests.json`, absent on base).

## Known base defects (not this unit)
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env tests `claude-session`, `root-identity`, `config` (GX-ENV).
