# GX-FIX-train-lock — retro

1. **Brief.** It was clear on the goal and the probes. Three premises were wrong:
   - It assumed a ref could be deleted ("delete it again right after", "the ref is gone afterwards"), but the proxy refuses every delete (REST and git). Three probe refs remain and need a person to remove them.
   - It named `scripts/lib/gate-script-tests.json`, which does not exist. Per-test covers live in `scripts/tests/covers/<name>.json`.
   - It offered force-with-lease for renewals, but the repo's own pre-push `no_history_rewrite` refuses any rewind. Fast-forward-only is the only design that fits both the proxy and the repo policy.
2. **Audit and plan.** The measured premise held: `refs/heads/*` create and fast-forward work over git, with no per-session name limit. A surprise changed the design: release cannot be a delete, so it became a fast-forward to an empty lease end. The plan otherwise did not change. Commit 5 (docs) did not depend on 3–4. It ran serially anyway, because the commits were small enough that fan-out cost more than it saved.
3. **Execution** (UTC, 27/10):
   - 21:13 launch; probes until 21:16.
   - 21:16 audit (48fb52d3); 21:18 plan (e58fad75).
   - 21:32 helper (62b529f6); 21:36 adapter and tests (b7efb170); 21:37 docs (830f0b67).
   - 21:52 PR #719; then the gate.
   - **Wait:** opening the PR hit GitHub's secondary content-creation rate limit (HTTP 403 from GitHub, not the proxy) from 21:17 to about 21:50. Every retry restarted the window. The MCP path gave the same answer ("retry after 30m").
   - **Failure 1 (class: a subprocess reads inherited stdin):** `git mktree` in a test waited on the caller's stdin under `scripts/run`, which hung for 10 minutes. Fixed in the test helper and in the library: `input=''` always.
   - **Failure 2 (class: literals, LT1):** structure-check refused new numeric literals. They were replaced instead of growing the baseline. The baseline now only shrinks (the 404 and 422 left `forge_github`).
   - **Dead end:** a git stash used to isolate commit 3 conflicted with the staged files. Nothing was lost.
4. **Gate.** See the PR comment "MERGE-READY" / STATUS for the one run of record (pinned verdict and head advisory).
5. **Lessons.**
   - (a) Brief template (A Torre): name the proxy's delete refusal and the repo's no-rewind policy up front. Never ask for "delete the probe ref". Have the session reuse one probe ref name and advance it.
   - (b) Shared helper (engine-events): every subprocess helper should pass `input=''` (or `stdin=DEVNULL`) by default. A guard like `NoRestGitDataWrite` could also flag `subprocess.run` without input in engine modules.
   - (c) Covers (GX-FIX owners of `covers/train-role.json` and `covers/forge-events.json`): add `scripts/lib/forge_git_ref.py`, which both suites now import. This unit was not allowed to edit those files.
   - (d) Rate limit (GX-FIX-forge-rate, #718): probes that POST content (comments) count toward GitHub's content-creation limit. Probe with requests that fail validation before creation, and keep the PR creation call first, as the coordinator asked.
