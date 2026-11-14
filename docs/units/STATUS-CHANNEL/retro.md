# STATUS-CHANNEL — retro

From Daniel's order (02/11 ~10:45 BRT, "Temos que corrigir o padrão do brief da sessão também") to the gate that passed
on head `c1317af9e` (2026-11-02 ~18:30Z), the head the train got.

## 1. Brief quality
- The first brief (local box session) had no step after the last commit. The session pushed all 8 commits by 14:24Z
  and stopped before the gate, `pr-ready` and leaving draft. A second brief (STATUS-CHANNEL-CLOSE, 15:26 BRT) was needed
  only to run three commands.
- The close brief contradicts itself: scope item 1 says "merge the base", and the 28/10 rule "never bring the base to
  fix a queue" says not to. It was settled by measurement, not by choice: 42 behind, and `merge.max_behind_base` is 20,
  so the train could not accept the head without the merge.
- The close brief names the branch `mod/status-channel`. The cloud harness named another one
  (`claude/pr-1082-status-channel-*`). The brief's branch won (one branch, one PR).

## 2. Audit and plan
- `Premises: none` held. The three roots (R1 AGENTS.md sentence, R2 EVENTS.md storage section, R3 no test) and A2
  for each held. The plan did not change in the close session.

## 3. Execution (timeline, commit times)
| When (UTC) | What |
|---|---|
| 14:01–14:24 | 8 plan commits plus 1 base merge (`5cb4a21f8`), box session |
| 14:24–18:2x | Idle: draft, no gate, no `pr.ready`. The branch fell 42 commits behind (#1083, #1084, #1085 and others) |
| 18:28 | Close session: base merge `c1317af9e`, 0 conflicts (the unit touches 2 shared files, both untouched on the base) |
| 18:29 | Suites by hand: event-contracts 28 OK, `units check` 48/0, `test_orphans` 0, `structure-check` 0 errors (26 base warnings) |
| 18:30 | `gate-dev --pr 1082`: PASSED, 8 stages, 4 script tests, `pr.ready` emitted, train woken |

No failures and no rework. Almost all the waiting was the ~4 h gap between the last commit and a session that would
run the gate.

## 4. Gate
- One run before this retro, and it passed. A second run is needed only because this retro commit moves the head.
  No known base defect was hit.

## 5. Lessons
- L1 (the ~4 h idle draft). A brief that ends at the last commit leaves the PR in draft. Change: the brief template's
  last step is always "gate, `pr-ready`, `gh pr ready`, `gate-wait`". Owner: brief template (coordinator).
- L2 (the merge rule that contradicts itself). Rule: merge the base only when `behind > merge.max_behind_base`, then
  re-gate. That is one number to compare, and it belongs in `scripts/gate-dev --explain`. Owner: engine (gate-dev).
- L3 (the retro moves the head). Committing the retro after the green gate always costs a second gate. Owner: the brief
  template. Allow the retro as the last plan item before the final gate, or accept a docs-only retro commit as a carried
  stage.

## 6. The step that should have descended
| Repeated work (AI today, identical tomorrow) | Should descend to | Cost this time | Owner |
|---|---|---|---|
| "Branch done, now gate + `pr-ready` + undraft + `gate-wait`" needed a whole new cloud session | Deterministic script: `scripts/service runner` gates a draft whose plan is fully ticked and undrafts it (or `pr-ready` runs `gh pr ready`) | One session launch, ~4 h of latency, ~10 turns | engine (runner / pr-ready) |
| "Is the head too far behind? Merge the base?" — the same decision as in #605/#607/#615 | Rule in the engine: `gate-dev --explain` prints `behind N > max M: merge base` | ~2 turns | engine (gate-dev) |
| Retro timeline from `git log` | Deterministic script: `scripts/plan retro-skeleton --pr N` fills section 3 from commits and diary | ~2 turns | engine (plan) |
