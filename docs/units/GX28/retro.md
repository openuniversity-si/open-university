# GX-28 retro

Unit: attestation in keys and proof. PR #738, branch `mod/gx28`, base `mod/roadmap-integration` (3cae824a at launch, a698f542 after one base merge). Times are the container clock (UTC).

## 1. Brief quality
- Clear on ownership and acceptance. Gaps: (a) the brief names `gate_test_cache` as a test and "misses every cache" as acceptance, but forbids editing `gate_test_cache.py` (GX-11 #733), so the per-test cache cannot miss on a stale toolchain in this unit; recorded as a seam (`gate_test_cache.key` should append `*gate_keys.key_parts()`). (b) "Vercel CLI dependency tree pinned in toolchain.json" does not say how big that is: 387 packages, +4317 lines of JSON. (c) The harness assigned a `claude/...` branch while the brief named `mod/gx28`; the brief's explicit branch was used (BRIEF STANDARD v2 (1)).
- The contract description of `toolchain_id` in `contracts/events/gate.{passed,failed}.v4.json` still says `install_id()`; contracts are not this unit's files, so it stays (follow-up for the contracts owner: "attested toolchain_id, toolchain_manifest.attestation()").

## 2. Audit and plan
- Premise P-43 (attestation precedes tier-2 reuse) held: the recipe is published in the PR body for GX-31/GX-35.
- Audit finding that changed the design: version probes cost ~1 s warm and 10 s cold (python), and `key_parts()` runs per key, so the attestation memoizes per process (`gate_keys`) and on disk by binary identity (`.toolchain/attest.json`: realpath, size, mtime_ns, inode), never by `install.stamp`. Warm attestation: 0.09 s.
- Plan unchanged except item 6's shape (lockfile header stored with the packages, below).

## 3. Execution (timeline)
- 03:02 branch + skeleton + draft PR #738 + STATUS. 03:05 audit (21ed90c0). 03:07 plan (12299399).
- 03:09 item 3 c7132e12. First structure-check: literal scan refused `/bin/sh`, `0o755` and a count `2` in the new test → `shutil.which('sh')`, `stat.S_IXUSR`, compare probe lists. Class: test fixtures writing literals; the scan caught all three in one run, fixed in one pass before the commit.
- 03:11 item 4 3cc84d93. One test failure: `test_down_database_is_a_gap_and_without_skips_a_probe` relied on the stamp shortcut (empty fake binaries + one `return_value` probe). Class: every preflight test that fakes a healthy toolchain through the stamp; fixed all three occurrences with one helper `pinned_probe` in the same commit.
- 03:12 item 5 493a03ba (no failures).
- 03:16 item 6 618dadb0. Second literal-scan hit (`lockfileVersion: 3`, a registry URL in a test) → the lockfile header lives in the pin itself; the test derives the registry host from the CLI's own artifact URL. Real-environment proof: `npm ci` from the pinned lock into a scratch toolchain, 301 packages installed (other-platform optionals omitted), 0 drift, `vercel --version` 59.11.7. The live `.toolchain` already matched the pin (0 drift) and only rewrote its stamp. No Vercel API, deploy or promote command was run.
- 03:16 base merge db81a8ca (25 commits, no overlap with GX-28 files).
- Sub-agents: none. Items 3 → 4 → 5 were a real chain and 6 shared `toolchain_manifest.py`; spawning workers would have cost more than the ~15 min of serial work.

## 4. Gate
- Run 1, pinned `scripts/gate-dev --pr 738` on db81a8ca: **PASSED**, 7 stages, script tests 88/88 PASS (0 cached), 0 known defects hit, total 190.3 s (ceiling warning, report-only: script tests 148.2 s, cold test cache on a new head). Advisory head-tooling run: PASSED, 33.5 s.
- The pinned verdict binds with the base tip's tooling, so its `.pass` `toolchain_id` (6f04479f…) is still the old `install_id` recipe. The head's own bind on the same box gives the attested id 11d8254c… with `observed_versions` {python 3.12.15, node 22.23.3, pnpm 10.34.6, gh 2.102.0, gitleaks 8.30.1, vercel 59.11.7, postgres 18.6, chromium absent}. Chromium is `absent` because `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` holds revision 1243 and Playwright 1.64.0 pins 1248. That is the attestation doing its job.

## 5. Lessons
- Literal scan on test fixtures (hit twice, in two different files): run `scripts/structure-check` before every commit, not only before push. Owner: brief template (BRIEF STANDARD (4) already says "before each push"; make it "before each commit").
- A stamp shortcut hides behaviour from tests: three preflight tests passed only because the stamp short-circuited the probes. Prevention: fixtures fake the probe (`pinned_probe`), not the stamp. Owner: engine-env tests.
- Done means running: the attested id first reaches a verdict of record after this merges, because the pinned gate runs the base tip's tooling. To check after merge, on the next pinned gate: its `.pass` `toolchain_id` must equal `python3 -c 'import toolchain_manifest as m; print(m.attestation()["toolchain_id"])'` (from `scripts/lib`) on the same box, and its `gate.passed` v4 payload must carry `observed_versions`. Owner: coordinator, at the first post-merge gate.
- Seam: GX-11 should add `*gate_keys.key_parts()` to `gate_test_cache.key`, so the per-test cache also misses on a stale toolchain.
