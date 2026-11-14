# gate-speed — retro

Padrão v8 step 6 (D-115), over the whole program as resumed on 30/10 23:10 BRT: Daniel's brief (23:10), his
measurement rule (23:11) and "no wait, run the phases overnight" (23:14), the [avaliação](avaliacao.md),
[pesquisa](pesquisa.md), [diagnóstico](diagnostico.md), [solução](solucao.md) and the phases [F1](phases/F1.md),
[F2](phases/F2.md), [F3](phases/F3.md); PRs #828, #830, #831, #832. Updated after Daniel's 03:08 BRT order (D-122:
the program goes on to about 10 s) with [F4](phases/F4.md), [F5](phases/F5.md), [F6](phases/F6.md) and [F7](phases/F7.md); PRs
#833, #834, #835, #836. Closed on 31/10 14:30 BRT by Daniel's 13:26 order (D-136) after [F8](phases/F8.md)–[F11](phases/F11.md),
PRs #837–#845: the program went from 169.1 s to 0.99 s with the shared results and from about 170 s to 74 s with no
store at all; it did not reach the 10x per phase of D-132 or the 1 ms of D-134, and it resumes from section 7.

## 1. Brief and avaliação
- **The reframing held.** "Speed up the gate" became "the test-management system", and the diagnóstico measured
  coverage for the first time (89.12 %); the coverage guard then caught a real regression in F2 (89.31 %) that a
  speed-only program would have merged.
- **What the brief could not know, found by measuring:** the container signs every git commit (80 ms against 7 ms),
  the suite is bound by CPU and the CPU by processes (about 127,000 per cold run, 42,000 of them git), and the e2-micro
  runner cannot judge a PR whose selection is large inside its stage limits (1,200 s for the script tests, 300 s for
  the structure check).
- **The base moved under the program:** #827 merged between the diagnóstico and F1 (31 test functions of the retired
  product removed, D-113 and D-114 taken), so each phase compares with its own base, measured the same way.

## 2. Pesquisa, diagnóstico and solução
- The pesquisa's "preload once, fork per test" (Stripe, Django, pytest-xdist) was F4. Its ceiling was smaller than
  the retro's first estimate: about 900 Python processes a cold run (not 2,000), each saving 35–55 ms; 103.5 → 96.2 s.
  The estimate of "about 30 % of the CPU" came from a guess at the process count; F4's audit counted them first.
- The diagnóstico's first main-metric runs were taken in discovery order on a box with no durations; F2's committed
  cost hints made that order the system's, not the measurement's.
- **The 10x ladder was too steep for the first rung.** F1's premise (signing costs CPU) was refuted by its own
  measurement (it was waiting), so F1 stopped at 163.4 s and the ladder shifted one rung (D-118); F2 and F3 kept 60 s.

## 3. Execution
Timeline (BRT, 30–31/10):

| When | What | PR | Result |
|---|---|---|---|
| 23:13–23:46 | Padrão v8, the v8 check, avaliação, pesquisa, baseline (169.1 s, 89.12 %), solução, FASES PARA APROVAÇÃO | #828 | the runner's gates: BLOCKS by timeout (D-119) |
| 00:25–00:51 | renumbered after #827 (D-115–D-117), base merged, session gate | #828 | merged by the train 00:51 |
| 00:53–01:36 | F1: hermetic git, jobserver; 176.9 → 163.4 s | #830 | merged 01:36; stopped (D-118) |
| 01:41–02:23 | F2: fixture copies, hooks under test, in-process check, cost hints; 163.4 → 101.6 s | #831 | merged 02:23; stopped (D-120) |
| 02:30–03:15 | F3: the engine's own reads (structure check, config, train) and one tree listing per run; 104.2 → 95.8 s cold, warm 1.58 → 0.55 s | #832 | the program stops (D-121) |
| 03:08 | Daniel: the program goes on to about 10 s; fork server, then the train's git | — | D-122 |
| 03:13–05:35 | F4: profile (63,500 processes, 896 Python), fork server and native client, harness reads the registry once; 103.5 → 96.2 s | #833 | merged 05:34; stopped (D-123) |
| 05:35–06:24 | F5: the train's workspace answers about objects once, hermetic git through the environment; 100.9 → 94.9 s | #834 | merged 06:24; stopped (D-124) |
| 06:20–07:00 | F6: one process per test class of the longest files; inside the noise | #835 | not merged (D-125) |
| 07:00–07:55 | F7: the train fixture publishes refs without the transport; −6.9 % CPU on the train's tests (ABBA) | #836 | the cheap levers end at a measured floor (D-126) |
| 08:00–09:00 | F8 step 1: the train fixture's workspace without git's transport | #837 | merged 09:00 |
| 09:00–09:41 | F9: one node for every TS module, one walk per file in the vendor check | #838 | merged 09:41 |
| 09:41–09:59 | D-129: linear optimization exhausted (rewritten after Daniel rejected it as a stop) | #839 | merged 09:59 |
| 10:00–10:53 | F10: script test PASSes shared between boxes by input key (D-130); 95.7 → 0.69 s cold | #840 | merged 10:53; the uncached suite untouched (96.7 s) |
| 11:02–11:39 | D-132/D-133: 10x a phase, two main targets, the v8 panel, the unlock graph | #841, #842 | merged 11:14, 11:39 |
| 11:39–11:57 | F11 step 1: the train reaches git only through its workspace | #843 | merged 11:57 |
| 12:00–12:41 | F11 step 2: git in memory for the train's tests; uncached 92.6 → 77.1 s (ABBA) | #844 | merged 12:41 |
| 12:41–14:15 | D-134 (1 ms uncached, then the e2-micro); two attempts that gained nothing; D-135, the PR gate on the shared results; coverage back to 89.69 % | #845 | merged 14:15 |
| 14:15– | D-136: the closing, the e2-micro's real gates, the handover | this PR | — |

Failures, by root-cause class:
- **Contract (P-46):** a rule a PR adds cannot judge that PR: the pinned v7 check refused the new v8 program folder;
  thin adapter files carried it until the base ran v8 (D-117), and F1 deleted them.
- **Mechanism missing (decision numbers):** two sessions took D-114 the same hour; the register has no reservation.
  Renumbering cost a commit and a merge of the base.
- **Environment (e2-micro capacity):** the runner's gates of #828 ran past both stage limits and were labelled `code`
  without a test id; the same head passed in the session with the same pinned tools, so the session was the
  documented fallback runner (D-119) for every PR of the program.
- **Code (mine), caught before the gate:** literals the census refuses (numbers in tests, an environment name),
  production files with no unit (gitconfig, test_metrics, fixture_copy, costs.json), a CODEOWNERS left stale. Each was
  refused by `commit-check --local` or the pre-push hook, never by a gate.
- **Measurement (mine):** a registry regenerated while a measurement read it (two false failures), a worktree under a
  0700 directory (two uid-65534 tests failed), 29,000 untracked files in the main checkout's `apps/` (184 s instead of
  164 s), dirty worktrees in a warm comparison, and single samples when the cold CPU moves ±20 CPU-s between runs.
  From F2 on: clean worktrees at the exact head, nothing else running, interleaved samples.
- **Guard (worked as designed):** F2's first coverage pass fell to 89.31 %; the per-file absent lines named the
  pre-push edges the push guard had reached by accident, and the owning tests now judge them. F4's first two passes
  fell to 89.09 and 89.27 %: a fork restarted coverage inside a running frame (which a tracer started later never
  traces) and the preloaded `unittest` sent every fork down the harness's other path; the absent lines named both.
- **Contract (P-46), again:** F4's test used a UNIX socket, which the head's hermetic check accepts and the base's
  (the one that judges the PR) refused; the test moved to a socket pair. The advisory run (head tooling) caught a
  second, real fault the pinned run could not: a test that assumed every checkout has a `.toolchain`.
- **Measurement (the box):** the container's own speed moved ±15 % within an hour and ±40 % across two (the same
  base: 92.7–155.5 s cold); every comparison from F4 on is three interleaved pairs, and F6 was judged by them.
  `strace` made a busy-wait probe spin 11,545 times and never end: counts under tracing are not costs.

- **Measurement (cProfile), F11:** the profile ranked the registry's repeated scans first, and two attempts to remove
  them (a memo of the change store's replay, a frozen registry digest) gained nothing in three ABBA pairs; one was
  slower. cProfile weighs small, frequent calls far above their real cost, and a fork resets it. A profile is a map of
  where to look; the verdict is an A/B.
- **Mechanism missing, F10–F11:** the shared results (D-130) were read only by `scripts/test-suite`; the gate and the
  e2-micro's runner never read them, so the program's biggest gain did not reach the box where the gate runs. Found by
  reading the runner's own events (0 cache hits on #838–#844), fixed by D-135. A feature that changes who runs
  a test must be switched on where the tests run, and its first user is the runner.
- **Environment (e2-micro), still open:** the uid 0 probe (`test_root_identity`, run by `claude-session.test.sh` and
  `root-identity.test.sh`) failed on the VM three times in three PRs (#838 once, #845 twice) and passed on the same
  code in the container and on other VM runs; the runner's event keeps only the signature (`AssertionError: uid N probe
  failed (N)`), so the cause (most likely resource pressure on the e2-micro, unproven) needs the VM's own log. D-135
  avoids running the probe whenever another box already judged the key.

## 4. Gates
Every PR: two to four runner gates on intermediate heads (BLOCKS by timeout, or superseded) and one session gate on the
final head (pinned verdict PASSED, `pr.ready`), then the train. Session gates took 17–126 s of script tests against
1,200 s and more on the runner.

## 5. Results against the targets

Session container, 4 vCPUs, clean worktrees, ABBA or interleaved passes; the full panel is in the
[avaliação](avaliacao.md#painel-final-d-136-3110-1430-brt).

| Metric | Diagnóstico (`c770ba2e`) | After F5 | After F10 | After F11 | |
|---|---|---|---|---|---|
| `cold_wall_s`, against the shared results | 169.1 s | 94.9 s | 0.69 s | 0.99–1.02 s | −99.4 %; target met (≤ 10 s, ideal 1 s) |
| `uncached_wall_s`, no store at all | about 170 s | 94.9 s | about 96 s | 74.0 s (base of the hour 90.7 s) | −56 % since the start; D-134 not met |
| `cpu_s`, uncached | 529.5 | 310.5 | about 320 | 229 | −57 % |
| `coverage_pct` | 89.12 % | 89.68 % | 89.69 % | 89.69 % | held at every phase |
| `test_functions` | 2,337 | 2,371 | 2,378 | 2,384 | held |
| `failed` | 0 | 0 | 0 | 0 | held |

Each phase is judged against its own base measured the same hour; the box drifted between hours, so the columns
compare phases, not hours. F7's gain (about 2 % of the suite) is below what a suite pair resolves here, so it was
judged on the tests it changes, in ABBA order.

### The e2-micro (the-tower-runner)
Read from the runner's `gate.passed`/`gate.failed` events, whole gate, no result store (`cost.cache_hits` 0), an
e2-micro against the container's 4 vCPUs:

| PR (head) | Wall | CPU | Result |
|---|---|---|---|
| #838 | 544, 531 s | 281, 276 s | passed |
| #840 | 662, 613 s | 309, 312 s | passed |
| #841 | 554 s | 289 s | passed |
| #842 | 320 s | 345 s | passed |
| #843 | 292 s | 326 s | passed |
| #844 | 556 s | 293 s | passed |
| #845 `39991229` | 397 s | 546 s | passed |
| #845 `a59d10de`, `3f67dbd7` | 538, 482 s | 685, 534 s | failed: the uid 0 probe (above) |

The same stages take 25–40x the container's: the structure check 168–234 s against 7 s, the schema compat 97–146 s
against 3 s, the PR metadata 55–88 s against 5 s (the forge's reads, and the stages share the box's CPU). The wall is the
CPU (about 290–340 CPU-s of suite on a shared-core box) plus contention; the gate's 10 s target of D-122 was out of reach
without not running the tests, which is what the shared results do. After D-135 the runner's gates are appended below.

**After D-135, the same runner, the same head** (`40da7345`, this PR's closing docs, five script tests selected). The
first gate was the first time the runner judged those inputs; I then asked the runner to gate the same head again
(`scripts/service requeue --pr 846`), which is the documented way and touches nothing on the VM:

| Run | Wall | CPU | Script tests (stage) | Cache hits |
|---|---|---|---|---|
| 1, inputs never judged | 364 s | 499 s | 124 s (5 tests run) | 0 of 5; the runner published 5 PASSes at 17:38:19 UTC |
| 2, same head, requeued | 300 s | 329 s | 10 s | 5 of 5 (source: run 1) |

So the shared results work on the e2-micro end to end: the runner publishes what it judges and reads what any box
judged, and the stage that was the whole gate on a fresh box (about 300 CPU-s of suite) is the stage that no longer
is. It also shows what they cannot do: a PR gate runs the tests whose inputs *changed*, and those have no PASS
anywhere until someone runs them, so a scoped PR gate misses by construction the first time and saves on every rerun
and on every box that judges the same inputs afterwards (a full run on a fresh box, the train's batch gate). Before
D-135 neither happened (292–662 s, zero hits). The stages D-135 does not touch are now the gate: structure check
193–228 s, schema compat 130–148 s, PR metadata 70–80 s (the forge's reads), secret scans 38–71 s, all on the same
shared CPU. The structure check's own cache (`structure.tree_cache_dir`, per box) did not hit on the identical head
(3 min 14 s, then 3 min 48 s); why is not known and is the cheapest lead for the next unit (N19, N21 in the
solução).

## 6. Lessons

| Problem | Change that prevents it | Owner |
|---|---|---|
| Decision numbers collide between sessions | a number is taken when the row merges, or reserved by a command that writes a ref | structure owner (A Torre) |
| A stage killed past its limit is labelled `code` | the runner keeps the `.timedout` marker through the report; a timeout is `env` | engine-gate-report |
| The e2-micro cannot judge a PR whose selection is large | results any runner trusts (a session's PASS reused by the runner), the next program | engine-gate-run |
| A measurement on a dirty or polluted checkout lies | `scripts/test-suite --metrics` refuses a root with untracked or modified files | engine-gate-report |
| A test reaches lines of another module by accident | a fixture runs only the machinery it judges, plus one integration test of the chain | engine-test-support |
| The setup leaves the retired product's `node_modules` in `apps/` | `scripts/cloud/setup.sh` installs nothing for a product root that `units/` no longer names | engine-cloud |
| A rule and its first content in one PR | the program template says so: land the rule, then the content (D-117) | structure owner |
| An estimate set a phase's expectation (F4's "30 % of the CPU") | a phase's audit counts the thing it will remove before the plan names a gain | program owner (padrão v8) |
| A fixture swaps the file a hermetic setting lives in (`GIT_CONFIG_GLOBAL=/dev/null`) | hermetic settings at the environment's level (`GIT_CONFIG_COUNT`, F5) | engine-gate-report |
| A coverage tracer restarted inside a running frame measures nothing of it | a fork keeps its parent's tracer; coverage.py writes a fork's data to its own file | engine-hermetic-tests |
| A box whose speed moves ±15 % within the hour | A/B pairs, interleaved, for every phase verdict; never one sample | program owner |
| Pairs always run in the same order on a box that drifts | ABBA order; a change under the pairs' resolution is judged on the tests it touches | program owner |
| A profile ranks the wrong cost (cProfile: small, frequent calls; a fork resets it) | the profile finds where to look, an A/B decides; both cheap attempts of F11 were dropped by it | program owner |
| A feature that changes who runs a test is on where the tests do not run (D-130 read by `test-suite`, never by the runner) | switch it on where the runner runs and read the runner's own events for its hits (D-135) | engine-gate-run |
| The runner's failure event keeps a signature, not the output (`uid N probe failed (N)`) | the event keeps the failing test's output tail, so a failure on the VM can be diagnosed without the VM | engine-gate-report |
| A phase's target (10x) is set before the audit counts what it would remove | the audit's count sets the target; a phase without a 10x cut says so before it starts (D-132) | program owner |

## 7. Not done: the handover (D-136)
The program stops here by Daniel's order, with the suite at 74 s uncached (target 1 ms, D-134) and 0.99 s against the
shared results. The state, the nodes in order, the files to start from and the exact commands that reproduce every
number above are in the [solução's Retomada](solucao.md#retomada-d-136). In short:
1. **The lean runner and the CLIs in process (N13, N10).** About 2,200 shell and Python starts and 98 scripts'
   start-up and imports are what is left after the train; nothing linear moves them (two attempts gained nothing).
2. **Git in memory for the other 57 modules (N8/N6)**, by the CPU list in the Retomada; the integration layer (N14)
   keeps real git where git is the subject.
3. **The e2-micro's uid 0 probe** (above) fails intermittently there: it needs the VM's own log, or the event keeping
   the output tail (the lessons table).
4. **The gate's fixed costs (N17–N22)** once the suite is no longer 85 % of the gate.
5. **Not measured:** the floor of an empty test through the runner (N16), which says how far 1 ms is; and the forge's
   round trips, 18–23 a gate, whose latency is the likely floor of any gate that talks to GitHub.
