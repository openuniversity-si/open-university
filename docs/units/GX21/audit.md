# GX-21 audit (base da1ac7f5)

## Plan completeness today
- `scripts/lib/plan_tick.py:35` `ticked_by(messages)` ticks every item named by a `Plan: N` trailer; it reads only
  commit messages, so an `--allow-empty` commit carrying `Plan: N` ticks the item. `commit_messages` (`:48`) drops the file lists.
- `scripts/lib/pr_ready.py:84-90` `plan_gap` builds `items not ticked by a commit: …`; `:236` prints the refusal. It runs only
  when someone runs `pr-ready`, never in the gate. The workaround people used: an empty commit with `Plan: N` (#615).
- `scripts/lib/structure.py:462+` `main` is the `pr metadata` stage (`structure-check --pr N` / `--pr-body`). It runs
  `commit_check.plan_errors(body)` (`:526`, only the 3-8 item count) and `commit_check.check(pr)` (`:556`); nothing checks
  that every item is ticked.
- `commit_check.fetch` (`commit_check.py:203-250`) already returns each commit with `files` (first-parent diff,
  `local_files` `:164`), so an empty commit is `files == []` and a merge of the base shows the base delta only.

## Lane decidability today
- `pr_ready.lane_of` (`pr_ready.py:38`) -> `train_ownership.UnitOwnership.lane_of` (`train_ownership.py:26`) returns
  `None` for "no unit" (legitimate: docs-only) and also for "several lanes" (the only undecidable case; the train refuses it
  later). The gate never evaluates it. `units.py` has no lane decision.

## GX-20 carry
- `gate_carry.py` carries *stages* of a proof by delta; it never touches plan ticks. No carry code is reimplemented; a
  carried head still has real commits with files, so the tick rule below is unaffected.

## Design
- `plan_tick.ticked_by_commits(commits)`: commits are `{message, files}`; a commit with `files == []` ticks nothing; a commit
  whose files are only `docs/units/*/retro.md` ticks only items whose text contains `RETRO`. `files` absent -> counted (fail open
  for callers that have no file list: `ticked_by(messages)` unchanged).
- `structure.plan_completeness_errors(body, commits)` and `structure.lane_errors(root, base, files)` run in `main` for `--pr`.
