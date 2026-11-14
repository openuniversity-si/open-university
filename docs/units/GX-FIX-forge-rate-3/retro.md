# GX-FIX-forge-rate-3 — retro

1. **Brief.** It was clear. "Why the selective gate did not run gate-db" had a more precise answer: it did run, and its failure was adjudicated as known defect KD-335a14a4.
2. **Root cause class.** #718 moved a kind off the forge, and a test kept reading the forge's raw store instead of the port. #720's gate and #718's gate missed it because a known hermetic crash in the same test file masked the assertion.
3. **Execution** (23:56-00:02Z, 4 commits). One literal-census refusal: an extra `7` in gate-db. It was fixed before push by asserting on the file log directly.
4. **Gate.** One run on the final head; the results are in the PR STATUS and RETRO comments.
5. **Lessons.**
   - (a) A change that moves a kind's storage must grep the tests for raw reads of the old store. The guard now does this. Owner: engine-events.
   - (b) A known-defect match must not hide later checks of the same test. Owner: defects (KD1). The proposal is in audit.md.
   - (c) Env-scoped outputs (count files, record roots) need an owner check, not per-test scrubbing. This was done for the forge count.
   - (d) In #720 I wrote "the failures are known base defects" without checking what the known signature covered. Reading the matched signature against the head's own tail would have shown the masking.
