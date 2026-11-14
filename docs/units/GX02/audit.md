# GX-02 audit (read-only, 27/10)

Base tip `4bc4dd04` (later than the brief's `25c6f7a8`; GX-00, GX-01, GX-04 and #677 are on it). Branch `mod/gx02`, PR #695.

## Cited sources (brief standard v2 (2))
- `eaa408de` exists (on `origin/claude/merge-train-pr-ready-f7mxzt`) and is not on the base: `git merge-base --is-ancestor` exits 1 (GA-P05 holds). It touches `docs/operations/train.md`, `docs/units/TR2/plan.md`, `scripts/lib/train.py`, `scripts/tests/test_train.py`, `units/engine-train/unit.json` (27+/2-). It does not conflict with the base, so it lands as commit 1 unchanged. `docs/units/TR2/plan.md` is outside the §3.3 file list but is part of the unchanged content.
- `gate.class_line_prefix` (`config/registry/gate.json:516`, default `GATE-CLASS:`) and `gate_classify.class_line` (`scripts/lib/gate_classify.py:60`) exist. `gate-runner.sh:39` prints the line for every red stage and `gate-local:87` prints it for every driver abort. Its form is `<prefix> <stage>\t<class>`, and the class is one of `gate_classify.ACTIONS` (code, env, contract).
- `contracts/events/env.drift.v1.json` exists with a generated module, and nothing emits it (`grep -rn "env.drift" scripts/lib` finds only the generated file; this was F-12). Its required fields are repo, pr (nullable), sha, unit, premises, stage, tool (nullable) and versions.
- `docs/process/EVENTS.md:69` lists `env.drift` with the producer "gate `env` class → env lane".

## Findings
1. `engine_role.CommandGate.run` (`engine_role.py:150-159`) takes the stage from the first `^FAIL (.+)` line. The gate's human lines start with `FAIL <stage> (<time>; exit …; log: …)`, so that stage also carries the time suffix. The result has no class.
2. `eaa408de` classifies with `gate_classify.classify(result.stage, result.log)`. `result.log` is only the last `train.tier2_log_chars` (2000) characters of the output, so a long red stage can push its evidence out of the tail. The bisection hook reads `self.last_result` through the flake callback.
3. Halt vs eject has no switch, so rolling it back needs a code revert. The brief asks for `train.halt_classes`.
4. `Tier3Gate` (`battery.py:94`) shares `CommandGate`, so the class parsing serves the battery too. The battery itself does not change here.
5. Tests: `Tier2.test_the_real_gate_runs_the_registry_command_with_a_fresh_cache` (`test_train.py`) expects the stage `lint` from a bare `FAIL lint` line. With the class line as the source, that fake gate must print the class line, and a gate output with no class line needs its own explicit test (the fallback).
6. Covers: `scripts/tests/train.test.sh` covers `train.py`, `train_git.py` and `config/registry/train.json` (`gate-script-tests.json:974-989`); `train-role.test.sh` covers the role. This unit does not touch `gate-script-tests.json`.

## Design choice (decide, then report)
A red run whose output has no class line (a timeout, or a gate older than GX-01) is classified once with `gate_classify.classify` over the full output, never over the tail. Its stage is the command name. A timeout therefore stays `code`, which is today's behaviour, and every red result carries a class. The train halts when `result.kind` is in `train.halt_classes`, so `[]` restores eject-on-anything.
