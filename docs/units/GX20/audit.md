# GX-20 audit

Base tip a698f542 (mod/roadmap-integration, GX-18 merged). Current behaviour of everything GX-20 changes. Cited sources verified on the base (brief standard v2 item 2); deviations from the brief are listed at the end.

## 1. The plan source has one diff: `base...head`
- `scripts/gate-local:376` calls `gate_hook plan` (no-op body, `scripts/lib/gate-hooks/plan.sh:5`), then `:380` runs `gate_policy.py classify --pr --sha --base --output $logs/db.json`; `:383` splits it into `$logs/plan.json` (devPlan) and `$logs/selection.json` and exports `GATE_PLAN_FILE`/`GATE_SELECTION_FILE`.
- `scripts/lib/gate_policy.py` `classify_pr` (`:94-108`) fetches base and head and classifies `changed_paths(root, base, head)` = `git diff --no-renames --name-only base...head` (`:83-88`) through `select_dev_plan` → `gate_areas.plan_for`. There is no notion of an earlier proof: a RETRO commit after a green head re-plans the whole PR diff (F-01, F-06).
- `gate_want` (`scripts/lib/gate-runner.sh:150-160`) runs a dev stage only when it is in `plan.json` `stages`; a stage not in the plan is simply not run.
- The prerequisite stages (secret scans, workflows, **structure check**, generated drift, schema compat) are launched at `gate-local:362-369`, before the plan hook, on every run: they always execute on the new head (GA-P01, D-B6). No carry can skip them.

## 2. The docs area (GX-18)
- `scripts/lib/gate-areas.json` area `docs`: paths `docs/**`, `**/*.md`, `**/*.txt`, `**/*.rst`, `groups: []`, `coveredGroups: ["script-tests"]`; `always` = the six prerequisite stages.
- `gate_areas.AreaMap.areas_for` (`gate_areas.py:317-322`): a documentation path maps only to `docs`. `plan_for` (`:430-488`) adds `coveredGroups` when `ScriptTestCovers.covers(path)` (`:356-374`, fail closed: unreadable covers count as covered). So `plan_for(docs paths)` is exactly "always-stages + script tests when covers meet", and `gate_script_tests.select(GATE_PLAN_FILE)` then picks only the covering tests (`gate-local:324-356`).
- `event-contracts` covers `docs/process/EVENTS.md` (`scripts/tests/covers/event-contracts.json`); `lessons` covers `docs/units/*/retro.md`.

## 3. The v4 proof (GX-10, GX-37) and `carried_from`
- `gate-hooks/proof.sh` (GX-10, before the plan hook) exports `OU_GATE_PROOF` = `gate_proof.bind(...)`: `sha, plan, head_tree, base_sha, base_tree, gate_version, toolchain_id, selection_digest, input_digest, lane_id, ...` (`gate_proof.py:146-160`). The plan hook therefore already knows the current base, toolchain and gate version.
- `gate_proof.proof_payload` (`gate_proof.py:233-242`) copies a fixed key list from the binding plus `selection`/`cost`; **no field is taken from the run for `carried_from`**. The contracts already allow `carried_from {event_id, sha, delta_files[]}` (`contracts/events/gate.passed.v4.json:164-185`, same in gate.failed.v4).
- `gate_proof.proof_stages` (`:220-230`) marks a stage `cached` from its `<stage>.stage.json` (`cached` key); `gate_report.stage_results` reads every `*.stage.json` in logs (`gate_report.py:17-21`).
- `gate_carry.py` is the GX-39 stub: `carried(logs) -> []`; **nothing calls it** (`git grep gate_carry` finds only CODEOWNERS and `units/engine-gate-report/unit.json`).
- Earlier proofs live in the PR's event log: `ForgeEvents.read(repo, pr)` → `gate_verdicts.accepted` → `forge_events.replay` (`forge_events.py:459-486`) keeps per head and plan only `{verdict, event_id, at}`, so a carry needs the raw verdict events (payload with `base_sha`, `toolchain_id`, `gate_version`, `stages`).

## 4. Coverage and the verdict
- `gate_report.expected_stages` (`gate_report.py:24-37`): a dev run with a scoped/full `plan.json` expects exactly the plan's stages (∩ dev + script tests). `apply_coverage` (`:144-167`) fails on an expected stage without PASS. Stages present but not expected (e.g. carried records) are reported, not judged.

## 5. pr.ready (`scripts/lib/pr_ready.py`)
- `ready_after_gate` (`:111-141`) emits when the plan is ticked by the commits of `base..sha` and `emit_ready` (`:72-79`) finds a `gate.passed` for that exact head and plan (`forge_events.gate_evidence`). A carried verdict is a `gate.passed` on the new head, so it already counts; there is **no check that a carried proof's delta is what the commits after its source changed**, and no rule naming the plan items satisfied by a carry (GX-21's rule, moved here by D-B7).

## 6. Pinned gate
- Under GX-05 the tooling of a `--pr` run is the base tip (`gate-hooks/pin.sh`). The carry therefore takes effect only for runs whose tooling contains it, i.e. after this unit merges; this unit's own RETRO commit is gated by base-tip tooling (no carry). Measured locally with this branch as tooling instead (no probe PR).

## 7. Deviations from the brief (decided, reversible)
- **Registry key names.** `config.check` (`scripts/lib/config.py:510-514`) refuses a key that does not start with its file owner, so `gate.carry_over_enabled` cannot live in `gate-carry.json` (and `gate.json` belongs to GX-16 #731). Keys: `gate-carry.carry_over_enabled` (true) and `gate-carry.carry_over_areas` (["docs"]).
- **`carried_from` in the event.** The proof builder (`gate_proof.py`, GX-28 #738) has no seam that reads the run; GX-20 may not edit it. GX-20 writes the carry record to `$logs/carry.json` and exposes `gate_carry.carried_from(logs)`; the proof builder needs one line in `proof_payload` (`payload.update(gate_carry.fields(logs))`). Until that seam lands, carried stages appear in the v4 verdict as passed `cached` stages with 0 ms and the record is in the run logs; recorded in the PR.

## Known base defects/env failures (not this unit)
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env: claude-session, root-identity, config tests (GX-ENV); TMPDIR flake class (GX-ENV).
