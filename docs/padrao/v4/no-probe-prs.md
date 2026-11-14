# No probe PRs (Daniel 23:36)

Never open a PR to measure, test or experiment. PRs are only real units of work. Measure locally: a throwaway worktree off your own head with the minimal diff, then run the gate (gate-dev on the local diff/ref); record the numbers in your PR comment. Delete the worktree after.
