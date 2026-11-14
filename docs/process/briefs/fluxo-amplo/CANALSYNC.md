# CANALSYNC: the branch sync is one command and the hand merge of the base is refused at push (BRANCH-SYNC)

- Owner: lane-1, model claude-opus-5-5, wave 1
- Depends on: CANALTRIGGER
- Source: `docs/programs/fluxo-amplo/plan.md`

## Done criteria

- [ ] scripts/lane-ship --sync covers a clean branch, a local commit, a conflict and a branch already in sync
- [ ] commit-check --local refuses a merge of the base with git default message
