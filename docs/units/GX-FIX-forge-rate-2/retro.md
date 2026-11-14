# GX-FIX-forge-rate-2 — retro

1. **Brief.** It was good, and its hypothesis order was right (H1 first). It assumed the pinned run said "pinned to e7d8bfdb", but that claim came from GX-29's comment, not from gate output. The real gap was one level lower: `baseRefOid` is GitHub's `base.sha`, which lags the base tip. The ≤ 3 write bound conflicts with the panel contract (begin, pending status, final, final status). The bound is now 6 plus the throttled live edits, and stated as such.
2. **Audit and plan.** H1 held, in a refined form: a stale base from GitHub (live GETs showed #705 and #714 at `ebab9368` with the tip at `e7d8bfdb`), not a stale worktree. H3 was ruled out: the new code builds envelopes at once, and the evidence showed them serial. H2 is left with GX-29. The plan changed once: `progress.jsonl` moved to the follow-up because it needs a `gate_graph` hook outside the unit's files.
3. **Execution** (23:05-23:20Z, 11 pushed commits). `POST /pulls` was refused by the secondary limit at 23:06Z. I retried too early at 23:08Z, 2.5 min instead of 10, which was my error and is recorded in status.md. It passed at 23:19Z. The literal census flagged 4 literals (an index 2, `[:12]` slices, 201, a count 2) after commits 3-6 had been pushed. They were fixed in commit 6, so commits 3-5 alone are not census-clean. The structure check flagged my own new unit edge (gate_report → engine-github), which I declared.
4. **Gate.**
   - Run 1, on 6679de49, 23:19:42-23:22:31Z (169 s). `gate: pinned to e7d8bfdb…`, `gate: version f419f412…`. The pinned verdict is **PASSED**.
   - Stages: script tests 99.7 s, structure check 8.6 s, secret scans 4.0 s and 1.6 s, schema compat 0.6 s, drift 0.4 s.
   - The failures are the known base defects KD-335a14a4 (gate-db), KD-a3870679 (hermetic TimeoutTest) and KD-71c8e5fe (invoker-tooling: rest_fake readiness probe under the hermetic denial). All three are in the hermetic class GX-29 owns.
   - The advisory run with the head tooling is PASSED, with the same three known defects and `forge: 0 writes, 6 reads`.
   - I pushed this retro while run 1 was going, so run 2 re-gates the final head (see the PR STATUS).
5. **Lessons.**
   - (a) Any tool that needs "the base tip" must fetch the base REF, never trust a forge-reported sha. Owner: engine-gate (GX-05). Rule for the brief template: "a forge field naming a sha is a snapshot, not the tip".
   - (b) Run `literal_census.py` and `structure-check` before each push, not only `commit-check --local`. The local push guard does not run the census. Owner: LR1 (`local-checks.json`).
   - (c) Never push while your own gate runs: the gate judges the head it read at the start. Pushing mid-run costs one more gate.
   - (d) Count GitHub calls per run by default (done here), so the next leak shows up in the gate output instead of on #548.
