# TRAIN-VERDICT-FIX: audit (why the train merges nothing alone today)

Read-only analysis of 29/10 15:45 BRT on `mod/roadmap-integration` @ `80839a23` and #802 @ `9830863a`. Decision:
D-075 (the train resyncs a requeued PR itself). Premises: P-53, P-43, P-46.

Method: for each of the 21 ready (non-draft) PRs, the tip merged into the head in a throwaway clone, then
`scripts/generate --check`, `schema-compat`, `structure-check` and `structure-check --metadata --no-publish` (no unit,
integration or e2e run).

## Blockers in the code

- **B1. The resync does not regenerate generated files.** `train_verdict.resync` calls `train_git.combine`, which only
  runs `git merge-tree`. In 9 of the 15 PRs that merge clean (#659, #643, #641, #649, #645, #635, #633, #626, #625,
  #620) the merged tree leaves `apps/web/tsconfig.paths.json` stale: `gate-verdict --cold` would go red on
  `generated drift` and eject the PR. After `scripts/generate addresses` the drift is gone and structure/schema report
  0 errors; the full `scripts/generate` broke in the test, so only the generators the check names may run. #774
  conflicts only in `.github/CODEOWNERS`, which is generated: regeneration resolves it.
- **B2. No bootstrap.** The train resyncs only a PR whose head has a live `pr.ready`. None of the 21 ready PRs does:
  every head is 56 to 603 commits behind the tip and its last gate is `gate.failed` (or the head already left the
  queue, #772, #774, #663). The queue stays empty and `scripts/train run` does nothing.
- **B3. `gate-verdict` drops the cause of a red metadata stage.** `live_red` returns `[stage, class]` and discards the
  `FAIL` lines (`gate_verdict.py` ~l.352), so `pr.ejected` says only `red pr metadata: code`.
- **B4. An UNOBSERVABLE or `env` re-verdict halts the train.** No minimal fix: run preflight before the train.

## Expected effect

With B1 and B2, about 10 PRs enter alone (4 need only B2); #774 also needs the generated-conflict part of B1. Six stop
on metadata (undecidable lane, #615's plan) and four on real textual conflicts; those go back to their owners.

#649's lane is undecidable because `scripts/lib/generated/config_registry_text.py` (engine-config) and
`apps/web/src/generated/text/text.json` (site-text) are generated outputs touched by many PRs but not declared
`shared`.
