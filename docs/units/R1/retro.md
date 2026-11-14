# R1 — retro

Whole unit, from the coordinator's launch (14:45 BRT, 01/11) to the execution PR. Times are BRT.

## 1. Brief and intake
- The brief was enough to start: "the train refuses a merge on a red base" with two done criteria. Missing: the brief did not say what a red result is for a tip with no result, nor who clears a hold. Intake said both (Lacunas, Regras). Intake's real problem held through the work: RC-005 was the incident it was written from.
- The brief named lane-2 as owner; the shadow publisher is in engine-gate-verdict (lane 11) and the loop in engine-flow (lane 1). Found in the audit, not the intake: the audit's R2 fix had to be split across lanes (plan.md, R2 A1 and its follow-up).

## 2. Research, audit and plan
- Research changed the plan: the reference (a result per tip, read before admission) gave the shape of R2 (a shared per-tip record); the repo's own ref pattern (train/lock, train/wake) made the cheap form fit without an event kind.
- The audit's root causes held: a rule missing (R1, regra faltando) and a mechanism missing (R2, mecanismo faltando); the chains reach evidence in scripts/lib/train.py:439 and scripts/lib/train_loop.py:35.
- The plan missed one thing, found at revision 1: a hold never moves the base tip, so the repair PR is held too. The plan had no way out. Revision 1 added a release by name and a switch off by default. A later failure from the same cause would be a root the audit stopped short of: the audit named the hold but not its deadlock. Lesson 1 below.
- R2 is a remendo (A1: the train reads its own host's file) with a follow-up in lane 11, because the publisher is not ours to edit. The choice was forced by ownership, not by cost; the plan says so.

## 3. Execution
- Fail-first: the six base-hold tests errored with `'Train' object has no attribute 'base_held'` before the method existed.
- The registry key was not visible to the train until `scripts/generate` rebuilt `config/registry/train.json` (`ConfigError: train.base_hold is not a registered parameter`). Found by the first test run, fixed in the same commit.
- The push guard refused the code commit: `scripts/lib/train_base_gate.py is a production file of no unit`. The local commit check passed; only the pre-push check reads the unit manifest. Fixed by amending the unpushed commit to list the file in `units/engine-train/unit.json`.
- Timeline: plan revision 1 pushed; code commit refused, then pushed after the manifest fix; docs commit pushed; retro committed last.

## 4. Gate
- R1 docs PR #1031: one real-gate lap in the worktree failed in preflight, `env: missing toolchain: postgres` (the worktree has no `.toolchain`; only the main checkout has it). Rerun from the main checkout: PASSED in 57 s on `b86d0427`, merged by the train.
- The records PR #1029 passed in 59 s from the main checkout.
- Known defects hit: none new. KD-3ec4be1f (scripts/tests/config.test.sh) is the flake the operations doc names; not reproduced in this unit.

## 5. Lessons, each with its owner and a concrete change
1. A hold needs an exit, designed with the hold: a red tip that stops merges can be the tip that the fix must merge on. Change: the plan template asks for the release path of every gate that holds a merge. Owner: the padrão (padrao v8, plan rules), through the lane-2 unit that owns the train.
2. A new production file must be listed in its unit's manifest when it is created, not at the push. The commit check passes it; the pre-push check refuses it. Change: `scripts/commit-check --local` runs the unit-ownership check that the pre-push hook runs. Owner: the local checks (`config/registry/local-checks.json`), engine-push-guard (lane 5).
3. A new registry key is not readable until its owner's aggregate is generated. Change: `scripts/commit-check` names `scripts/generate` when a key file is new and the aggregate is stale. Owner: engine-config (lane 1).
4. A lap run from a worktree has no toolchain. Change: `scripts/lane-ship` refuses a worktree without `.toolchain` before the gate, with the checkout to run it from. Owner: engine-env (lane 4).
5. The shared per-tip result is the open follow-up (R2 A2): gate-shadow publishes `refs/heads/gate-base/<sha>`. Owner: engine-gate-verdict (lane 11). Until it merges, the hold covers only the hosts that run the shadow (docs/operations/train.md).
