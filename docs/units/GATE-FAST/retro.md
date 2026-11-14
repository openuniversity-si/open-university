# GATE-FAST: retro

Decision: D-076. Premises: P-56, P-43, P-53. Audit: [audit.md](audit.md). Plan: [plan.md](plan.md).

## 1. Before and after, same input, same container

Input: this PR's head `eba687c36aec` (commits 1-6) on the base tip `13ba2b0e25f1`: 34 changed paths in
`scripts/lib`, `config/registry`, `units`, `CODEOWNERS`, the tests and docs; 36 script tests cover them. One 4-vCPU
cloud container, one run at a time, every run cold (`OU_GATE_COLD=1`, fresh build cache). The `pr metadata` stage is
red in all three only because plan item 7 had no commit yet; every other stage ran to the end (GK1).

| Run | Tooling | Stores | Unit tests | Script tests | Stages done | Wall |
|---|---|---|---:|---:|---:|---:|
| A, before | base tip (pinned) | empty | 62 s (full: 1,790 tests) | 108 s | 145 s | 225 s |
| B, after, first cold verdict | this head (`OU_GATE_PINNED=off`) | empty | 12 s (11 reader tests) | 87 s | 121 s | 199 s |
| C, after, re-verdict (the train's resync) | this head | B's content-keyed stores | cached | 1.6 s (36 of 36 by content) | 35 s | **106 s** |

And the full battery of section 2 of the audit (PR #802's head, every stage, 109 script tests): 359 s.

- **The re-verdict, the train's real bottleneck, went from ~225 s to 106 s** on this input, and its stages from 145 s
  to 35 s: every unchanged test and stage is reused by its content key (P-56). It is what the train pays after each
  merge for every PR behind it, and what the verdicts ahead (commit 6) prepare in parallel.
- A first cold verdict saves the full web unit battery on every engine PR (62 s → 12 s here, ~130 s under load in the
  audit) and spreads the multi-file script tests over the free vCPUs (`config` 43 → 17 s, `structure-check` 68 → 33 s,
  `train` 30 → 19 s alone).
- Two verdicts now run at once on a 4-vCPU box (`slot 1 of 2`).

## 2. What is left (largest first)

1. **~60-80 s after the last stage** (C: 46 → 105 s): the report and evidence of a red run read GitHub 156 times
   against the 60-read bound of `github-client` (`forge: 3 writes, 156 reads`). This is now the largest slice of a
   re-verdict; the next unit should bound those reads (cache the PR's comments once per run) before anything else.
2. **~12-18 s before the first stage**: preflight, slot, pinned worktree.
3. **The first verdict of a large engine PR** is still bound by CPU on 4 vCPUs (~1,000 test-seconds for the full script
   suite). Only the shared store of D-073 (GX-35) lets one box reuse another box's PASS; until then content reuse
   works per box, which is the train's own box for its re-verdicts.
4. `cost.wall_s` and `cost.queue_wait_s` of the v4 proof are epoch seconds, not durations (audit, section 4.5).

## 3. Lessons

- A test helper named `test_*.py` under `scripts/lib` is read as a test by `test_orphans`; the runner is
  `parallel_tests.py`.
- The event contract `gate.passed.v4` is locked: a new payload field needs a v5. The train does not need one: a
  verdict whose `gate_version` is the tip's comes from tooling that keys every cached result by content.
- A test flaked once under the load of 36 tests at once (`gate-worktree-resources`: two e2e servers up together) and
  passed alone; it is the box, not this change, and the concurrency of two gates per box makes such contention more
  likely. Watch it in the ledger.
- The literal census counts numbers in tests too: derive them (`len(...)`, a registry value) instead of writing them.

## 4. Issue #548

The measurements above were also posted as one comment on issue #548, as Daniel asked. That issue is the event log of
the `forge_events` port and its body says nobody comments there by hand; the reader skips any comment that does not
start with the marker line (`forge_github`), so a plain comment cannot corrupt the log (blocking evaluation, D-072:
option (a), done as ordered, no record needed).
