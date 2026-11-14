# gate-speed — solução

The path from the [diagnóstico](diagnostico.md)'s baseline (`cold_wall_s` 169.1 s on 4 vCPUs) to the ideal system of
the [avaliação](avaliacao.md): a 10x ladder on the main metric, each phase its own PR (or small series) through the
gate and the train, measured at its end in the session container with `scripts/test-suite --metrics` (main metric and
every guard; a phase passes only if the main metric reaches its target and no guard gets worse, D-115). Daniel's 23:14
BRT order: no wait for approval; each green phase merges and the next starts.

## Fases
**Extended after D-134's clarification (Daniel, 31/10 12:36 BRT): the main metric stays `uncached_wall_s` in the
session container; the e2-micro, where the gate runs, is the final destination, reached once the container is at the
target, and nothing is measured on it during the phases.** Because the destination is the gate, the gate's own
end-to-end time (`gate_wall_s`, from the PR's event to its reported verdict, measured in the container) is a
complementary metric, and its fixed costs are nodes of the graph. On #844 the gate took 91 s of wall: the script
tests 77 s, the structure check 7 s, the PR metadata 5 s (forge reads), the schema compat 3 s, the secret scans 2.5 s,
plus the wake, the queue, the checkout and the report.

| Node | Change | Needs | Estimated gain | State |
|---|---|---|---|---|
| N17 | An always-warm gate: one resident process with the engine and the tests imported, woken by the PR's event (no process start, no import, no toolchain probe per gate) | N10 | the gate's start-up and its stages' (seconds today) → µs | |
| N18 | A persistent workspace: one object store kept between gates; the head is fetched (its new objects only) and read as an in-memory tree, never checked out to disk | N8, N11 | checkout and preparation → the fetch of the new objects | |
| N19 | Stages fused and parallel over one snapshot: the structure check, the generated drift, the schema compat and the tree secret scan read the same in-memory tree once, in the warm process | N11, N12, N17 | 13 s of stages, each re-reading the tree and the registry → the logic they assert | |
| N20 | The forge off the critical path: the PR's metadata in one read (or from the event itself), the verdict one write; the status panel and its edits after the verdict | — | the forge's 5 s → one round trip each way, counted and timed apart (D-134) | |
| N21 | The secret scans incremental and in process: the tree scan over the changed blobs, the history scan over the new commits only, against the same rules as gitleaks (gitleaks stays in the integration layer, N14) | N18 | about 2.5 s → the changed bytes | |
| N22 | `gate_wall_s` as a command: the gate run from a clean state with no store, the event-to-verdict time and every stage's share printed and kept as JSON (reproducible; the numbers are published) | — | — (it is the measurement) | |

The phases below (F11–F15, main metric `uncached_wall_s`) take the gate's nodes where they serve the suite (N17 is N10
for the gate, N22 measures `gate_wall_s` beside the main metric); after F15 the gate as a whole goes to the e2-micro.

**Extended after D-134 (Daniel, 31/10 11:51 and 12:02 BRT): the final target was about 1 ms for the whole suite
uncached, in phases of at least 10x: 10 s → 1 s → 100 ms → 10 ms → 1 ms.** The engine stays in Python. The budget
fixes the design: about 2,400 test functions in 1 ms on 4 cores is about 4 CPU-ms, under 2 µs a test. A unittest test
case costs tens of µs of runner machinery before its first assertion, a process start tens of ms, a git process about
1 ms, a file write tens of µs. So at the final level a test is a Python function call on values already in memory, in
a process that imported everything before the clock started, and nothing else; every effect is a port whose
in-memory adapter answers in ns–µs, and the real effects are judged in the separate integration layer (D-134).

Nodes added for the levels below 10 s (estimated gain; measured after):

| Node | Change | Needs | Estimated gain | State |
|---|---|---|---|---|
| N10 | A lean runner: one warm process imports every test module before the clock, collects test functions once, calls them directly (setUp/tearDown/subTest kept as plain calls), forks workers from the warm image only where the cut pays for the fork | N13 | runner and import cost (about 50 ms a file, 30–100 µs a test) → about 1 µs a test | |
| N11 | A pure engine core: modules take values (a tree, the registry, an event log, a clock reading) and return values; effects (git, disk, processes, forge, clock) only through ports, each with a real and an in-memory adapter | N8 (git) generalized to disk, processes and the clock | a test's own work → the logic it asserts | |
| N12 | The registry, the contracts and the unit manifests as values loaded once per run (a frozen snapshot the run starts from; a test that changes the registry gets its own copy) | N11 for config | the 390,000 stats a train test pays → zero | |
| N13 | Every `*.test.sh` wrapper registered directly in the runner; a test whose subject is a CLI calls its `main(argv)` in process (exit code and output asserted as before) | — | about 1,600 shell and 900 interpreter starts → zero | |
| N14 | The integration layer: the tests whose subject is a real effect (git, a process, PostgreSQL, gitleaks, the merge driver, the hooks) in one separate small suite with its own metric, `integration_wall_s` | N6, N11 | the effects leave the main suite; judged apart, never dropped (D-134) | |
| N15 | The hot path without allocation: test worlds as constants built before the clock (N7's snapshots frozen into the warm image), no per-test temp directories, logging off the path | N7, N10, N11 | the last µs per test | |
| N16 | The floor, measured: an empty test function's cost through the runner, the fork and the join of a worker, the clock read; recorded as the D-NNN that stops the program | N10 | — (it is the stop criterion) | |

| Phase | Target (`uncached_wall_s`) | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F11 | ≤ 10 s (from about 96 s) | N8 + N6 + N7 (+ N9), the train and the gate first | 10x measured, ABBA with repetitions | several PRs |
| F12 | ≤ 1 s | N10 + N12 + N13: one warm process, no shell, no per-test runner machinery | the same | several PRs |
| F13 | ≤ 100 ms | N11 + N14: a pure core, the effects in the integration layer | the same | several PRs |
| F14 | ≤ 10 ms | N15: worlds frozen into the warm image, no allocation on the path | the same | — |
| F15 | ≤ 1 ms, or the floor | N16 measured; what is left above it | a physical floor measured and recorded (D-NNN) | — |
| — | `integration_wall_s` | measured from F13 on, its own target set when it exists (D-134) | — | — |
| — | N2 + N3, the e2-micro | beside, not progress (D-133); the e2-micro once, near the end (about 100 ms there) | — | — |

The graph after D-133 and before D-134, kept for the record:

**Re-planned after F10 (D-133): two main targets, each ≤ 10 s with 1 s ideal; the work is the uncached suite.**
`cold_wall_s` (with the shared cache) is 0.69 s and is kept; `uncached_wall_s` (no store at all) is about 96 s on
about 320 CPU-s, and the next phases cut the graph for it. Why the uncached suite does that work: each test builds
its world from nothing through real processes (about 45,000 git processes: init, add, commit, fetch, push per test
case), because the engine reaches git and the forge through subprocesses, not through ports a test can fill in memory;
and each world is built again by every test case that needs the same one.

Nodes for the uncached target (added to the graph below; estimated gain on `uncached_wall_s`):

| Node | Change | Needs | Estimated gain | State |
|---|---|---|---|---|
| N6 | In-memory doubles for the forge, the train's workspace and the change store where git is not the test's subject | N8 for the engine's own git calls | the train's and the gate's families (about a third of the CPU) → near zero | |
| N7 | Each test world built once per run and shared copy-on-write (a snapshot per fixture kind, a copy per test case) | — | the fixtures' init/add/commit (about 11,000 processes) → one build per kind | |
| N8 | The engine reaches git through one port (a git adapter and an in-memory adapter), as it reaches the forge (forge_events) | — | unlocks N6 for every engine module, not only the train | |
| N9 | The subjects' own processes (gitleaks, the merge driver, hooks) run once per run where their subject allows | — | about 30 CPU-s of gitleaks → one scan of the union | |

| Phase | Target | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F11 | `uncached_wall_s` ≤ 10 s (from about 96 s), `cold_wall_s` kept ≤ 10 s | N8 + N6 + N7 (+ N9 if the cut needs it): the smallest closed set the measurement shows gives 10x | 10x measured in ABBA with repetitions, or the next level of redesign; only a measured physical limit stops | several PRs |
| F12 | `uncached_wall_s` ≤ 1 s | what F11's measurement leaves | the same | — |
| — | N2 + N3 (the gate and the runner on the shared cache, then the e2-micro once) | may go on beside, not counted as progress (D-133) | — | — |

The graph before D-133, kept for the record:

**Redrawn after F10 (D-132): an unlock graph from the current system to the ideal one, cut into phases of 10x.**
The ideal system (avaliação): a test's verdict is a pure function of the inputs it reads, computed once on any box
and kept by input key; a change runs only the tests whose inputs it changed, in process, in memory, on every core;
the whole suite cold about 1 s on 4 vCPUs and under 10 s on the e2-micro, a typical change's verdict well under 1 s.

Unlock graph (Mikado style; a node needs the ones it names; gain on the metric it moves, estimated before, measured
after):

| Node | Change | Needs | Moves | Estimated gain | State |
|---|---|---|---|---|---|
| N1 | PASSes shared between boxes by input key (D-130) | — | `cold_wall_s` | 96 → about 1 s | done in F10: 0.69 s measured, 139x |
| N2 | The gate and the runner read and publish the shared results | N1 | the runner's cold verdict (e2-micro) | 1,200 s and more → seconds | next |
| N3 | The e2-micro validates once (Daniel's rule: near 1 s, now met) | N2 | `cold_wall_s` on the e2-micro | measured, not estimated | after N2 |
| N4 | Keys per test file, not per script test: a change reruns the files that read it | N1 | `change_verdict_s` (a typical change on a fresh box) | about 35 s → about 5 s | |
| N5 | Keys from traced reads (the covers trace enforced), not declared covers | N4 | `change_verdict_s` | about 2x more | |
| N6 | In-memory forge, workspace and change store for the tests whose subject is not git | — | `change_verdict_s`, `uncached_wall_s` | the train's files 15 s → about 1 s | |
| N7 | Fixtures built once per run and shared copy-on-write | — | `uncached_wall_s` | about 2x | |

Phases (cuts of the graph, each the smallest closed set that delivers at least 10x measured):

| Phase | Target | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F10 | `cold_wall_s` ≤ 10 s (from 96 s) | N1 | reached: 0.69 s (D-131); the `uncached_wall_s` guard measured again in F11 | 1 PR, done |
| F11 | the runner's cold verdict ≤ 1/10 of today's | N2 + N3 | the e2-micro measured once; a miss records its floor (CPU, network), a D-NNN | 1–2 PRs |
| F12 | `change_verdict_s` ≤ 1/10 (a sample of real changes on a fresh box) | N4 + N5 + N6 (+ N7 if the cut needs it) | 10x measured, or the next level of redesign; only a measured physical limit stops | several PRs |

The main metric of F10 (`cold_wall_s` against the shared results) is at 0.69 s, about its own floor (hashing the
covered files and one fetch); the next cuts move the metrics the ideal names next: the e2-micro's verdict and a
change's verdict.

**Re-planned after F9 (D-129, Daniel 31/10 09:41): 10x a phase, by redesign.** F4–F9 were linear (−7 %, −6 %, …);
from F10 each phase must deliver 10x on the main metric, and only a measured physical limit stops the program.

| Phase | Target (`cold_wall_s`, container) | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F10 | ≤ 10 s (from 96 s) | **The cold suite redesigned.** A model of the cold suite: for each test, the processes that are its subject (a git merge driver's merge, a secret scan, a hook) and the rest, which goes: in-memory doubles for the forge, the workspace, the change store and the registry reads; fixtures built once per run and shared copy-on-write; every Python test file run in one preloaded process per worker; the test folders and files restructured around that model. | The measured floor of the subjects' own processes on 4 vCPUs, recorded as a D-NNN | several PRs |
| F11 | ≤ 1 s | The subjects' own processes: one per run where their subject allows. | The physical floor, measured | — |
| F12 | e2-micro (once) | Validation at the end. | — | 1 run |

**Re-planned after F6 (D-125).** F4 (fork server, D-123) and F5 (the train's git answers, D-124) took the suite to
94.9 s cold and 310.5 CPU-s; F6 measured that the suite is now bound by its CPU (`cpu_s / 4` is about 80 % of the
wall), so more parallelism only moves CPU around. What is left, by measured share: the fixtures' git (about 45,000
processes a cold run, init/add/commit/push per test case, each push through the local transport) and the test files'
own Python (about 120 CPU-s, the largest file 9 CPU-s: a long tail, no single hot spot).

| Phase | Target (`cold_wall_s`, container) | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F4 | ≤ 60 s (stopped at 96.2 s, D-123) | A fork server for every Python process a test starts. | done | 1 PR |
| F5 | ≤ 60 s (stopped at 94.9 s, D-124) | The train's workspace answers about objects once; hermetic git through the environment. | done | 1 PR |
| F6 | ≤ 60 s (not merged, D-125) | One process per test class of the longest files. | measured inside the noise | — |
| F7 | ≤ 60 s | **Fixtures without a transport:** a fixture repository's "push" writes the ref into a remote that shares its objects (alternates) instead of starting the local transport (seven processes a push), and fixture histories are built by one `git fast-import` instead of an init, add and commit per file set. | Measured at its value, a D-NNN | 1–2 PRs |
| F8 | ≤ 10 s (step 1, the train fixture's workspace: 96.3 s, D-127) | **In-memory doubles where git is not the subject:** the train's and the gate's fakes answer refs and trees from memory; the tests whose subject is git keep real repositories. The report names every test above 1 s. | `cpu_s / 4 > 10` with the rest in tests whose subject is a process: the floor measured, a D-NNN | 3+ PRs |
| F9 | ≤ 10 s (at its value, D-128) | One `node` for every generated TS module; one walk per file in the vendor check. | done | 1 PR |
| F10 | e2-micro ≤ 10 s (once) | Validation, not a lab (Daniel 23:11, D-122). | A miss records both numbers and the e2-micro's floor, a D-NNN | 1 run |

The plan after F3, kept for the record:

**Re-planned after F3 (D-122).** Daniel (31/10 03:08 BRT) revoked D-121's stop: the program goes on to about 10 s cold
in the container, in his order: a fork server, then the train's git work batched, then the retro's other next steps.
F4's audit measured what a cold run starts: about 63,500 processes, 54,300 of them git (85 %), about 900 Python, each
Python process paying 40–55 ms of start-up and harness that a fork of a warm interpreter does not
([F4](phases/F4.md)).

| Phase | Target (`cold_wall_s`, container) | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F1 | ≤ 60 s (stopped at 163.4 s, D-118) | Hermetic git for every test process; a jobserver for the long tail. | done | 1 PR |
| F2 | ≤ 60 s (stopped at 101.6 s, D-120) | Fixtures copy what they read; tests stop running machinery that is not their subject; the engine in process where its CLI is not the subject; cost hints. | done | 1 PR |
| F3 | ≤ 60 s (stopped at 95.8 s, D-121; the program's stop revoked, D-122) | The engine's own reads made cheap (registry, secret guard, plan dates, syntax trees, the train's tooling version). | done | 1 PR |
| F4 | ≤ 60 s | **Start-up is paid once.** A fork server: one interpreter per run with the standard library imported and its heap frozen; every Python process a script test starts is a fork of it, reached through a native client named `python3` first on the tests' `PATH` that keeps the process's contract (argv, environment, working directory, umask, descriptors, exit status, signals) and execs the real interpreter for whatever the fork does not model. | Measured at its value with a D-NNN when the start-up left is under 5 % of `cpu_s`; the next phase starts | 1 PR |
| F5 | ≤ 60 s | **The train's git work batched** (Daniel's order): a train step asks one git process what it now asks many. | Measured at its value, a D-NNN | 1 PR |
| F6 | ≤ 10 s | **The rest by measured share** (the retro's next steps): fixture repositories built once per run and copied, in-memory doubles where git is not the subject, waits on events where a probe busy-waits. | `cpu_s / 4 > 10` with the rest in tests whose subject is a process: the floor measured, a D-NNN | 2+ PRs |
| F7 | e2-micro ≤ 10 s (once) | Validation, not a lab (Daniel 23:11, D-122): one `scripts/test-suite --metrics` on the e2-micro through the documented runner command, at the end. | A miss records both numbers and the e2-micro's floor, a D-NNN | 1 run |

The plan after F1, kept for the record:

**Re-planned after F1 (D-118).** F1 measured that the suite is bound by CPU, and the CPU by the processes each test
starts (about 127,000 in a partial trace, 42,000 of them git); F1's two levers removed the box's leak and the idle
tail but cannot reach 60 s, so the ladder shifts one rung and the restructuring that pays processes once comes next.

| Phase | Target (`cold_wall_s`, container) | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F1 | ≤ 60 s (stopped, D-118) | Hermetic git for every test process (no global or system config, a fixed identity, no signing, no automatic maintenance) and a jobserver that hands the CPUs of ended tests to the long tail. | Stopped at its measured value: the wall is bound by `cpu_s / 4`, which only fewer processes lower | 1 PR, done |
| F2 | ≤ 60 s (stopped at 101.6 s, D-120) | **Processes are paid once.** Fixtures copy only what they read (the registry's aggregates, not its 900 per-key sources); a test does not run machinery that is not its subject (the push guard's fixtures ran the whole pre-push check on every push); the engine is called in process where its CLI is not the subject. The heaviest tests first. | `cpu_s` above 240 with the rest in tests whose subject is a process: the floor measured, a D-NNN | 2–3 PRs |
| F3 | ≤ 60 s (D-120; stopped at 95.8 s, the program stops, D-121) | **The engine's own work gets cheap.** The structure check reads the registry once per run and walks each syntax tree once, judges every parameter's secret shape with one read of its guard and dates every plan with one git log; a train run reads its tooling's version once; the train's test forge reads refs from their files. | `cpu_s` above 240 with the rest in tests whose subject is a git or bash process: the floor measured, a D-NNN | 1–2 PRs |
| F3b | ≤ 10 s | **The whole suite in process.** A warm fork server (the engine imported once, each test file forked from it), in-memory doubles where git is not the subject, the slowest files split so the jobserver spreads them; the report names every test above 1 s (a warning). | `cpu_s / 4 > 10` with the rest in tests whose subject is a process: the floor measured, a D-NNN | 2–3 PRs |
| F4 | ≤ 1 s | Every test file under about 0.25 s, `cpu_s` about 4. | The physical floor (process start-up times the processes a test is about), a D-NNN | 2+ PRs |
| F5 | e2-micro ≤ 10 s (once) | Validation, not a lab (Daniel, 23:11): one `scripts/test-suite --metrics` on the e2-micro through the documented runner command. | A miss records both numbers and the e2-micro's floor (`cpu_s` / its burst vCPUs, D-093), a D-NNN | 1 run |

The first plan, kept for the record:

| Phase | Target (`cold_wall_s`, container) | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F1 | ≤ 60 s | **The box stops leaking into the tests, and the long tail gets the free CPUs.** Every test process runs git hermetic (no global or system config, a fixed identity): today each fixture commit inherits this box's signing, 80 ms against 7 ms. The scheduler gives the longest tests (structure-check 60 s, train 55 s, push-guard 44 s, train-reuse 40 s) the CPUs that free up as the short ones end, instead of one CPU each for the whole run. | A single test file still above 60 s after both changes needs its fixtures rewritten: F1 stops at the measured value with a D-NNN and F2 takes it | 1 PR, 3–4 commits, ~2 h |
| F2 | ≤ 10 s | **Start-up and fixtures are paid once.** A warm fork server: the engine imported once, each Python test file forked from it. Fixture git repositories built once per run and copied, in-memory doubles where git is not the subject. The slowest files test in process (the function, not the CLI) where the CLI is not the subject. The suite report names every test above 1 s (a warning, never a failure). | `cpu_s / 4 > 10` with the rest of the cost in tests whose subject is a process (git, bash, a CLI): the floor measured, a D-NNN | 2–3 PRs, ~4 h |
| F3 | ≤ 1 s | **Every test file under about 0.25 s, `cpu_s` about 4.** Shell tests ported to the in-process harness where their subject allows; the tests that must start processes keep the fewest and run first. | The physical floor: process start-up times the processes that are the subject of a test, measured, a D-NNN | 2+ PRs, ~4 h |
| F4 | e2-micro ≤ 10 s (once) | **Validation, not a lab** (Daniel, 23:11): one `scripts/test-suite --metrics` on the e2-micro through the documented runner command, when the container is near 1 s. Over 1 s is a warning. | A miss records both numbers and the e2-micro's floor (`cpu_s` / its burst vCPUs, D-093) as a D-NNN | 1 run, ~30 min |

Guards at every phase end (baseline in the diagnóstico): `coverage_pct`, `test_functions`, `failed` (two independent
cold passes), `cpu_s`, `warm_wall_s`. No test is deleted, skipped, quarantined or loosened (timeouts, thresholds) to
reach a target: a test is restructured with every assertion it had.

## Retomada (D-136)
The program closed on 31/10 14:30 BRT by Daniel's order, at F11's measured state. Whoever resumes (a wider unit that
reviews the whole flow, if the test time is still its bottleneck) starts here. The graph above stands; D-134 (about
1 ms uncached in the container, then the e2-micro) is still the target.

**State, measured** (container, 4 vCPUs): `cold_wall_s` 0.99–1.02 s; `uncached_wall_s` 74.0 s; `cpu_s` 229; 35,430
process starts in one uncached run (13,323 git, 8,059 `grep`, 7,888 `ps`, 960 Python, 742 `bash`, 478 `sh`, 277
`psql`, 180 `node`); the CPU per script is spread: `structure-check` 31 s, `train` 18, `config` 14, `merge-regenerate`
11, `push-guard` 11, `gate-test-cache` 11, then 92 scripts under 9 s each (299.6 CPU-s in all, summed over the 98 scripts, before F11 step 3).

**What exists to build on**
- `scripts/tests/memory_git.py`: git in memory (one object store, refs per repository, working trees on disk, line
  merges), `intercept()` routes `subprocess.run` of `git` for its repositories only; any command it does not know raises.
  `test_memory_git.py` runs one script of commands on real git and on it and requires the same answers: add a command
  there first, then use it. The train's fixture (`test_train.Fixture`) is the model (`memory = False` keeps a class on
  real repositories where git is the subject).
- The train reaches git only through `GitWorkspace` (step 1, #843); the other 57 engine modules that call git do not.
- `scripts/lib/fork_server.py`: one warm interpreter per run, forks per Python process (F4).
- `scripts/lib/shared_results.py`: PASSes shared by input key, read by `scripts/test-suite` and, since D-135,
  `scripts/gate-dev`.

**Next, in order, each with its first measurable cut**
1. **N13, CLIs in process.** About 1,220 `sh`/`bash` and 960 Python starts a run come from `*.test.sh` wrappers and
   tests that run a script to assert its exit code and output. Register each `*.test.sh`'s Python in the runner and call
   the CLI's `main(argv)` in process where the CLI is not the subject. Cut: the process counts above; measure with the
   trace below.
2. **N10, a lean runner.** One warm process imports every test module before the clock, collects the test functions
   once and calls them (`setUp`, `tearDown`, `subTest` as plain calls), forking workers from the warm image only where
   a test needs its own process. The entry points to replace are `scripts/lib/parallel_tests.py` and
   `scripts/lib/gate_test_cache.py` (`run`, `forks`). Cut: the 98 scripts' start-up and import (about 50 ms a file).
3. **N8/N6 to the other modules**, by the CPU list above: `test_structure.py` (900 git processes in 57 tests),
   `test_push_guard.py`, `test_merge_regenerate.py`, `test_units.py`, `test_gate_carry.py`, `test_retro.py`. For each,
   keep real git only for the tests whose subject is git (they form the integration layer, N14).
4. **N12, the registry and contracts as values** loaded once per run: a profile of `test_train_reuse.py` shows 6,394
   scans of the 53 registry files (about 340,000 `stat` calls); but two cheap attempts (a memo of the change store's replay, a frozen
   registry digest) gained nothing in ABBA, so do it as a value passed in, not another cache.
5. **N11, N14, N15, N16** as in the table above, after 1–4; N16 (the measured floor of an empty test through the
   runner) is the stop criterion and should be measured early, because it says how far 1 ms is.
6. **On the e2-micro the suite is no longer the gate** (D-135 proved it: script tests 124 → 10 s on a rerun); the
   structure check (193–228 s), schema compat (130–148 s) and the PR metadata (70–80 s) are. The structure check's own
   cache (`structure.tree_cache_dir`) did not hit on an identical head there: find out why first.
7. **N17–N22, the gate's fixed costs**, when the suite is no longer most of the gate (it is about 85 % of it now):
   N22 first (the measurement as a command).

**How to measure** (every number published must be reproducible)
- Clean git worktrees at the exact heads under `/home/user`, nothing else running; `source scripts/cloud/env.sh`.
- Cold: `OU_SHARED_RESULTS=1 scripts/test-suite --metrics`, twice (the first publishes the tests that changed; the
  second is the number).
- Uncached: `OU_SHARED_RESULTS=0 scripts/test-suite --metrics --json F`, in ABBA order against the base of the same
  hour, at least three each (the box moves ±15 % within the hour).
- Coverage: add `--coverage /home/user/gs-covlib` (a directory with coverage.py importable); two passes of the same
  code differ by about three lines (89.68 and 89.69 %).
- Processes: `strace -f -qq -e trace=execve -o F scripts/test-suite --metrics` (a count, never a cost: tracing makes a
  busy-wait spin).
- Do not use cProfile for a verdict: it overstates small, frequent calls (the registry scan was ranked first and
  removing its repeats gained nothing), and a fork resets it. Use it only to find where to look, then A/B.
- The e2-micro cannot be reached from a session; read the runner's `gate.passed`/`gate.failed` events (`cost.wall_s`,
  `cost.cpu_s`, `cost.cache_hits`, each stage's `duration_ms`) on the PR's channel.

## Critério de parada
D-136 (Daniel, 31/10 13:26 BRT) closed the program at F11's state; it resumes from the Retomada section above. D-122 (Daniel, 31/10 03:08 BRT): the program does not stop by cost-benefit before about 10 s cold in the container. A phase that misses its target stops at its measured value with a D-NNN and the next phase starts; the program ends at about 10 s and F7's one validation on the e2-micro, or at a physical floor measured and recorded (process start-up times the processes a test is about, or the e2-micro's CPU). The retro (`retro.md`) closes it.

Until D-122 (kept for the record): The program ends when F3 reaches 1 s and F4 validates the e2-micro at 10 s or less, or earlier at a phase's stop
criterion: a physical limit (a measured floor: process start-up times the processes a test is about, or the e2-micro's
CPU) or a bad cost-benefit (more than about two hours of rewrite per second saved once under 10 s). Each stop is a
D-NNN with its numbers; the retro (`retro.md`) closes the program.

Parts of the ideal system that do not move this main metric are not phases here, because a v8 program has one main
metric: selection enforced by traced reads (soundness of the warm path), a result cache shared between boxes, and the
flake rate over many runs. Each becomes its own program when the merge queue of about 1,000 PRs a day needs it.
