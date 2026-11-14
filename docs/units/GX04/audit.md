# GX-04 audit (read-only, cheap evidence)

| Area | Evidence | Consequence |
|---|---|---|
| Base | `origin/mod/roadmap-integration` = 54e05d45 (GX-00 #692) at start; `mod/gx04` did not exist on the remote. | Branch created from the base tip. |
| Cited premise | `scripts/gate-local:168` exports `OU_SUBJECT_ROOT="$root"` (the detached worktree at the gated sha, or the source checkout in working-tree mode). Premise holds; no edit to `gate-local`. | The subject root is read from the environment. |
| The defect (G-03) | `pr_ready.ready_after_gate` runs `git rev-parse HEAD` in `root` and refuses when it differs from `sha` (`pr_ready.py:97-103`); `gate_report.ready_hook` passes `root or pr_ready.ROOT`, i.e. the tool checkout (`gate_report.py:169`). A gate run from a checkout not on the head therefore never emits `pr.ready`. | Decide from `sha` and the subject root, never the tool checkout's HEAD. |
| Plan ticks | `plan_tick.commit_messages(base, root)` logs `base..HEAD` with `base = plan-tick.base_ref`, a local remote-tracking ref (`pr_ready.py:92`, `plan_tick.py:44-50`). A stale `origin/...` ref counts base commits as the PR's, or misses a moved base. | Count over `baseRefOid..sha`, base read once from the forge port. |
| Recorded base | `ForgeEvents.change(repo, pr)` already returns `{'head','base','body'}`; the GitHub adapter fills `base` from `pull['base']['sha']` (`forge_github.py:125-130`). The `pull()` operation lacks the sha. | Use `change()`: no edit to `forge_github.py`. |
| lane_id | `lane_of(root, base, head)` takes the merge base of `base` and `head` (`pr_ready.py:36-44`); passing the recorded sha as `base` is enough. | No change to `train_ownership`. |
| Files owned by others | GX-01 owns `gate-local`, `gate_report.py`, `gate_classify.py`, `preflight.py`, `gate-runner.sh`. `ready_hook` passes `root=None` in the gate, so the fix lives in `pr_ready.py`. | `gate_report.py` untouched. |
| Callers | `scripts/pr-ready` (CLI, `pr_ready.main`), `gate_report.ready_hook`; tests `test_pr_ready.py` (run by `scripts/tests/plan-tick.test.sh`), `test_plan_tick.py`, `test_slo.py` import the modules. | Keep the `ready_after_gate` signature compatible; fixtures in `test_pr_ready.py` gain a recorded base. |
| Config | `plan-tick.base_ref` exists; no new key is needed. | Fallback to it, reported. |
| Hand-emitted `pr.ready` (Q10) | `scripts/pr-ready` is a CLI that emits from the local checkout HEAD and local base. | The CLI uses the same recorded-base and sha logic. |
