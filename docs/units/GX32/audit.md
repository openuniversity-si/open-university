# GX-32 audit (read-only findings)

Base `mod/roadmap-integration` 3cae824a (contains GX-13 #729 32f3aca0, GX-37, GX-05, GX-08). Branch `mod/gx32`, PR #737.

## Cited sources, verified on the base
- `contracts/events/base.red.v1.json` (77 lines): payload `{repo, pr, sha, unit, premises, base_sha, tests[{id, stage, signature}] (minItems 1), since}`, natural key `(repo, base_sha)`. `base.green.v1.json` (54 lines): `{…, base_sha, cleared[str]}`, natural key `(repo, base_sha)`. Both locked in `contracts/events/schemas.lock.json:3,7`, owned by `units/engine-events`. No producer and no consumer exist yet (`grep -rn "base\.red"` over scripts/config: only `scripts/tests/test_event_contracts.py:180-181`, the fixture). Not edited (E47).
- `scripts/lib/defect_detect.py` (257 lines, GX-13): `recorded_base` (:70-84), `rerun` (:127-153), `outcome` (:156-167, per (base, test) cache), `changed_files` (:170-175), `touched` (:178-191), `adjudicate` (:194-210), `verification` (:213-231), `explained` (:234-241), `apply_to_report` (:244-257).
- `scripts/lib/gate_adjudicate.py` (49 lines): `adjudicate` (:31-49) calls `recorded_base`, `changed_files`, `apply_to_report`. No change needed (the new path lives behind `apply_to_report`).
- `scripts/lib/battery.py` (219 lines): the battery role, tier 3 on `integration.advanced`. `run_tip` (:137-152) emits `battery.green` / `battery.red` with `failing = [first failed stage]` (:90-91); `Tier3Gate` (:94-99) is `engine_role.CommandGate` over `battery.tier3_command` (`scripts/gate-local --tier3 --sha`).
- `scripts/lib/engine_role.py:188-217` `CommandGate.run(commit, env)`: passes `env` to the command; the result `GateResult(ok, stage, log, tests, kind)` (:45) carries failing test *files* only, no signatures. Not mine (unchanged).
- `scripts/gate-local:280-286`: `logs="${GATE_REPORT_DIR:-…}"`; the report (`stages.json`) and per-stage logs land there (`gate_report.py:210`). Tier-3 mode is not adjudicated (`forge-events.tier1_gate_modes` = `["dev"]`, `gate_tier.adjudicated`), so its `stages.json` holds raw results.
- `scripts/lib/gate_failures.py`: `vitest_failures` (:50-61), `script_failures` (:64-66), `browser_failures` (:69-71), `failing` (:91-101, capped at `gate.failing_tests_max`). The same signature function serves both sides.
- `config/registry/defects.json` (458 lines): `defects.stages` default `["script tests"]`; no `base_signal_enabled` key.
- Ownership: `units/engine-defects/unit.json:12` globs `scripts/lib/defect_*.py`, so a new `defect_adapters.py` needs no manifest or CODEOWNERS change. `scripts/tests/covers/defect-detect.json` and `covers/battery.json` exist (GX-08 sidecars).
- Gate stages (`scripts/lib/gate-stages.json`): per-test stages are `script tests`, `unit tests`, `integration tests`, `e2e smoke`, `performance tests`; the rest (scans, build, lint, typecheck, install, db schema) are whole-stage.

## Current behaviour on 3cae824a (what GX-32 changes)
1. **Only script tests can be excused.** `explained` (`defect_detect.py:238`) collects failures only from `script-tests.json`; `adjudicate` (:199) sends any stage outside `defects.stages` (= `["script tests"]`) to `own`; `unexplained` (:240) keeps any failed stage without attributed script failures. A vitest/browser test red on the base blocks every PR (F-02).
2. **Every excuse costs a base re-run.** Each failing script test is re-run on a throwaway worktree of the base (`outcome` → `rerun`, :156-167, `rerun_timeout_s`); cached per (base, test), so the first PR on each new base pays it.
3. **Tier 3 does not say which tests are red.** `battery.red` carries `failing: [stage]` (:90-91, :143-150); nothing publishes `base.red` / `base.green`.
4. **GX-13 touched rule** (:178-191): a test whose file, covers manifest or declared covers the PR changed is never excused. It compares the test id with repo paths, which works for script ids (repo paths) only; a vitest id (`|project| src/x.test.ts > suite`) is relative to `apps/web`.

## BD1 #667 (head 28f96db5): what is harvested
`defect_adapters.py` there: one adapter per failure shape (`script`, `vitest`, `browser`, `whole`), each with `extract(stage, report, logs)` → `(failures, complete)`, plus re-run commands, `load` (concurrency) and `defects.stage_shapes`/`rerun_*` keys. Harvested: the per-shape `extract` with its completeness rule, the `whole` shape (never excused) and the id → file parsing (`PROJECT` regex). Not taken: per-shape re-run commands, load re-runs and their keys (the base signal replaces a vitest/browser re-run; script tests keep the GX-13 re-run), the `kind`/load-sensitive record field (contract change).

## Not in scope / routed
- "Re-gate asks pause while the base is red": the re-gate requester is the train/coordinator (`train.py`, not mine). This unit exposes `defect_detect.base_red(base)` for it; wiring is a follow-up for the train owner.
- Known base defects / env failures: KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (pinned gate adjudicates); env `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (GX-ENV).
