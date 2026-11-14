# GX-34 retro

PR #704, branch `claude/gx34-sharded-tier2-design-42tm99`, base `mod/roadmap-integration` (4bc4dd04 at launch,
2e862f22 after GX-42 #703 and GX-14 #702 merged; merged in by a merge commit). Times are UTC on 27/10 (BRT = UTC−3).
This file is committed before the verdict run, so that run judges the exact final head. The verdict numbers are in the
PR's RETRO and MERGE-READY comments.

## 1. Brief

- **Branch name conflict.** The brief names `mod/gx34`, but the cloud harness assigns `claude/gx34-…` and refuses any
  other branch. I used the harness branch and recorded that in the first PR comment. Lesson: the coordinator's launch
  should name the branch the harness will assign, or the harness should take the brief's branch.
  → coordinator (launch template).
- **"GA2 open Q7" was ambiguous.** GA2 has a Q7 (API budget) and an open question 7 (adaptive batch); plan.md:732
  settles it. A brief should cite `file:line`, not a label that exists twice. → plan author (GX-42 `program.v1`).
- **"Disjoint units" vs lanes.** The brief says units, but the engine's ownership refusal and the audits talk about
  lanes. I simulated lanes first and added units afterwards (§5 of the design shows both). Nothing was lost, but the
  simulation was rerun twice, ≈ 10 min.
- **The "merge log" holds no tier-2 outcomes.** The train was off on 27/10, so no red batch was ever recorded. The red
  rate and the streak shape are therefore swept parameters, not data. The brief could have said so up front.
- **"Files: that doc only"** conflicts with the conventions' audit/plan/retro files. I followed the conventions
  (`docs/units/GX34/`). The simulator went into a Markdown file so that no `.py` file enters the engine scans.

## 2. Audit and plan

- Premises: P-27 held as the frame. P-14 (3 %) agrees with GA2's three ejections in 71 PRs (≈ 4 %); I swept it to
  10 % anyway. P-15 (240 s) vs GA2 Q1 (614 s cold) differ 2.5×, so both are reported. P-23 (units split when hot) turned
  out to be the premise that decides between the designs: L scales only through it.
- Findings that changed the design. A dependents-wide key (`requires`, transitively) costs L most of its gain on
  today's mix (44 → 33 PRs/h), so the recommendation names contract-only dependents as the C3 lever. Hand-edited
  shared files, not generated aggregates, are the ceiling at k = 16.
- Plan changes: none to the commit list. Two variants (dependents, by unit) were added to the simulator inside commits
  4 and 5. That is why `simulation.md` changed in three commits (3, 4, 5), each time with its source and output in step.

## 3. Execution timeline (commit times, UTC)

| Time | Step |
|---|---|
| ≈ 18:00 | launch; read brief, plan-v2 §4/§5.2, GA2 G-09/B-21/open Q7, `train.py`, `train_ownership.py`, train registry |
| 18:24 | commit 1 audit (pushed with a wrong `Claude-Session` trailer copied from GX-01's log; not rewritten, noted in the PR) |
| 18:25 | draft PR #704 opened, STATUS comment; commit 2 plan |
| 18:29 | commit 3 simulation (71 merges, B0/B1/L/S/adaptive; ≈ 25 s per full run) |
| 18:31 | commit 4 design part 1 + dependents key |
| 18:34 | commit 5 design part 2 + by-unit key |
| 18:35 | base 2e862f22 merged in (merge commit) |

Failures and rework: one extraction crash (a squash-merge subject `(#616)` broke the PR-number parse; fixed in the
parser, class: subject formats, checked against all 71 subjects). One modelling bug caught before any number was
used: bisection time was counted twice for L (once in the executor's end time, once in `resolve`). Fixed with a
`timed` flag; L's numbers come only from the fixed run. No sub-agents: one doc, one writer. A fan-out would only have
added hand-offs.

Where time went (≈ 50 min of session time before the gate): reading ≈ 15 min, simulator ≈ 15 min, writing ≈ 20 min.

## 4. Gate

The verdict of record is one `scripts/gate-dev --pr 704` from a clean checkout of the base tip (D-A3), plus one run in
this checkout (report-only), both on the head that carries this file. Numbers are in the RETRO comment. Known base
defects expected: `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (RegistryMemo), and the
uid-65534 fs-encoding crash (GX-ENV).

## 5. Lessons

| Problem | Change that prevents it | Owner |
|---|---|---|
| Brief branch ≠ harness branch | the launch names the harness-assigned branch, or the harness takes the brief's | coordinator |
| Label cited twice (Q7) | briefs cite `file:line` for every audit item | plan author / GX-42 |
| No recorded tier-2 outcomes to replay | turn on SH-1's shadow events as soon as GX-30 merges, so C3 replays real red rates | SH-1 (engine-train) |
| A docs unit needs runnable code without becoming code | a sanctioned place for analysis scripts outside the engine scans (e.g. `docs/units/<unit>/*.md` blocks, as here) written into the conventions | structure owner |
