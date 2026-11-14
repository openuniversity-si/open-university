# GX-FIX-forge-rate — retro

1. **Brief.** The brief was precise about the incident path (record_durations → one comment per test) and the proxy's
   limits. Three things were missing or wrong. (a) It asked for an object-shaped route key in the registry, but object keys
   are reserved for locale text (`x-text`), so the key became the array `forge-events.file_kinds`. (b) It put the
   helper "under units/engine-events", but the limiter's only caller is `github_api.py` (engine-github), and
   engine-events already requires engine-github; an engine-events helper would have made a unit cycle, so it went into
   engine-github. (c) It did not list `gate_status.py` or `test_gate_status.py` among the files, yet the repost fix needed
   both: one line so live edits don't wait, and a test that encoded the repost defect as expected behaviour.
2. **Audit and plan.** The premise "gate-status reposts" held only in part. 74 of 75 sampled comments were one per new
   (sha, mode). The one real repost was a same-second create race (#695 a94be3e0, pinned + advisory run). A second repost
   class came from reading the code: any failed PATCH became a POST. The plan kept its 7 commits; only the key shape changed.
3. **Execution** (UTC). 21:33 branch, 21:34 PR refused (secondary limit), 21:41 audit + plan, 21:42 client, 21:48 batching,
   21:48 PR #718 opened (3rd attempt), 21:51 sticky gate-status, 21:52 guard, 21:53 docs, then the gate. Two failures:
   the config registry refused the object key (fixed by the array key, before the commit); a broad covers glob for the
   guard changed the selective-gate table (`test_gate_script_tests`), so it was reverted. Process slip: the 2nd PR attempt
   came 3 min after the 1st instead of ~10 (I misread the clock); it is recorded in STATUS.
4. **Gate.** Run 1 on 01f558ea (21:53 to 22:08 UTC, 884 s wall). Pinned verdict FAILED, advisory FAILED. Three code
   classes came from this PR. (a) CODEOWNERS drift: new engine-github manifest paths. (b) The LT1 literal census: number
   literals in forge_rate, github_api, forge_github, rest_fake and the new tests; the census scans tests too, and its
   list only shrinks. (c) structure-check, the same census. Root cause: I ran the targeted tests and the local push
   checks, but never `literals`, `structure-check` or `generate`. Those are the suites that guard any new engine file.
   All three were fixed in one commit (registry keys, `http.HTTPStatus`, a JSON fixture for the test values, regenerated
   CODEOWNERS). Then the base moved (GX-FIX-train-lock, #719), and I merged it with a merge commit: conflicts in
   forge_github imports, rest_fake dispatch and CODEOWNERS, both sides kept. Known base defects hit (KD ids on #712):
   gate-db, hermetic, invoker-tooling, merge-phase (`ModuleNotFoundError: forge_events` in the rest fake), plus
   rest-fake-ready under load. Run 2 is on the merged head; see MERGE-READY / STATUS.
5. **Lessons.**
   - The guard test reruns only when its covers change. A bypass added in an unrelated new file is caught by the nightly full
     battery, not by the selective gate. Fix: a gate-level "always run" list for guard tests (owner: GX gate-run unit).
   - A test that asserts a defect ("failed edit creates a new comment") hides a class. When a class fix changes such a
     test, the brief should say the contract changes (owner: brief template).
   - Briefs that name registry shapes should check the registry schema's rules (object = x-text) (owner: A Torre).
   - Any new engine file needs `literals`, `structure-check` and `generate` before the gate, along with the step's own
     tests. Fix: list these three in the brief template's targeted tests for engine units (owner: A Torre / brief template).
   - Follow-ups: per-role GitHub identities (torre-gate App); train.py per-PR emit loop (GX-30); lock writes on git-data
     (GX-FIX-train-lock).
