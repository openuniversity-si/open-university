# TX30 retro

## Result
- sync.test.ts: sparse files plus a private dir removed in `afterEach`. absolute-literals.test.ts: scope root removed in `afterEach` (try/finally dropped).
- Assertion counts (`expect(` per file): sync.test.ts 41 before / 41 after; absolute-literals.test.ts 36 / 36. Tests 26 / 26 passing.
- Tmpdir after one run: 8 dirs, 1,402,892 bytes on base; 0 dirs, 0 bytes after.
- Timeouts, thresholds: `git diff origin/mod/roadmap-integration...HEAD | grep -nE '^[+-].*(timeout|_s"|_ms"|threshold)'` prints no line.
- Lane: the diff touches only tooling-lane files plus docs/units/TX30.

## Measurement under load (4 cores, `yes > /dev/null` x4, 5 runs each)
- Before: sync.test.ts file 129-204 ms, "enforces MEDIA_BYTE_BUDGETS" 13-21 ms; absolute-literals.test.ts file 45-88 ms.
- After: sync.test.ts file 154-207 ms, same test 17-24 ms; absolute-literals.test.ts file 61-68 ms.
- This container does not reproduce the 6.6 s the audit measured on the gate (fast local disk), so wall time shows no improvement here. What the change removes is the cause: about 2.6 MB of data writes per run (sparse files write none) and the leftovers. Not claimed: a wall-time gain.

## Brief quality
Good file and line cites; two went stale (code moved to a package, absolute-literals already clean). No cause for absolute-literals beyond the 14 mkdir+write was found; the brief's claim that it times out for tmpfile reasons is unproven on this base.

## Premises
Held: no seam needed, sparse size equals asserted size.

## Failures
None. Gate runs: see the MERGE-READY comment.

## Lessons
- Brief cites should carry a package path, not a file path, once code moves into `@ou/*` packages (owner: TX program author).
- A load-reproducing helper in the repo would let units like this measure the claim; there is none (owner: tooling-lane).
