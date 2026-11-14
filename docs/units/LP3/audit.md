# LP3 audit — fold, validate and log the live plan

Base `mod/roadmap-integration` at `3c834942` (LP2 #701 merged). Read-only findings, cheap evidence only.

## Cited sources (verified on the base)

| Source | State |
|---|---|
| `scripts/lib/plan_live.py` | LP2 stub: `PlanError`, `fold`, `digest`, `validate`, `read_log`, `append` raise `NotImplementedError`; `FIXTURE` path constant |
| `scripts/tests/fixtures/live-planning-fold.json` | `plan` (3 units), 2 `changes` (brief_line+hold; add_unit+set_deps+release), `expected`, `expected_at` 0..2 |
| `contracts/events/plan.changed.v1.json` | 16 ops; required repo/pr/sha/unit/premises + program/version/parent/ops/…/digest |
| `config/registry/planner.json` | `planner.log_branch` (`plan/live`), `planner.launch_hold_path`, `planner.partition_recent_decisions` list `plan_live.py` as reader |
| `contracts/programs/program.v1.json` + `program.graph_problems` | schema and graph check (unique ids, known deps, wave order, no cycle) — reused by `validate` |
| `scripts/program` → `scripts/lib/program.py` | subcommands list/check/graph/status/new/migrate-queue; no `plan`/`log` |
| `origin/plan/live` | does not exist yet (LP6/LP9 create it); `read_log` treats a missing log as version 0 |

## Findings

- F1. Both fixture digests equal sha256 of the canonical JSON (sorted keys, `,`/`:` separators, `ensure_ascii=False`) without
  `digest`: the runbook formula is the contract. The fixture changes omit `repo/pr/sha/unit/premises`, so `fold` and the
  chain check must not require the envelope fields; schema validation of a full payload is `event_contracts`' job.
- F2. Fixture semantics: `add_unit` appends at the end of `units`; `set_deps` replaces `depends_on` verbatim; `hold` stores
  `args` (`reason`, `release_when`) under `holds[unit]`; `release` deletes it; `brief_line` appends `args.line` to
  `brief_lines[unit]`; `priority` stays `{}` without `reorder`. Version 0 = the plan plus `version: 0` and the three empty maps.
- F3. Test execution: the gate runs only `scripts/tests/*.test.sh` listed in `scripts/lib/gate-script-tests.json`
  (`gate_script_tests.load` refuses an unlisted runner). LP3 may not edit that map and GX-08 sidecars have not merged, so a
  new runner is impossible: `test_plan_live.py` runs from `program.test.sh` (the program sidecar is LP3's). `plan_live.py`
  is not in its covers yet: a diff touching only it is an uncovered scripts path, which runs the whole suite (safe, slower).
  The covers line is left to after GX-08 (brief rule).
- F4. Ops beyond the fixture (`set_unit`, `remove_unit`, `reorder`, `set_estimate`, `rescope`, `redo`, `continue`,
  `register_defect`, `apply_lesson`, `escalate`, `note`) have no fixed `args` shape in the contract; LP3 defines the minimal
  one in the module docstring and keeps the non-graph ops as records (`notes`) so the fold never drops information.
- F5. No literal is needed beyond `planner.log_branch` and `coordinator.programs_dir`; the log file name stays derived from
  the design (`plan-log.jsonl`) — see the plan for the key decision.
