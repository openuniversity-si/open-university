# U4 factory-domain: retro

1. **Brief.** It asked to move files into `units/factory-domain/`; S1 (P-03) keeps units logical, so nothing moved. The branch name differed from the session's designated one; the designated one was used.
2. **Execution.** One finding: the contract entry must be a tracked file, so `unit-battery` was red until `index.ts` was staged. The audit, entry and manifest landed in the first commit, so the plan's item 1 covers them.
3. **Lessons.** The battery's contract step should say "untracked" instead of "not a file of the unit" (owner: engine-battery).
