# GX-09 audit

Base `mod/roadmap-integration` d101b73c (GX-37 #706 merged). Cited sources verified present on the base: `contracts/events/gate.{passed,failed}.v{3,4}.json` (both locked), `scripts/lib/gate_digest.py`, `config/registry/gate-contracts.json` (`gate-contracts.gate_{passed,failed}_version`, default 3), `scripts/lib/{pr_ready,slo,stall_report,train}.py`, `scripts/tests/{test_pr_ready,test_slo,test_push_guard}.py`, covers sidecars `scripts/tests/covers/{plan-tick,slo,push-guard}.json`.

## How a verdict reaches a reader

`ForgeEvents.read` (`scripts/lib/forge_events.py:319-340`) validates every envelope against `contracts/events/<type>.v<version>.json` (`event_contracts.validate`) and drops the invalid ones into `rejected`. So a locked v4 envelope already passes the read, and an unlocked version (v5) is rejected there. Every reader below then selects verdicts by **type only**; none names a version.

## Readers of gate.passed / gate.failed on the base

| Reader | file:line | What it checks | On a v4 event |
|---|---|---|---|
| `forge_events.apply` (replay; used by `pr_ready.emit_ready`) | `scripts/lib/forge_events.py:459-469` | skips `pr is None`; records `gates[sha][plan] = verdict, event_id` | works: v4 keeps `pr`, `sha`, `plan`; a tier-2/3 v4 verdict has `pr: null` and is skipped (repository channel, not a PR's evidence) |
| `forge_events.gate_evidence` | `scripts/lib/forge_events.py:509-512` | the passed verdict of exact head + plan | works (version-agnostic) |
| `pr_ready.emit_ready` | `scripts/lib/pr_ready.py:68-73` | replay + gate_evidence of the head/plan | works; no version source, so it would accept any type-matching verdict a future reader path let through |
| `slo.fold` | `scripts/lib/slo.py:28, 59-64` | `INPUTS` by type; `payload['tier'] == 1`; sum of `stages[].duration_ms` | works: v4 `tier` is an integer 1..3 and v4 stages keep `duration_ms`; tier-2/3 v4 verdicts are correctly outside the tier-1 SLO |
| `forge_events.gate_slow` | `scripts/lib/forge_events.py:487-506` | tier-1 median | works (not owned by GX-09; same shape) |
| `stall_report.stalls` | `scripts/lib/stall_report.py:42-49` | latest verdict by type on the PR channel, its `sha` vs head, `occurred_at` | works (reads only `type`, `payload.sha`, `occurred_at`) |
| `train.queue_entry` | `scripts/lib/train.py:64-86` | `pr.ready.evidence` names a `gate.passed` of the same sha | works, version-agnostic (plan-v2 E11); not edited, only tested |

## Findings

1. Nothing breaks on v4 today: the type-only reads are what makes v4 pass. The gap is the opposite: no reader states which versions it accepts, so the acceptance is implicit in `ForgeEvents.read` and the verdict type names are literals repeated in `slo.py:28,62`, `stall_report.py:42`, `forge_events.py:465,490`, `train.py:84`. A reader fed events that did not come through `ForgeEvents.read` (a fixture, a file log replay, a future cache) has no version check at all.
2. No test anywhere proves a v4 verdict is accepted by pr.ready, the SLO fold, the stall report or the train queue; `test_event_contracts.py:162-172` only validates the v4 payload schema.
3. `gate-contracts.gate_passed_version` describes "GX-09 sets 4". Under plan-v2 the producer switch is GX-10 (`gate_report.py` does not build the v4 fields yet; flipping the pin now would make every default emit fail validation). GX-09 leaves the pin at 3.
4. Fixtures: the plan-tick fixture `test_plan_tick.gate_passed` is v3-shaped; a v4 fixture needs `input_digest` (from `gate_digest.input_digest`), trees, `selection`, `cost`, `lane_id` and the v4 stage fields `cached`, `inputs_digest`.

## Not in scope (owners)

`train.py`/`test_train.py` (GX-30), contracts/lock/generated/EVENTS.md (GX-37), the producer (`gate_report.py`, GX-10/GX-39), `forge_events.py` readers (`apply`, `gate_slow`: shared port; GX-09 reads through them without editing them). Known base defects/env failures as listed in the brief (KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; claude-session/root-identity/config tests: GX-ENV).
