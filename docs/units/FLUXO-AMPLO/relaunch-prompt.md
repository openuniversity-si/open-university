# FLUXO-AMPLO — relaunch prompt

Self-contained. Paste it as the first message of a new session, then follow AGENTS.md and CLAUDE.md.

---
Repo openuniversity-si/open-university, base `origin/mod/roadmap-integration`. You continue the program FLUXO-AMPLO (padrão v8). Work
alone, ask no questions ("realize e depois comunique"), record decisions as the next free D-xxx in
`docs/domain/DECISIONS.md`, report in pt-BR, times in BRT.

**Goal (Daniel, 31/10 13:26 BRT).** Improve A Torre's whole flow of producing software. Main metric: counted
integrated commits per day, summed over lanes (D-137, `scripts/flow-metrics`). Guards in operations, never time windows.
Phases are 10x with a ladder 200 … 1,000 (Phase 1), 2,000 … 10,000 (Phase 2), and so on. Only a measured limit recorded
as a D-xxx stops the program.

**State (31/10 ~18:50 BRT, D-155).** Read first: `docs/programs/fluxo-amplo/` and `docs/units/FLUXO-AMPLO/`, decisions D-137 to D-155. The REGIME OF EXCEPTION is on (D-151): `gate.bypass` true in the shared store, so a PR's gate is green in seconds, marked `bypass=D-151`; the e2-micro runner is paused (service.paused true) and the train runs in the lane-1 session container (`scripts/train serve` from a clean checkout under `/var/tmp`, never `/tmp/<private dir>`); a PR integrates in about 1 min. `scripts/gate-shadow run` runs the REAL gate for measurement and prints BASE BROKEN when the base fails (it found D-153 and D-154). Two lanes are open (RC-002 trigger met: median 2.0 min per commit): lane 1 (flow-metrics, lane runbooks, runner, train) and lane 2 (`session_01N99RyPiqc4grGNxDFkJz3L`: the real gate under 10 s on the e2-micro, so the regime ends). Exit of the regime: the real gate on the e2-micro under 10 s; only then `scripts/config set gate.bypass false --actor <who> --reason <why>` and the VM is unpaused (watchman or Daniel). Measure the programme with `scripts/flow-metrics --rolling --cycles --durability 100`; F1.1's target is 200 counted commits in 24 h.

**Next step.** Keep the lane at its pace (about 11 commits per hour), PR plans filled to their 8 items, base merged in before the gate, no draft PRs. F1.2 (authoring per commit): the scaffold exists (D-146), `--admit` (D-144) runs before the gate. Close F1.1 with its `phase.v1` block and the answer to "did the goal improve or only the number".

**Rules that matter.** Follow every rule and evaluate it (D-138): a rule that hurts is challenged with a record in
`docs/process/rule-challenges/`, grades 1/2/3; never worked around. Branch: if the designated branch exists on the remote
and is stale (RC-001), push the HEAD to a new `claude/fluxo-amplo-v8-*` name; never force-push. Commit plan of 3–8 items in
every PR body, one push per commit, the trailers of STRUCTURE B5. No GitHub Actions, no secrets, free tiers, no
production changes, no measuring loops on the e2-micro, no REST polling.

**Environment setup (not secrets; run it in the shell first, then `scripts/cloud/preflight`).** The first session had none of
these IDs in its environment and lost time to it:
```bash
export OU_CREDENTIALS=network TOWER_NEON_PROJECT_ID=wispy-sun-55356617 TOWER_NEON_PRODUCTION_BRANCH=br-nameless-king-aw2s4pbh VERCEL_PROJECT_ID=prj_HJ0ueSZq4QBI0RYiNqDCxFux1ScO VERCEL_ORG_ID=team_feEmDZ0B5CZl98oD8mq8U4UC
```
`NEON_API_KEY` and `VERCEL_TOKEN` stay missing in preflight; the train does not need them.

**How a PR integrates.** There is no `scripts/ship-tail`. The train needs a `gate-dev` pass on the HEAD, every plan item
ticked by a `Plan: N` commit trailer, and `scripts/pr-ready --pr <n> --body <file>` (it emits `pr.ready`). Mark the PR ready
when the step closes. Stay serial (F1.1, F1.2) until Daniel decides RC-002.

**Lanes (D-176, 31/10 21:50 BRT).** Daniel lifted the cap on lanes (RC-004). You are lane N and own exclusively the units your
launch message names; never edit a unit another lane owns (if you need a change there, send the owner a message). Lane 1
keeps `engine-flow`, `engine-units`, `engine-config`, `engine-generate`; lane 2 `engine-train`; lane 3 `engine-gate-report`,
`engine-gate-run`, `engine-gate-plan`; lane 4 `engine-env`, `engine-events`, `engine-structure`. Lane 2 keeps the gate front, not the `engine-train` split, which is deferred (D-188). Lane 5 (D-184) `engine-push-guard`, `engine-merge-regenerate`, `engine-test-support`. Work: code, not prose (docsonly
guard 0.45 against 0.365): split the oversize units (`scripts/structure-check` WARN unit.oversize), narrow covers by what a
test reads (`scripts/covers-cost --since 2026-10-31`, D-173 to D-175), fix what `scripts/lane-status` shows. Each lap:
branch `claude/fluxo-amplo-v8-laneN-<topic>`, 3–8 commits with `Plan: N` trailers, `scripts/lane-ship --create TITLE
--body-file FILE --real`, wait for the container train, repeat. `scripts/lane-status` first and between laps: if it says BASE
BROKEN fix that first. Not yours to change: `gate.bypass`, `service.paused`, the VM runner, the channel. No money, nothing
that touches other people.
---
