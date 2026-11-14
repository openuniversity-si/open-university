# FP1 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/FP1/audit.md`).
2. Plan (this file).
3. `force_push` refusal: `commit_check.fetch` also reads the head ref's `force_push` activity; `force_push_errors` refuses each one, naming its time, before/after SHAs and `scripts/replay-branch <pr>` (a new branch) as the remedy; fixtures for the refusal and the allowed case.
4. Rebased-branch refusal: `fetch` reads `compare/<base>...<head>` (`behind_by`, merge base); `rebase_errors` refuses a head behind its base without a merge commit of the base (a PR commit whose non-first parent is the merge base), naming `git merge <remote>/<base>`; fixtures: behind without merge (refused), behind with a base merge, up to date (allowed), unknown compare (not judged).
5. Local class fix: `no_history_rewrite` in `config/registry/local-checks.json` and `local_checks.py`: the pre-push check refuses a push whose remote sha is not an ancestor of the pushed sha (a force push after a rebase or amend); tests for refused and allowed pushes.
6. Docs (`docs/operations/local-gate.md`, the commit-check docstrings), retro (`docs/units/FP1/retro.md`) after the gate.

## Dependency graph and owned files
`1 -> 2 -> 3 -> 4`; `5` depends only on 2 (disjoint files) and could run beside 3-4; `6` last. The change is small (two functions and one handler), so the coordinator writes it in sequence: sub-agents would cost more context than they save. One writer of the branch, one push per commit (X1 post-commit hook).

| Commit | Files owned |
|---|---|
| 3 | `scripts/lib/commit_check.py`, `scripts/tests/test_commit_check.py` |
| 4 | `scripts/lib/commit_check.py`, `scripts/tests/test_commit_check.py` (after 3) |
| 5 | `scripts/lib/local_checks.py`, `config/registry/local-checks.json`, `scripts/tests/test_local_checks.py`, generated config types if any |
| 6 | `docs/operations/local-gate.md`, `docs/units/FP1/retro.md` |

## Premises and blast radius
Premises: P-41 (registry; no literal, no new tunable is needed: the rules read the PR's base from the forge and the remote from `push-guard.remote`).
- (high) GitHub's `/activity` lists `force_push` events for the head ref (documented `activity_type`). If wrong: rule 1 sees nothing (no false refusal); the local check (5) still stops the push before it leaves.
- (high) `compare/<base>...<head>` returns `behind_by` and `merge_base_commit`. If missing: the rule is not judged (never a false refusal).
- (medium) Every PR in flight that rebased or force-pushed is refused by the next gate; the remedy (`scripts/replay-branch`) exists. A branch merely behind its base without any base merge is refused until it merges the base, which the brief already requires before gating.
- CRITICAL: none (no production, money or source of truth). Branch protection would cost a plan upgrade (money): not taken.

## Targeted tests, then one final gate
3, 4: `scripts/tests/commit-check.test.sh`. 5: `python3 scripts/tests/test_local_checks.py`, `scripts/structure-check` (config_check). Then one `gate-dev --pr <n>`.

## Known base defects expected
None known for these paths (`scripts/lessons for-area` returns none); any other red stage is compared against the base before acting.
