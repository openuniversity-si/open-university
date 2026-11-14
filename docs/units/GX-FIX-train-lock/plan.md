# GX-FIX-train-lock — plan

Brief: A Torre 18:1x BRT 27/10 on Daniel's order 18:08 (owner gx-train, D-070). Evidence: [audit.md](audit.md).

## Mechanism (from the measured table)

The proxy refuses every REST git-data write and every ref delete (REST and git); it permits creating and
fast-forwarding `refs/heads/*` over the git protocol, PR merge (`PUT pulls/<n>/merge`), issue comments and pulls.

- One shared helper, `scripts/lib/forge_git_ref.py`: a lock ref is read with `git fetch` and written only by
  `git push` of a lock commit built locally (`hash-object`, `mktree`, `commit-tree`). **Create** = push of a new ref
  (the server refuses it when the ref exists). **Advance** (renew, take-over, release) = push of a child of the sha read
  (the server refuses it when the ref moved: not a fast-forward of the new tip). No force, no lease override, no delete
  (the proxy refuses deletes; the pre-push `no_history_rewrite` refuses rewinds). The push result is read from
  `--porcelain` (a proxy-refused push can exit 0 with *Everything up-to-date*).
- **Release** is a fast-forward "released" lock commit (`expires: ""`), never a delete: an empty `expires` is below every
  `now`, so the next contender advances on top of it. Owner `train@<session id>`, lease and renewal before every batch and
  tier-2 run are unchanged (`engine_role.LockedRole`); the battery lock uses the same adapter.
- The train lock ref stays `train.lock_ref` (`train/lock`, under `refs/heads`, the only namespace the proxy permits); no
  new registry key. The proxy does not limit branch names per session (audit), so nothing session-specific is needed.
- Merge stays `PUT pulls/<n>/merge` with `sha` (merge commit, `--match-head-commit`, D-054 release policy): permitted.
- Refused and kept: `set_status` (GX-17, already non-fatal on 403; the status comment carries the verdict),
  `pr merge --delete-branch` (only `scripts/merge-phase`, production, frozen), `merge-phase:34` (frozen).
- Guard: a test fails when a train/gate module under `scripts/lib` names a REST git-data write path.

## Commits (dependency graph)

| # | Commit | Files | Depends on |
|---|---|---|---|
| 1 | audit | `docs/units/GX-FIX-train-lock/audit.md` | — |
| 2 | plan | `docs/units/GX-FIX-train-lock/plan.md` | 1 |
| 3 | helper + its tests | `scripts/lib/forge_git_ref.py`, `scripts/tests/test_forge_git_ref.py`, `scripts/tests/forge-git-ref.test.sh`, `units/engine-events/unit.json`, `scripts/lib/gate-script-tests.json` (own entry) | 2 |
| 4 | adapter on the helper + fake forge refusing git-data writes + guard | `scripts/lib/forge_github.py`, `scripts/tests/test_train_role.py`, `scripts/tests/rest_fake.py`, `scripts/tests/test_forge_events.py` | 3 (real: imports the helper) |
| 5 | docs | `docs/operations/train.md` | 2 only (parallel with 3-4) |
| 6 | retro | `docs/units/GX-FIX-train-lock/retro.md` | gate |

Critical path 1 → 2 → 3 → 4 → gate → 6 ≈ 45 min plus gate wall time. 5 is a separate file set, so it never waits on 3-4.
`train.py`, `engine_role.py`, `train.json` (GX-30) are not touched.

## Premises
- Measured, CRITICAL to scope: the proxy permits create and fast-forward of `refs/heads/*` over git and refuses deletes
  (audit). If it starts refusing pushes to `train/*`, the lock fails loud (GitRefError), never silently.
- P-42: the work runs in cloud sessions (low radius here).

## Tests
- 3: `python3 scripts/tests/test_forge_git_ref.py` (local bare repo: create, create race, stale advance, two contenders).
- 4: `scripts/run test train-role`, `scripts/run test train`, `scripts/run test forge-events`, `scripts/run test forge-git-ref`.
- One final `scripts/gate-dev --pr <n>` (pinned verdict + head advisory).

## Known base defects (owner GX-ENV)
`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (`RegistryMemo.test_a_rewritten_file_is_read_again`),
in cloud containers the uid-65534 fs-encoding crash.
