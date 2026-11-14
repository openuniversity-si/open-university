# GATE-TRAIN-SERVICES — retro

Stage 6 of the unit flow (D-077), written before the merge, over the whole unit: Daniel's brief (29/10 23:56 to 30/10
01:07 BRT), [intake](intake.md), [research](research.md), [audit](audit.md), [plan](plan.md) and the thirteen commits of
#814, from 30/10 01:18 to 03:40 BRT.

## 1. Brief and intake
- **The real problem held.** Every verdict and merge needed a live AI session; nothing in execution contradicted it.
  GATE-ON-PUSH had named this unit as its rung 3, and the audit found the same three roots it had left open.
- **What the brief got wrong or left out, found by evidence:**
  - "Execution plane: GitHub Actions hosted runners" could not be the plan: ADR-24 exists because the free minutes ran
    out on 14/10, and the audit's projection is 9–39 times the 2,000 free minutes (D-087). The research's "strictly
    better free option" (a vendor-neutral runner, Actions as one budgeted kind) replaced it, inside Daniel's own
    "unless your research finds a strictly better free option".
  - The brief did not know four platform walls: the pinned gate (P-46) judges a PR with its base's rules, so no rule
    this PR changes applies to its own heads; `workflow_dispatch`, `repository_dispatch` and `schedule` start only
    workflows on the default branch (`main`, frozen); the egress proxy refuses the Actions API and GraphQL and this
    session cannot resolve Cloudflare; `.claude/settings.json` forbids sessions to write `.github/workflows`.
  - "Gate green on every commit" contradicts D-022 (3–8 items) plus GX-21 (every listed item ticked) for the first two
    heads of any serial PR (D-083), and D-077 (each stage its own commit) contradicts the intake check for a new
    unit (D-084).
- **Lacunas, all decided and recorded:** Cloudflare access and the webhook identity became Daniel's steps (D-088); the
  owner's plan was assumed Free for the projection; Actions secrets: none needed until the optional install.

## 2. Research, audit and plan
- **The research changed the plan.** R1 went from "Actions runs everything" to A2 (a Tower runner on free compute) by
  the minutes math and ADR-24's history; R2 gained the git transport (zero REST, no deploy) so a runner works before
  any deploy; GitHub's merge queue was ruled out (organizations only).
- **Premises.** P-46 held and constrained: D-083 changes the rule for later PRs, never this one. P-18 held: the runner
  only ever runs `scripts/train run`, under the train's own lock. P-55 is no longer on the merge path once a runner
  runs. P-57 (event comments are never edited) was proposed, then validated by measurement: 176 of 176 event
  comments had `created_at == updated_at`.
- **How the plan changed during execution, and why:**
  - One extra commit (commit 8) repaired commit 7's comment cache (section 3).
  - The plan pre-assigned D-085–D-088; each was recorded at the next free number in order (the shared read became
    D-085, the architecture D-086, the projection D-087, Daniel's steps D-088).
  - The page-boundary cache of the plan could not see a deleted comment (a deletion shifts every later comment left);
    the `since` read plus a comment-count check replaced it.
  - The site lane's vitest guard (`no-github-actions.test.ts`) stayed untouched: editing it would make the PR cross
    lanes, which the structure check and the train's ownership rule refuse. Its amended version is staged beside the
    workflow and installed with it (D-088).
  - A `scripts/service job` command was dropped: the staged workflow calls `scripts/gate-dev` and `scripts/train run`
    directly.

## 3. Execution
Timeline (BRT; commit, gate, verdict event):

| # | Commit | What | Gate (BRT) | Verdict |
|---|---|---|---|---|
| 1 | `4cd47abe` | GX-23: one set of key parts per gate run; the self-host leg's whole output (D-082) | 01:31–01:43 | red, `gate.failed` `eb5afe471202` |
| 2 | `c3d9e107` | D-083 (a draft is judged on delivered items); D-082's premise | not gated (only red was possible) | — |
| 3 | `424c0d64` | base defects: `gate-isolation.test.sh`, `test_battery.py` | 01:45–01:51 | green, `0dca25f947a8` |
| 4 | `0dfb0766` | intake and research (D-084) | 01:53–01:58 | green, `9c3bc0bf8411` |
| 5 | `9a787682` | audit | 02:00–02:03 | green, `e3ef4fdfc3b0` |
| 6 | `65e24a82` | plan | 02:05–02:09 | green, `4df536cd4976` |
| 7 | `118cbd28` | one shared windowed read of #548 and its comment cache; `github_max_pages` 20 (D-085) | 02:18–02:29 | red, `gate.failed` `7be7a5405b45` |
| 8 | `89851d31` | the cache trusts itself only while the forge's comment count agrees | 02:31–02:39 | green, `a2ebfda68e2b` |
| 9 | `bd5d863b` | service contracts; `scripts/service` status, health and metrics; ADR-41 (D-086) | 02:40–02:49 | green, `dfdb543c9eae` |
| 10 | `a54755aa` | the Tower runner; pause, resume, requeue, cancel | 02:50–02:59 | green, `e892cbe3c15d` |
| 11 | `c5d2821f` | the control plane (Worker and Durable Object); the runner's control transport | 03:00–03:17 | green, `60c7ff89e903` |
| 12 | `c1e93ef2` | Actions as one optional runner kind; ADR-24 amended; D-087, D-088 | 03:17–03:32 | green, `131080bd0251` |
| 13 | this retro | RETRO (plan item 8) | after this file | in the PR body and the RETRO comment |

Failures, by root-cause class:
- **Contract (rules that contradict each other).** Gate 1: GX-21 refused the undelivered plan items while D-022 asks
  for 3–8 of them (D-083; the body lists delivered items from then on, the rest under "Next"); commit 2 was not gated
  because its only possible verdict was red. The intake check vs D-077's one-stage-per-commit (D-084).
- **Base defects (not this PR's code).** Gate 1: `gate-isolation.test.sh` pinned the slot counts from before #804;
  `test_battery.py` asserted the live shared store. Both fixed in commit 3.
- **Code (mine).** D-082 shipped without its `Premises:` line (gate 1). Commit 7's comment cache, keyed by channel only
  and placed above the REST client, was read by in-process stand-ins of the client in `gate-status` and
  `gate-forge-budget` (gate 7, red); commit 8 keys it by forge and trusts it only while GitHub's comment count agrees.
- **Local refusals before any push** (the pre-push checks and `structure-check`, minutes each): the literal census
  (a new unit may write no number but 0, 1 and -1, and `1 + 1` folds to 2; `parents[2]`, `[:12]`, `0o755`, durations in
  test strings), the hermetic-clock rule (`datetime.now` in a test), a registry key without `x-unit`, a dict key that
  spells a registered parameter (`train_enabled`), pipes inside a decision cell, two missing asset entries.
- **Dead ends.** The page-boundary cache (deletions are invisible to it). A `--once` smoke run of the runner, not
  allowed here because its first poll sweeps with `scripts/train run`; replaced by `--dry-run` and a live poll that
  found #814's head as one gate job with one REST read.
- **Waits.** Every gate of this PR runs twice (the pinned run, then the head's own tooling, report-only, because the PR
  touches the gate): about 100 (gates 1 to 12) minutes of gates in total, about two thirds of the wall clock spent waiting.
- **Quota.** The gates of commits 1 to 11 made 2,261 GitHub requests, 1,825 of them `304`s that cost no primary quota; this session's own calls were about 150 (PR body updates, the newest #548 pages, PR channels, the live status and window measurements). The token never fell below 14,600 of its 15,000 an hour; nothing waited on quota.

## 4. Gate
Eleven gate runs before this retro, each the pinned run on the base's tooling plus the advisory run of the head's own: nine green, two red (gate 1: the plan rule, D-082's premise and a base defect; gate 7: the comment cache), and commit 2 not gated. Base defects hit: `gate-isolation.test.sh` (stale since #804) and `test_battery.py` (the live shared store), both fixed in commit 3. Push to `gate.passed` on this PR: p50 126 s over eight green heads (46 s to 399 s; the 399 s head touched the contracts, so the web stages ran).

The pinned gate keeps reading 204–212 times per run on this PR: it is the base's tooling. With this PR's code a warm
windowed read of #548 is two conditional GETs (both `304` when nothing changed) instead of 21 pages, measured live at
02:59 BRT, so the same gate should make about 30 reads (target T5: 60) once the base carries it.

Every green head woke the train (`pr.ready` on a draft, audit finding 12): #814 sat in the train's queue as a draft,
and the forge refused its merge, which is harmless but wasted the train's time.

## 5. Lessons
| Problem | Change that would have prevented it | Owner |
|---|---|---|
| A process rule this PR fixes cannot judge this PR (the pin) | D-083 now lets a draft's verdict judge delivered items; the brief template should say rule changes apply from the next PR | structure owner (A Torre) |
| Intake and research must land together on a gated head | `unit_intake` should accept an intake-only folder until research is due (D-084) | engine-structure |
| A machine-wide cache above the faked boundary leaked into tests | caches live below the transport tests replace, or validate against the source (commit 8's count check) | engine-events, engine-github |
| A green draft wakes the train | `pr_ready` (or the train's queue) skips drafts | engine-train |
| The literal census gives a new unit a zero budget, unannounced | the brief template names it: derive numbers from the registry or from 1 | engine-census |
| The advisory run doubles every gate of a gate-touching PR | GS2 (#683) wall-time work; the advisory run could reuse the pinned run's content keys | engine-gate-run |
| `gate.passed.cost.wall_s` holds an epoch, not a duration (audit 7) | fix the field in `gate_report` | engine-gate-report |
| The brief prescribed hosted Actions without the 14/10 history | a brief that names a vendor cites its ADR and quota | A Torre |
