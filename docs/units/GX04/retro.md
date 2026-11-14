# GX-04 retro: pr.ready from the gated sha and the recorded base

## 1. Brief quality
- Clear scope and acceptance. One gap: the brief says `plan-tick.base_ref` "stays the fallback" but the existing `base=` argument and `--base` flag also existed; they became the fallback too (decision recorded in the PR).
- The plan cites `pull()` for the forge read implicitly; `pull()` has no base sha, `change()` does. Found at audit, saved an edit to `forge_github.py` (outside the file list).
- `gate_report.py` (GX-01's file) is where the hook picks the tool root; the brief did not say so. Solved inside `pr_ready.py` (`subject_root`).

## 2. Audit and plan
- Held: `OU_SUBJECT_ROOT` is exported at `gate-local:168`; `change()` returns `base`; `lane_of` already takes the merge base of whatever base it gets.
- Plan unchanged: 5 items (audit, plan, recorded base, sha + subject root, retro), sequential because items 3 and 4 share two files.

## 3. Execution (UTC 27/10)
| Step | What | Note |
|---|---|---|
| 1 | audit.md, push | push-guard timed out once on the first push (`push_timeout_s`); the remote had the commit, the guard retried nothing needed |
| 2 | plan.md, draft PR #693 | |
| 3 | `plan_tick.commit_messages(head=)`, `pr_ready.recorded_base` + 6 tests | |
| 4 | `ready_after_gate` / `main` use sha + subject root + recorded base; 6 tests | |
| 5 | gate 1 failed on a bare `2` in my test | see below |
| 6 | literal removed, gate 2 passed | |
- Failure class: an engine test with a bare number (`..., 2)`), refused by the structure check (D-068, LT1). I had searched my diff for the same pattern after it failed: that was the only occurrence. `scripts/commit-check --local` (`no_registered_literals`) did not flag it before the push, so the gate discovered it.

## 4. Gate (verdict of record: `scripts/gate-dev --pr 693` from a clean checkout of base tip 54e05d45)
- Run 1, head 87be4180: FAIL structure check (the literal), 53.7 s.
- Run 2, head 31433baf: PASS, 26.2 s (all stages: workflows, generated drift, schema compat, both secret scans, structure check, script tests). No known base defect hit, no env abort.
- That run is also direct evidence of G-03: the base-tip tooling printed `pr.ready: not emitted (checkout HEAD 54e05d45 is not the gated head 31433baf)`, the behaviour this PR removes.

## 5. Lessons
| Problem | Change that would have prevented it | Owner |
|---|---|---|
| Literal in a test reached the gate | Make the `no_registered_literals` local check cover test files the same way the structure check does (one shared census) | gate / local-checks owner |
| Hook default passes the tool root | `gate_report.ready_hook` should pass `OU_SUBJECT_ROOT` itself; then `subject_root` drops its default-root special case | GX-01 (owner of gate_report.py) |
| `pull()` lacks the base sha | Add `base_sha` to `pull()` so one read serves the push guard and pr.ready | engine-events |
| Fallback visibility | The hook prints only "emitted"; surfacing the note in that line needs a hook change | GX-01 |
