# GX-14 plan (mirrored in the PR description)

Decision: D-070 (D-025 unchanged; only its subject is fixed to the gated sha). Premises: P-02 github source of truth (high: the PR's pushes, comments and compare still come from GitHub; only file names and the commit list of the gated sha come from the local checkout, which is that same sha), P-46 (GA-PG1, the verdict is about the pinned/gated checkout). No CRITICAL premise: no scope, money, production or source-of-truth change.

## Commits (sequential; one writer per file)
1. `docs/units/GX14/audit.md` (Plan: 1)
2. `docs/units/GX14/plan.md` (Plan: 2)
3. Comments judged up to the gated push (Plan: 3): `decision_wait.before(comments, cutoff)`; `commit_check.check` keeps only comments created at or before the gated head's push (`pr.gated.pushed_at`, else the push whose `after` is the gated sha); bodies and timed dicts both accepted. Files: `scripts/lib/decision_wait.py`, `scripts/lib/commit_check.py`, `scripts/tests/test_commit_check.py`. Test: `scripts/run test commit-check`.
4. Fetch on the gated sha, REST cut (Plan: 4): `commit_check.fetch(number, sha=None, root=None)`: compare `base...<gated>`, one PR commits page cut at the gated sha (local `git rev-list` when it is not on the page), file names from local git (one `git log` for every commit, one `git diff --name-only <merge base> <gated>`), timed comments; `commit-check --sha`. A fake transport counts the calls on a 12-commit PR (19 → 6) and proves a push during the gate leaves the verdict unchanged. Files: `scripts/lib/commit_check.py`, `scripts/tests/test_commit_check.py`. Test: `scripts/run test commit-check`.
5. Structure check passes the gated sha (Plan: 5): `structure-check --pr` fetches with the checkout's HEAD when it is a commit of the PR (else the live head, as today), `--sha` overrides. Files: `scripts/lib/structure.py`, `scripts/tests/test_structure.py`. Test: `scripts/run test structure-check`.
6. `docs/units/GX14/retro.md` (Plan: 6).

Graph: 1 → 2 → 3 → 4 → 5 → 6. 3 and 4 share `commit_check.py` (one writer); 5 needs 4's signature (real edge). Critical path ≈ 15 + 25 + 15 min of session time plus one gate pair. Sub-agents are not used: each step is one small file set and sequential by its edges.

Final gate: one `scripts/gate-dev --pr N` from a clean base-tip checkout (verdict of record, D-A3) and one from this checkout (report-only).
Known base defects: `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (GX-ENV).
Config keys: none new (paging reads `forge-events.github_page_size` / `github_max_pages`, already read by `github_api`).
