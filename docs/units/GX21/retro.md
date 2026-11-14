# GX-21 retro

## Brief
Clear. Two gaps: "lane undecidable" was not an existing error anywhere (`train_ownership.lane_of` returns None for both
"no unit" and "several lanes"), so the unit defined it as: files touching units of more than one lane. "Respect GX-20's carried
proof" had nothing to do: carry-over acts on stages, never on plan ticks.

## Audit and plan
Premises held: `commit_check.fetch` already gives per-commit first-parent file lists, so no new git plumbing was needed.
pr_ready.py stayed untouched.

## Execution
- Push refused three times by the literal census (LT1): small item numbers in my tests and code counted as engine values.
  Root class: fixtures with hard-coded small integers. Fix: derive numbers from named constants. The fix-up commits were
  squashed locally before any push (no pushed history rewritten).
- Push refused once for an undeclared unit import (`engine-train` in engine-structure requires): declared, it is this change's own dependency.
- The new rule applies to this PR itself: an unticked RETRO item would turn its own gate red, so retro.md was committed before the gate.

## Gate
See the PR comment RETRO for the gate numbers.

## Lessons
- Brief template: the commit plan's RETRO item must be committed before the gate, since GX-21 checks it (owner: A Torre).
- LT1 census: an exemption for plan-item numbers in test fixtures would avoid constant gymnastics (owner: engine-literals).
