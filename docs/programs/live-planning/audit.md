# Live planning — audit (LP1)

Status: final (LP1, 27/10/2026, branch `mod/lp1`).

Unit LP1, audit + design only (ordered by Daniel 15:02 BRT 27/10/2026). Base `mod/roadmap-integration` at `4bc4dd04`, read at
the start of LP1. Evidence is quoted as `file:line` on that base, as a PR number, or as a commit. Nothing was run except
reads; no PR, no event, no comment. The gate audits are not repeated here; they are cited as
[audit-1-fable.md](../gate-excellence/audit-1-fable.md) (GA1) and [audit-2-opus.md](../gate-excellence/audit-2-opus.md) (GA2).

**Verdict in one line.** The engine has every input a live planner needs (events, gate classes, lessons, premises, defects,
retros) and one pure function that reads the plan on every call (`scripts/lib/coordinator.py:59`), but **no path from new
information back into a plan or into the next launch**: a plan changes only when a person or a session edits `plan.md` by
hand, and the only scheduled re-plan points are the four fixed checkpoints written into the gate-excellence plan.

## 1. How plans are made today

| Step | Where | What it is |
|---|---|---|
| Program folder | `docs/programs/<p>/{brief,audit,plan,retro}.md` (`docs/programs/_template/`) | Brief → audit → plan → retro, each a file. `scripts/program check` requires all four. |
| The plan as data | one fenced `json program.v1` block in `plan.md` (`docs/programs/_template/plan.md:6-19`, contract `contracts/programs/program.v1.json`) | Units with `id`, `depends_on`, `owner`, `model`, `wave`, `done`, optional `area`, `pr`. Status is never written; it is folded from events (`scripts/lib/program.py:124-149`). |
| The plan as prose | the rest of `plan.md` | gate-excellence: 836 lines, 37 units, 4 waves, decisions D-A1…D-A16, slot schedule §4.3, checkpoints C1–C4 (`docs/programs/gate-excellence/plan.md:675-682`). |
| Who writes it | one planning session (GA3 for gate-excellence, `plan.md:3`), once | "Status: final … ready to execute as written in step 4" (`plan.md:3`). A revision is a new session and a new file (`plan-v2.md` on `origin/mod/ga4`, §3 below). |
| Unit plans | `docs/units/<U>/plan.md`, PR body `## Plan` | Padrão v1 `audit-and-plan.md`: "If the plan changes, edit the PR description and say so in one comment." That is the only plan-change rule in the standard, and it is per PR, not per program. |
| Roadmap | `docs/process/roadmap/STEP-0N-{audit,plan}.md`, `STATUS.md` (one hand-written row per PR, `STATUS.md:1-8`), `STRUCTURAL-PLAN.md` (static prose, D-013) | Hand-maintained. |

## 2. How plans are executed today

- **Coordinator** (`scripts/coordinator` → `scripts/lib/coordinator.py`). `next(state, events, limit)` (`:59-91`) is pure: it
  folds the program's events into unit stages and returns actions `launch`, `enqueue`, `open_fix_unit`, `mark_blocked`,
  `escalate`. It re-reads `plan.md` on every call (`:155`), so **a changed plan is picked up at the next call with no extra
  machinery**: the plan is already the coordinator's only input. What decides is fixed: wave order, then id
  (`:84`), bounded by `max_sessions`, `launch_rate_max`, `retry_budget` (`config/registry/coordinator.json:126-168`). It
  never reorders, inserts, re-splits or cancels.
- **Quota is blind**: `quota_remaining_percent` is always `None` (`coordinator.py:135`), so the quota headroom rule (`:82-83`)
  never applies.
- **Actions that only print**: `escalate` and `mark_blocked` go to `notify` (stderr) (`coordinator.py:112-114`,
  `coordinator_launch.py:122-123`); `enqueue` is "reported, not written" (`coordinator.py:117`).
- **Inputs that never arrive**: the fold needs `pr.opened`, `session.failed`, `session.ended`; no code under `scripts/`
  emits them (only documented, `docs/process/EVENTS.md:30-82`). So the `open`/`failed` stages, and therefore `escalate` and
  `mark_blocked`, cannot fire on real logs.
- **Launch** (`scripts/lib/coordinator_launch.py:86-103`): the brief is the unit row + Padrão v1 + *applied* lessons for the
  unit's area + open defects; the Claude adapter runs `claude --remote <brief>` (`config/registry/coordinator.json:264-269`,
  `scripts/lib/adapters/launcher_claude.py:16-29`). The box-side launcher, its `v3/LAUNCH-HOLD` file and
  `/workspace/torre/motor/sessions.log` live **outside the repo** (`scripts/lib/adapters/launcher.py:3`; zero matches for
  `LAUNCH-HOLD` in the repo; `/workspace` does not exist in this cloud container, as GA1 `audit-1-fable.md:413` and GA2
  `audit-2-opus.md:455` already found). The hold is therefore a binary stop, not a plan: it says "nothing launches", never
  "launch X instead of Y".
- **In practice** gate-excellence launches were made by A Torre by hand from the slot schedule (`plan.md:600-626`, protocol
  `:669`), not by `scripts/coordinator run --apply`.
- **Merge**: the train (`scripts/lib/train.py`) is off unless `train.enabled`; until checkpoint C1 the coordinator merges
  (D-070, `plan.md` D-A11).

## 3. Where new information surfaces, and where it is lost

| Information | Where it surfaces | Machine-readable? | Who reads it | Does it reach a plan or a launch? |
|---|---|---|---|---|
| Gate failure class (code / env / contract, D-027) | stdout machine line (`scripts/lib/gate_classify.py:6-7`), `class` in the `gate.failed` payload (`scripts/lib/gate_report.py:66`), PR status comment | yes | the PR's own session | **No.** No `env.drift` is emitted; `stall-report` flags `red_gate` only when run by hand (`scripts/lib/stall_report.py:1-14`). An env failure on one PR is invisible to the next launch. |
| RETRO lessons | `docs/units/<U>/retro.md` §5, RETRO PR comment | after `scripts/lessons ingest` | `program-gate retro` aggregates them at program **end** (`scripts/lib/program_gate.py:85-130`) | **No.** All 16 lesson records are `status: proposed` (`docs/process/lessons/*.yml`); briefs include only `applied` lessons (`config/registry/lessons.json:547-550`, `scripts/lib/lessons_brief.py:24-29`), so no lesson reaches any brief today. `lessons.reported` says "the top class is the next engine fix" (`EVENTS.md:64`) and nothing acts on it. |
| Premise refuted / confirmed | `scripts/premises answer` | printed only (`scripts/lib/premises.py:272-274,346`) | nobody | **No.** EVENTS.md promises "every dependent plan and PR goes to review" (`EVENTS.md:108`) but re-judging waits for the port (`:110-114`). |
| Base moved (a merge) | `pr.merged`, `integration.advanced` | yes | the train halts (`train.py:265-267`); each open PR discovers it when its gate says "behind" | **No.** Each unit merges the base separately (the MERGE LOOP rule); nobody asks whether the merged change makes another unit smaller, larger or obsolete. |
| Open defect | `docs/process/defects/*.yml` | yes | coordinator `open_fix_unit` → `defect_router` (`scripts/lib/defect_router.py:1-15`) | **Partly** — the only dynamic planning that exists: a fix unit is created, but outside `plan.md` (`coordinator.py:65-66`), so the program graph never learns that its units now wait on it. |
| Estimate overrun | none recorded; plan rule "a unit over 2× its effort estimate stops … and the coordinator re-plans that unit" (`gate-excellence/plan.md:673`) | no | nobody | **No event exists for it**; there is no start time per unit to compare against except `work.assigned`. |
| Session stall | `scripts/stall-report --emit` → `engine.session.stalled` | yes, if run | nobody subscribes | No. |
| Things outside the repo | `sessions.log`, `v3/night-plan.md`, `known-defects.json`, `queue-lanes.md` under `/workspace/torre/motor` (GA1 `:413`, GA2 `:455`) | unknown | A Torre | Only through A Torre's memory. Not versioned, not readable from a cloud session. |

**The pattern.** Information is produced in five registries (events, lessons, premises, defects, retros) and two
off-repo files, consumed only by the session that produced it, and folded back into a plan only at program end (the program
retro) or when a human starts a new planning session. The re-plan points are written in advance (C1–C4, `plan.md:675-682`)
and keyed to wave completion, not to what is learned.

## 4. Cases from the last two days

Times UTC, 27/10 unless marked (BRT = UTC−3). Sources: unit retros under `docs/units/`, merge commits, PR comments on
`openuniversity-si/open-university` (read-only), `origin/mod/ga4:docs/programs/gate-excellence/plan-v2.md`. Counted over 25–27/10: 112 gate
status comments on 25 PRs; 84 base-merge commits on 27 PRs (362 merges of the base into 178 unit branches in git history);
9 distinct environment causes, every one recorded on its PR as class `code` or "not known base defect" even where the
author argued env or load.

| # | Learned (where, when) | Also hit | Should have changed | What happened | Cost |
|---|---|---|---|---|---|
| L1 | **Base-tip verdict vs new registry keys.** Under D-A3 the head's script tests run with the base's `config` module pre-imported, so a key added by the PR is "not a registered parameter". #677 17:27; `docs/units/GX01/retro.md:46` ("every GX unit that adds a key … hits this"); `docs/units/HD1/retro.md:36-42` | GX-01 #694 17:34, HD1/GX-07 #677 17:27, in parallel | `gate-excellence/plan.md` §3.1 (every unit adds keys), the GX brief, GX-05's scope; a 15-minute **preparation unit** before the next launches | Fixed twice, differently (own-root `config.get` in `e94e8a21`; child `config.py get` in `1b58c223`). §3.1 unchanged; plan-v2 does not mention it. | 1 red verdict each (GX-01 397.6 s); every later key-adding unit (most of waves 0–1) still exposed |
| L2 | **`gate-db.test.sh` red on the base** (hand-picked lib copy lacks `gate_select`). Named 07:03 (`docs/units/engine-test-support/retro.md:8-10`), fixed 14:06 in #677 (`7bf7e830`) | GX-01 #694 17:32 re-fixed it (`GX01/retro.md:36`: "not in the known-defect registry") | Route to one owner and land first, or register as a known defect | Two fixes, one merge conflict (`c87c9fd1` 17:50: "kept HD1's whole-lib copy"); HD1's fix sat unmerged 3.5 h | 7/22 base tests red ≈ 10 h; duplicate work + conflict |
| L3 | **Literal census only in the gate** (`structure_fast` misses it). GA1 `audit-1-fable.md:231`, GA2 `audit-2-opus.md:40` (F-15) already knew | #683 13:48, #671 14:07, #690 14:07, #669 14:16, GX-00 #692 16:57, GX-04 #693 17:23, GX-01 #694 17:34 | Pull F-15's local check (planned in GX-15, wave 1) ahead of wave 0 as a prep unit, or one line in the brief | Every RETRO repeats the lesson (690, 693, 694) and names the push-guard owner; `config/registry/local-checks.json` unchanged since 06:54 | GX-04 red run 53.7 s, GX-01 red run 397.6 s + a second fix round, ≈ 7 sessions' investigation |
| L4 | **"Merge as is" was false** for GX-07 (HD1 #677, 0.5 h in `plan.md` §5): a code fix and 4 base merges were needed (`HD1/retro.md:35-44`) | — | GX-07's scope and estimate; whether it should still run in slot S2 | Plan not updated; plan-v2 records only "merged" | 4 base merges (14:09, 17:25, 17:31, 17:50), 9 gate status comments, 1 red verdict |
| L5 | **Env failures not routed.** `root-identity.test.sh` "No module named 'encodings'" in a `/tmp/claude-0` worktree (#692 16:58; `HD1/retro.md:43-44`: same on an untouched base tip); `config.StoreError` "missing GH_TOKEN" classed **code** (#677 17:40) | #677 ×3, #694 17:42/17:46 | Register as env defects; add the string to `gate_classify.ENV`; pause launches that would hit it or prepare the container first | Coordinator ruled "env-only, separate unit GX-ENV-root-identity" (#694 17:49) — the right instinct, done by hand, recorded in a PR comment only; no defect record (`docs/process/defects/` holds two unrelated records) | Every later base-tip verdict in that container hits it; #694 and #677 merged with their last head gate red on it (17:46, 17:52) |
| L6 | **Load-sensitive psql timeouts** (`claude-session.test.sh`, `gate-heavy-db.test.sh`, `test-db.test.sh`) | 6–12 PRs each, 07:09–14:16 | Pull the load fix (BD1 #667, then GX-03) forward; lower parallelism until then | BD1 #667 paused; GX-03 planned in slot S3 | Dozens of red stages read as "not known base defect" |
| L7 | **Train ejects on env** (#690 14:16, missing local Postgres). Fix `eaa408de` pushed 14:20, one minute after #690 merged; not on the base (GA1 already reported it) | any train run on that box | Land `eaa408de` alone and first (plan-v2 does fold it into GX-02, but GX-02 has not run) | Still not on the base | Every train run before GX-02 can eject green PRs |
| L8 | **Scope churn by message.** TR2 #690 scope cut 4 times in 15 minutes by coordinator messages; 8 → 6 items, remainder to TR2b/TR3 (TR3 does not exist) | — | One recorded re-plan with its reason, applied at a commit boundary | Each cut "came after work for the previous scope had started" (#690 RETRO) | Rework inside #690; orphaned TR3 scope |
| L9 | **Launches against a stale plan.** GX-02, GX-03, GX-05 launched 14:55 BRT while the plan was being redone, halted 14:57 (`plan-v2.md:5`); GX-07 ran in slot S2 although planned for S4; a hold at 10:30 BRT reached #653 after it merged (13:26 UTC) | — | Launch reads one live plan; a hold is a plan state with a reason | Three wasted launches; slot schedule no longer matches reality; nothing records why | Launch quota and coordinator attention |
| L10 | **A re-plan that is a new static plan.** plan-v2 (`origin/mod/ga4`, `d9f996b7` 17:50 → `6651cd4a` 18:05) rewrites the graph for Daniel's 14:19/14:44/14:59/15:01 rules; 6 of 9 sections still pending | — | Fold L1–L7 in; be applied incrementally | Its only inputs are `plan.md` and the two audits (`plan-v2.md:3`); `rg` finds none of L1–L5 in it. It adds GX-41 "dynamic-planning coordinator" (`plan-v2.md:17`) — the same need as this unit | A full re-plan session per change; unit lessons still lost |
| L11 | **Counter-example (works when someone acts).** `countries.test.ts` red on the base hit 14 PRs 07:33–08:22; KF2 #657 fixed it at 11:22; the PRs merged the base and went green from 11:24 (#615 11:34) | 14 PRs | — | One fix, then all recovered | ≈ 3 h of 14 PRs red before the fix — a coordinator would have fixed first and launched after |
| L12 | **Branch-name mismatch**: briefs say `mod/<unit>`, the harness binds `claude/...` (≥ 10 PRs; #692 RETRO: "launcher should set the branch from the brief") | ≥ 10 PRs | Launcher/brief fix once | Each session resolves it alone (this one too) | minutes per session, two naming schemes on the remote |

`git log -- docs/programs/` after `5c9fa5d3` (16:54, GX-00 imported `plan.md`) shows only LP1's own commits: the base plan was
not touched while GX-00 (17:13), GX-04 (17:30), GX-01 (17:48) and GX-07 (17:54) merged, and the program `retro.md` is an
empty template until program end.

## 5. Root causes (classes)

1. **No owner of the question.** Every case was *seen* — usually in a RETRO with an explicit "→ owner" line — and nobody's job
   was to ask "does this change the plan?". Unit sessions correctly stay in scope (fix what is theirs, pass the rest on), so
   the passed-on part lands in a file nobody reads until program end (L1, L2, L3, L5, L7).
2. **Plan = document, not state.** The plan is a long prose file plus one JSON block, written once, with re-plan points fixed in
   advance (C1–C4). Changing it means a new planning session and a new file (L10). There is no small, versioned
   "change" unit with context and intention, so changes are either huge (plan-v2) or invisible (PR-comment rulings, L5, L8).
3. **Inputs exist but are not wired.** Gate classes, lessons, premises and defects are machine-readable, but: env failures are
   mis-classed and never become `env.drift`; lessons stay `proposed` (0 of 16 applied) so none reaches a brief; premise events
   are printed, not published; three fold events have no producer. The coordinator cannot react to what it never receives.
4. **Launch is decoupled from the plan.** The box launcher and its hold are off-repo and binary; manual launches follow a
   slot table that already disagrees with reality (L9). A hold says "stop", never "do this first".
5. **No preparation step between waves.** Cross-cutting blockers found by the first units (L1, L3, L5, L6) are left for each
   later unit to rediscover, which is exactly the "prepare before every fan-out" rule (Daniel 14:51) applied at program level —
   nothing in the engine performs it.
6. **Re-planning by message causes churn** (L8): when the plan does move today it moves by chat to a running session, mid-work,
   with no record and no regard for the session's sunk work. A live planner must move the *plan* and leave running work alone
   unless the reuse-vs-redo judgment says otherwise.
