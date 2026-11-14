# Postmortem: engine parameters written as literals before the registry existed (2026-10-26)

Blameless (D-069 item 9). The question is which missing check let this happen, not who wrote the values.

## What happened

On 2026-10-26 the first wave of engine PRs (premises P1, event port M2, plan tick M4, session cache M5 and the first
config attempt C0, branches `mod/motor-*`) started before any configuration registry existed. Each session needed
tunable values (batch size, timeouts, retry counts, thresholds, cache keys) and wrote them where it stood: module
constants, function defaults and shell fallbacks such as `${GATE_CEILING_MS:-180000}`. Daniel saw it at 17:51 and set
the principle: no parameter or tunable value stays literal in code (D-068, P-41, his literal quote in the decision
register). The branches were kept for reference only and the wave restarted on shared formats (shared contract v3).

## Impact

- Four PR branches had to be redone instead of merged; their values were scattered over files no single place listed.
- Values already in the tree before the wave had the same shape: the D-008 size budget (`SIZE_BUDGET`), the D-022
  commit plan bounds (`PLAN_MIN`, `PLAN_MAX`) and the D-064 (f) gate ceiling (`GATE_CEILING_MS`).
- No production effect: production is frozen (D-054).

## Why (five whys)

1. Why were the values literal? There was no place to put them that every session knew.
2. Why no place? The registry was planned as a PR of the same wave, not as its first step.
3. Why did nothing stop the literals? D-063's literal gate covers `apps/web` only; the engine and tooling under
   `scripts/` had no check.
4. Why no check for `scripts/`? A check needs to know which names are parameters; without a registry there was no list.
5. Why did that matter now? The engine is where the throughput values live (D-065), and they change by event, so they
   must change without a code edit.

The root is the missing registry plus the missing check: the class, not the instance.

## The class fix

- The registry (D-068): `config/registry/<owner>.json`, JSON Schema 2020-12 validated by
  `contracts/config/registry.v1.json`, read with `config.get(name)` from `scripts/lib/config.py`, changed and audited
  through `scripts/config` (`set`, `history`, `revert`), with `config.changed` events.
- The gate check: `scripts/lib/config_check.py`, run by `scripts/structure-check` in the gate's `structure check`
  stage. It refuses, in the engine paths (`config.literal_check_roots`), any literal spelling of a registered
  parameter and any inline fallback after a registry read, and it validates the registry, the generated types and the
  contracts. Proof: `scripts/tests/test_config_check.py` (`test_a_registered_parameter_spelled_as_a_python_literal_fails`,
  `test_an_inline_fallback_fails`, `test_the_site_list_only_shrinks_against_the_base`,
  `test_the_repository_engine_paths_hold_no_unlisted_literal`), run by `scripts/tests/config.test.sh`.

## How it stays enforced

- A new parameter is a registry entry first; the check then refuses its literal anywhere in the engine paths.
- Three of the literals that predated the registry are read from it in the same PR: `SIZE_BUDGET`
  (`budgets.pr_changed_lines`), `PLAN_MIN` and `PLAN_MAX` (`budgets.pr_commits_min`, `budgets.pr_commits_max`).
  `GATE_CEILING_MS` is registered by the mechanical wiring PR, together with the tooling copies the gate's shell tests
  make of `scripts/lib/gate-budget.sh`. A literal that cannot move yet is listed on its parameter (`x-literal-sites`);
  that list only shrinks against the PR's base, and a site is accepted only for a literal the base already had, so no
  new literal can be grandfathered (P-05: literals migrate with their units).
- Changing the check's own scope (`config.literal_check_*`) is a registry change, visible in the diff and in
  `scripts/config diff --ref <base>`.

## Preventing check

- check: scripts/lib/config_check.py
- test: scripts/tests/test_config_check.py::test_a_registered_parameter_spelled_as_a_python_literal_fails
- test: scripts/tests/test_config_check.py::test_an_inline_fallback_fails
- test: scripts/tests/test_config_check.py::test_the_repository_engine_paths_hold_no_unlisted_literal
