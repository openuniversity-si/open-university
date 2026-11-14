# Cheapest useful effort (Daniel, Oct 28 13:55 and 14:00)

As there is cheaper useful intelligence, there is cheaper useful effort. Before the most expensive action of a plan, ask whether it has to happen at all, and for whom.

Incident (Oct 28): "think before acting" was followed and still bought half an hour of `apt-get install` to make WebKit run. The requirement was "the pr-mode gate is green", while the merge door runs `gate-local --dev`, which never touches WebKit: a satisfied requirement that nobody needed.

Every `docs/units/<unit>/plan.md` and every PR body carries a section `## Cheapest useful effort` with four lines, each non-empty and not a placeholder (none, n/a, -, tbd, todo, ?):
- `Action:` the most expensive action of the plan.
- `Cost:` its cost (minutes, quota, money).
- `Requirement:` who needs its result, naming an owner: a person (Daniel, A Torre), a role (the learner) or a unit lane (engine-lane), never a machine. "The gate is green", "the train merges", "the tests pass" is refused: a gate, a train or a test is not the one who needs it.
- `Cheaper rejected:` the cheaper path(s) considered and why each does not satisfy the requirement.

The gate: the `pr metadata` stage (`scripts/structure-check --metadata`, `scripts/lib/effort.py`) refuses a PR body without the block, with a missing, empty or placeholder field, or with a Requirement that names no owner. The `structure check` stage refuses a `docs/units/*/plan.md` the same way, unless the plan is older than the rule: a plan whose oldest commit predates `config/registry/effort.json` cannot carry the block, so its date grandfathers it, and a plan written after the rule is judged even when a change rewrites it and drops the block. `effort.plan_baseline` (`config/registry/effort.json`) remains for the plans that reach the rule through an older branch and only shrinks against the base: a new entry is refused, and a listed plan that gains the block must be removed from the list. The check makes the answers exist; it never judges whether the cost is worth paying. Every word, field and path it uses is in `config/registry/effort.json`. Decisions: D-069 items 4, 8, 9, D-065 (5); gate change under D-025.

Example:
```
## Cheapest useful effort
Action: install WebKit system libraries and run the 3-browser battery
Cost: 30 min of session time
Requirement: Daniel, before the release merge into main
Cheaper rejected: gate-local --dev only (never runs WebKit, so it cannot tell Daniel WebKit renders); gate-noite tonight (too late for this release)
```
