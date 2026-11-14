# TRAIN-VERDICT-FIX: plan (mirrored in the PR description)

Decision: D-075. Findings: [audit.md](audit.md). Premises: P-53, P-43, P-46. Stacked on #802 (TRAIN-VERDICT), which
already has the 8-item limit.

## Commits

- [ ] 1. Unit record: this plan and the audit.
- [ ] 2. `gate-verdict`: a red stage's `FAIL` lines go into `reason` (B3); test.
- [ ] 3. Resync regenerates: after `combine`, `scripts/generate --check` in a worktree; on drift run only the named
  generators and rebuild the merge commit with that tree, one commit (B1); test.
- [ ] 4. Resync resolves a conflict only in generated files by regeneration (B1, #774); test.
- [ ] 5. Bootstrap: under verdict/requeue `run` resyncs the open PRs left behind the tip, `scripts/train queue` lists
  them (B2); test.
- [ ] 6. Units: the two generated outputs of #649 declared `shared`; test.
- [ ] 7. Docs: `docs/operations/train.md`, D-075 test cell.

Graph: `1 -> 2`, `1 -> 3 -> 4 -> 5 -> 7`, `1 -> 6`. One commit per push.

## Cheapest useful effort

Action: extend the resync of #802 in place (`train_verdict`, `train_git`) and add one queue source; no new event.
Cost: one gate run on the final head.
Requirement: Daniel wants the ready PRs behind the tip merged with no owner session working.
Cheaper rejected: asking each owner to merge the tip (refuted by Daniel 15:02, D-075); running the full
`scripts/generate` after every combine (it broke on the real tree).
