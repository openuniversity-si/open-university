# BODY-GATE — the body learns the same date lesson the plan already knows

## Why this unit exists

The rule that asks for the cheapest useful effort has two homes: the unit's plan and the PR body. The plan was
taught to judge by the date a plan was created; the body was not, and on 28/10 that one missing lesson stopped
all twenty open pull requests at `pr metadata`, each with nineteen stages green.

## Steps

- [ ] 1. `scripts/lib/commit_check.py`: the PR payload carries `created_at` from the pull request it already reads (no extra call).
- [ ] 2. `scripts/lib/effort.py`: `body_grandfathered` and `body_errors(base, created)` — a body born before the rule is exempt; a body that carries a block is judged however old it is; an unreadable date or a checkout without the registry judges as before.
- [ ] 3. `scripts/lib/structure.py`: the `pr metadata` stage passes the merge base and the birth date.
- [ ] 4. Tests in `scripts/tests/test_structure_effort.py`, and the two mutations that prove they bite.
- [ ] 5. Retro, with the descent recorded.

## Cheapest useful effort
Action: the `pr metadata` stage judging a real PR body against GitHub REST.
Cost: 15 minutes wall, one gate-dev run.
Requirement: Daniel needs the twenty open PRs to be judged by the rules that existed when they were written.
Cheaper rejected: rewriting twenty PR bodies by hand (costlier and it teaches the gate nothing).
