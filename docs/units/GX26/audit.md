# GX-26 audit (base da1ac7f5)

Read-only; evidence only. Premise P-46 and decision D-070 (plan-v2 §4 row GX-26).

## 1. What exists for `--explain` / `--why`
- `scripts/gate-dev` (9 lines) forwards everything to `scripts/gate-local --dev` (`scripts/gate-dev:9`). Only `--batch` is handled there (`:5-8`).
- `scripts/gate-local` parses flags at `:60-74`. `--list` (`:65-67`) prints the static stage list of a mode through `gate_policy.py plan` (`scripts/lib/gate_policy.py:161-166`); it knows no diff, no selection, no carry. There is no `--explain` and no `--why`.
- The plan for one PR is built by `gate_policy.classify_pr` (`gate_policy.py:114-142`): `changed_paths` (`:83`), `select_dev_plan` (`:60`, over `gate_areas.plan_for`, `gate_areas.py:430`), `selection_for` (`:90`, `gate_select.select`) and `carry_plan` (`:99`, from `gate_carry.decide`, `gate_carry.py:98`). `classify_pr` also does `git fetch` and, with `logs`, writes `carry.json`; `gate-local:378-386` calls it as `gate_policy.py classify --pr --sha --base --output`.
- Script test selection: `gate_script_tests.select_plan` (`gate_script_tests.py:~166`). Cache key and lookup: `gate_test_cache.key` (`:150`) and `lookup` (`:179`), store at `store_location()` (`:137`). A cache marker is read-only to look up, so a hit can be predicted without running.
- Preflight: `preflight.gate_problems` (`scripts/lib/preflight.py:178`); `gate-local:146-153` runs it before the lock.
- Expected wall (GX-25) and plan completeness (GX-21): no module on the base exposes either (`rg 'eta|completeness' scripts/lib/gate_status.py` finds nothing relevant). `--explain` must print "unknown (GX-25 not merged)" / "unknown (GX-21 not merged)".
- A red gate prints `FAIL <stage> (...)` and a class line from `gate_classify.py` (`:62-82`) and writes `stages.json` plus per-stage `*.stage.json` under `.gate/records/reports/<sha>/<mode>-<ts>/` (`gate_report.py:17-21, 209`). No single "why" summary (failing test, class, log path, base status); base status (GX-13) has no module on the base.

## 2. Docs that drifted
| Item | Where | Reality |
|---|---|---|
| `.gate/logs/` | `AGENTS.md:43` (the only live hit; `rg '\.gate/logs' AGENTS.md docs scripts` outside programs/units) | Logs live in `.gate/records/reports/<sha>/<mode>-<ts>/` (`gate-local:129`, `gate_report.py`). `local-gate.md:62` no longer has the path. |
| `gate-quiet` plan | `AGENTS.md:19` ("lint, typecheck, unit tests and build in <= 20 lines") | `scripts/gate-quiet:5` execs `gate-local` with no mode flag: the legacy full gate on the working tree (mode `pr`, `FULL_STAGES`). |
| Budget | `docs/adr/ADR-28-full-local-gate-budget.md:1,33,39,48` (90 s); `ADR-33:11` (90 s warning, 2-3 min warm); `local-gate.md:193,221,389` | One budget: `gate.ceiling_s` 180 s, warning only (D-064 (f)). |
| D-065 (5) wording | `local-gate.md:323` (tier 3 row), `gate_tier.py` | Tier 3 (battery, Chromium only, no Neon); GX-11 made tier 2 (train batch) run every selected test uncached (`gate_test_cache.py:13-15`). Wording must say tier 1 caches, tier 2/3 do not. |
| Graph role | `local-gate.md:199` says the graph's `schedule()` is "the schedule `gate-local` implements" | The stage schedule is bash (`gate-runner.sh` launch/join, `gate-fixed.sh`); only script tests use `gate_graph` (D-A8 drops the scheduler swap, plan.md:50). |
| `gate_graph.schedule` mentions | `rg 'gate_graph.schedule' docs scripts` finds only programs/ (history); the swap is not claimed in `docs/operations` | Add one sentence stating it is dropped (D-A8) so the observable `rg ... \| rg -i 'scheduler\|swap'` finds only "dropped" text. |
| GX-06 runbook line | `docs/operations/train.md:5` and `:23-26` mention GX-06 | plan row says "removes the GX-06 runbook line after GX-11". GX-11's proofs line is at `train.md:42`; decide in plan.md which line is the runbook pointer. |
| `EVENTS.md:176-178` | lines shifted; the lifecycle/status-comment text is not at those lines on the base (176-178 is the adapter table) | Link the gate-status line from the status/event text to `docs/operations/gate-status.md`. |

## 3. Registry keys and covers
- Retired-key check: no key the program retired is identified on the base by the brief; `gate_script_tests.py check` prints `script test map ok`. Plan: list keys with `rg` for unreferenced `gate.*` keys; remove only a key a merged GX unit retired, regenerate the generated module and say so. Default: none.
- Uncovered path: to be measured with `gate_script_tests.select` on this diff; any `uncovered path` gets a sidecar `scripts/tests/covers/<test>.json`.

## 4. Known defects / dependencies
GX-25 (ETA) and GX-21 (completeness) not merged: degrade to explicit "unknown" lines. GX-13 base status: not on base; degrade the same way.
