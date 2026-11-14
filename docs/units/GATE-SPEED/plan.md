# GATE-SPEED — plan

Stage 4–5 of the unit flow (D-077, Padrão v7). Reads [audit.md](audit.md)'s `## Causas raiz` and
[research.md](research.md)'s `## Escada de ambição`; the architecture is [ADR-42](../../adr/ADR-42-gate-answers-by-content.md).

## Alternativas

### R1 The gate recomputes what did not change, and its memory of past answers lives on one box
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Lengthen `gate.test_cache_ttl_s` and pre-warm the VM by hand | remendo | não: a fresh box and tier 2 still run everything | minutes | one registry value | a stale marker lives longer | 0 |
| A2 Judge the whole suite by key in one process (each file hashed once), and make the scans incremental by default (the PR's commits and changed files; full at night) | corrige a classe | sim, for every runner that keeps its store: the answer is computed from the input, the scans judge the change | one session | a switch per mechanism (`gate.leak_scan_scope`) | a key that misses an input hides a break: covers check and nightly cold run stay | 2 |
| A3 A shared, content-addressed result store any runner trusts (Bazel's remote cache) | redesenho | sim, across boxes | a store on a free tier and a trust model (D-073) | drop the store | a poisoned entry passes every runner | 3 |

### R2 A test or a module pays one process per git object or step
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Speed up the slowest fixture by hand | remendo | não: the next reader repeats the pattern | an hour | revert | none | 0 |
| A2 One batched reader of a commit's files (`git cat-file --batch`), memoized by commit sha, used by the readers that loop | corrige a classe | sim, for production readers | hours | revert per caller | a memo keyed by a ref instead of a sha would go stale: keyed by the resolved sha only | 1 |
| A3 In-memory git doubles for tests that only read refs and trees | redesenho | sim, for tests | days | per test | a double that drifts from git hides a bug | 2 |

### R3 Reading a registry value replays a remote log
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Read fewer values in the hot loops of the structure check | remendo | não: every other caller pays the same | an hour | revert | none | 0 |
| A2 Memoize the event catalog per contracts directory listing, and serve one replay per read of the log without copying it on every call | corrige a classe | sim: a value read costs a dict lookup once the log read is the same | hours | revert | a caller that mutated the returned overrides would now share them: returned as a fresh shallow copy of an immutable fold | 1 |
| A3 Snapshot the shared store into the process environment once per run | redesenho | sim | a day | a switch | a switch flipped mid-run is seen next run only | 2 |

### R4 The gate's report runs the factory's chores on the verdict's critical path
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Raise the printed read bound | remendo | não, and it loosens a bound | — | — | refused (Daniel: no loosening) | 0 |
| A2 Route defects only when this run found or changed one, and read each PR channel once per process | corrige a classe | sim for the reads; the base re-run of a failing test stays (it decides the verdict) | hours | a switch (`defects.route_on_change_only`) | a defect detected elsewhere is routed by its own run, or by `scripts/defects route` | 1 |
| A3 Move every post-verdict chore to a runner job after the verdict | redesenho | sim | a day, and a new job kind | drop the job kind | chores lost if the runner stops | 2 |

### R5 The impact map is coarse where it matters most
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Keep the fail-closed classes; a registry change stays full | remendo | não | none | — | slow for registry PRs | 0 |
| A2 Select by the readers of the registry keys a diff changes (`x-readers`), full when a key has none | corrige a classe | sim | a day | a switch | a reader missing from `x-readers` hides a break: audited before it is used | 2 |
| A3 A dependency graph inferred from imports and file reads (Gazelle on Bazel) decides the affected tests | redesenho | sim | the last wave | `build.backend` | an inference gap: the native backend stays the fallback until parity | 4 |

### R6 The runner cannot pick up its own fixes
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Ask Daniel to restart the runner after each merge | remendo | não | a person per merge | — | forgotten restarts | 0 |
| A2 The runner re-executes itself between jobs when a refresh changed its own code | corrige a classe | sim | an hour | a switch (`service.self_update`) | a broken base crashes the runner: `Restart=always` brings it back on the same code, and the job is retried | 1 |
| A3 A warm runner: a resident process that refreshes, re-executes and pre-computes the keys of every new head before its job starts | redesenho | sim | a wave | a switch | memory on the e2-micro: measured | 3 |

## Escolha
Daniel, 30/10 11:47 BRT: "o padrão mundial já, nada de remendo", in waves (D-094). Every root climbs to the state-of-the-art rung of the research's ladder in this PR; wave 1 (the class fixes already planned) lands first.
- R1 → A3: wave 1 makes the whole suite judged by key on the box (A2: commits 3–4); wave 2 makes the answer trusted by any runner, a content-addressed result store on free compute (the VM's own disk behind the runner, or a GCS bucket inside Always Free), written only by gate runs and verified by key; the last wave gives it to Bazel's remote cache. A paid store is only a proposal for Daniel.
- R2 → A3: wave 1 batches and memoizes git reads in production (A2, commit 2); wave 2 gives the tests that only read git an in-memory double and the tests that write git a template repository copied per case.
- R3 → A3 if it measures better than the memo: wave 1 made the read constant (A2, commit 1); wave 2 snapshots the shared store once per run into the run's environment and measures both, keeping the faster (the choice and its numbers recorded).
- R4 → A3: wave 1 routes defects only on change and reads each channel once (A2, commit 5); wave 2 makes the post-verdict chores a runner job (`chores`, an additive kind of `job.v1`), so the verdict answers first.
- R5 → A2 now, A3 in the last wave: audit that `x-readers` is complete, then select by the readers of the changed keys (fail closed for a key without readers); Gazelle's inferred graph replaces it when Bazel reaches parity. The follow-up unit of the first plan is cancelled (D-093 revised).
- R6 → A3: wave 1 re-executes the runner when its code changed (A2, commit 6); wave 3 makes it a warm runner that pre-computes keys on push.

## Ondas
Serial: one commit, push, the normal gate green, then the next (Daniel, 11:51 BRT). Each wave closes before the next starts; the retro is last.

**Onda 1 — the class fixes (plan items 6).**
1. Registry reads are constant reads (R3 A2). Done: `236cd497`, `gate.passed` `5c555f8bc93c`.
2. One batched, sha-keyed git reader (R2 A2). Done: `ec822d4f`, `gate.passed` `8dd90f6b0419`.
3. The whole script suite judged in one pass; `scripts/test-suite` (R1 A2). Done: `409583d2`.
4. Scans judge the change (done: `a9531336`, red on the key's name, fixed in `2e36ecce` with the proof's epoch cost): `gate.leak_scan_scope` `change` (history `merge-base..head`, tree the changed and untracked files) in the PR gate, `full` in `gate-noite` (R1 A2).
5. The verdict before the chores: defects routed only when this run's known defects changed; one read of a PR channel per process (R4 A2).
6. The runner re-executes itself when a refresh changed its own code (R6 A2); in #816 with D-098 (each green commit merges at once).

**Onda R — registry and central lists without addition conflicts (Daniel 13:02 BRT, D-095; before commit 5).**
- R.1 (core): `config/registry/gate/` one file per key, `config/registry/gate.json` generated (`registry-gate`), `merge=regenerate`; the target lands disabled (D-096, P-46) and is enabled by the first PR after this one.
- R.2: the other owners split (62; `generate` and `config` stay whole) in #817 (D-099); one `registry` target for all of them enabled in the next PR, `registry-gate` retired (D-101).
- R.3: `docs/domain/DECISIONS.md` one file per decision (`docs/domain/decisions/D-NNN.md`), the register generated and merged by regeneration; the decision checks read the files.
- R.4: `docs/structure/assets.json` one file per entry, the inventory generated.
- R.5: a defect record's `area` becomes a view derived when read, not a stored field, so a unit manifest change never turns old records red.

**Onda 2 — each root at the state of the art (plan item 7).**
7. R5 A2, part 1 (done in #817, D-100): audit `x-readers` against the code: 153 undeclared readers found and declared; a test refuses a reader missing from the registry.
8. R5 A2, part 2 (D-102): a split registry key's diff selects the script tests of its readers (22 → 7 for one gate key); a key without readers keeps the wide selection (fail closed); contracts and the web stages' own reader selection follow in wave 4.
9. R2 A3: a template fixture repository built once per test process and copied per case; an in-memory git double for the read-only tests of the train and the structure check; counts of tests and assertions quoted before and after.
10. R3 A3: measured against the memo (D-103): a snapshot saves at most about 20 ms per fresh process; the memo stays, nothing built.
11. R4 A3: the post-verdict chores (defect routing, resolved-defect verification, flake attribution) become a `chores` runner job queued after the verdict.
12. R1 A3: the content-addressed result store any runner trusts: keys and PASS records under a store the gate runs write on free compute (the VM's disk served by the runner, or a GCS Always Free bucket), verified by key on read; the per-box store stays the fallback.

**Onda 3 — the graph and the warm runner (plan item 7).**
13. The inferred dependency graph: each script test's real inputs recorded from its imports and file reads (the audit hook of this unit's measurements), checked against its covers; a missing input refuses the manifest.
14. The warm runner: on a new head the runner refreshes, re-executes when needed, computes every key and starts the affected tests before the gate job asks for them.

**Onda 4 — Bazel, with Gazelle (plan item 7; Daniel 11:50 and 11:53 BRT).**
15. Measure first: Bazel (Bazelisk, a pinned release) on the e2-micro through the runner: server memory, cold and warm, time to verdict, on a pilot package (`scripts/lib` with `rules_python`). Recorded in a D-xxx with the numbers; if the server does not fit 953 MB with headroom, the numbers and the alternative are proposed to Daniel and the wave stops there.
16. `MODULE.bazel` and the `BUILD` files generated and kept by Gazelle (`rules_python`; Aspect's `rules_js`/`rules_ts` for the web package; `sh_test` for the shell tests): the `BUILD` files are the source of truth, never edited by hand; covers and keys are the migration's input.
17. The thin adapter: the gate asks one interface, "the tests this diff affects, with verdict and times", of the backend `build.backend` names (`native` | `bazel`); `native` (today's gate) is the fallback until Bazel proves parity; a future backend (Buck2 included) touches only this layer, and none is implemented now.
18. The remote cache on free Google compute only (bazel-remote on the VM's disk, or a GCS bucket inside Always Free); any cost is a proposal for Daniel.
19. Parity per category, then the switch: `build.backend` `bazel` once every category it covers matches the native verdicts on the same heads; the covers of a category retire after its parity.

**Onda 5 — continuous operation, no "night" (Daniel 12:57 BRT, D-097; after wave 4).**
Premise corrected: A Torre runs continuously at about 1,000 PRs a day (about 42 an hour, one every 86 s); nothing may wait for "once a day". What the state of the art does at that volume, and what we take:
- *Gating by a speculative merge queue* ([Zuul dependent pipelines](https://zuul-ci.org/docs/zuul/latest/gating.html): each change is tested on top of the changes ahead of it, in parallel, and the ones behind a failure are retested without it; [Uber SubmitQueue](https://github.com/uber/submitqueue/): conflict analysis from the build graph prunes the speculation, independent changes land without waiting, builds are prioritized by the likelihood they are needed, [53 % less CI, 37 % less wait](https://www.uber.com/en-UG/blog/slashing-ci-costs-at-uber)). Taken: the train becomes that queue; changes whose affected sets are disjoint (wave 3's graph, wave 4's Gazelle graph) are verified and merged independently, the rest speculatively stacked, with the window sized to the measured failure rate.
- *Continuous post-merge verification with culprit finding* ([Google TAP, "What Breaks Google?"](https://research.google/pubs/what-breaks-google/); [flake-aware culprit finding](https://research.google/pubs/flake-aware-culprit-finding/): Bayesian noisy bisection over the commit range, logarithmic builds even with flaky tests; Chromium's [LUCI Bisection](https://chromium.googlesource.com/infra/luci/luci-go/+/312accacda67/bisection)). Taken: `gate-noite` and ADR-33's end-of-day battery are replaced by a loop on the runner that, whenever it is not serving a PR, verifies the newest commit of the base in full (every category, every browser project, cache-assisted so it costs the delta since the last verified commit); a red result bisects the range with flake-aware culprit finding and ejects or reverts the culprit through the train.
- *Every scan continuous and complete*: the history secret scan runs on each new base commit's range as it lands (the whole history is then covered at every moment, never "tonight"); a full-history rescan only when the scanner or its rules change.
- *Predictive ordering, never predictive skipping* ([predictive test selection](https://launchableinc.com/what-is-predictive-test-selection)): the affected tests run most-likely-to-fail first so a red verdict comes early; every affected test still runs (Daniel's rule: no coverage skipped).
- *Flakes*: detected by reruns at the same input and attributed by culprit finding; never quarantined (Daniel's rule), fixed by their owner.
Commits:
20. ADR-43 (supersedes ADR-33): continuous verification, the speculative queue and culprit finding; the `gate-noite` contract becomes the continuous loop's contract.
21. The continuous verifier: a runner job kind `verify-base` that the runner takes whenever idle, verifying the newest base commit in full with the content-keyed caches, publishing `base.verified`/`base.red` per commit.
22. Flake-aware culprit finding over a red range (noisy bisection with the measured flake rates), ending in the train's ejection or revert of the culprit.
23. Continuous scans: the history secret scan of each landed range; the full rescan on a scanner or rules change.
24. The speculative queue: independent changes (disjoint affected sets) verified and merged in parallel, the rest stacked speculatively with an adaptive window; predictive ordering of the affected tests.

**Onda 6 — capacity for 1,000 PRs a day on free compute (D-097).**
At 0.25 sustained vCPU the e2-micro has about 21,600 CPU-seconds a day: about 21 CPU-s per PR for the presubmit verdict, the queue and the continuous verifier together. The wave measures the CPU-s per verdict on the VM after waves 1–5 and closes the gap only with free compute:
25. Measure: CPU-s, wall and memory per verdict and per base verification on the VM, over a day of real traffic; the capacity ceiling (PRs a day) published by `scripts/service metrics`.
26. Admission and backpressure: the queue admits at the measured capacity and reports the wait; nothing is dropped.
27. More free runners through the control plane's claim (ADR-41): any free-tier machine joins as a runner; a paid machine or a paid cache appears only as a proposal with its cost for Daniel (D-093).

**Onda 7 — answer per PR well below 1 s (Daniel 13:15 and 13:18 BRT, D-104; after wave 6).**
Targets on the e2-micro runner: 0.1 s for the typical PR (a small change, only affected unit tests), below 1 s for most, at most 10 s for the worst case; measured there and recorded.
State of the art: *preloaded fork servers* (Android's Zygote, Ruby's Spring and Zeus, Nailgun for the JVM): one process pays the interpreter and the imports once and forks a fresh child per run, so each run starts warm and isolated; *watch-mode runners* (Jest and Vitest watch: a file watcher plus the module graph re-run only the affected tests in milliseconds; [Watchman](https://facebook.github.io/watchman/) gives a change journal without asking git); *per-test impact from coverage* ([pytest-testmon](https://testmon.org/): each test's executed lines select it). Bazel's persistent workers serve build actions, not tests, as Daniel noted.
Chosen design (to be measured before adoption): a resident test server on the runner, a zygote that has imported the engine's modules and the test fixtures, receives the affected tests of a head and forks one child per batch, so dirty state never survives a run (the child exits). Selection comes from the content keys and the inferred graph (waves 1–4), changes from an inotify journal of the checkout (no git call on the warm path), and results stay in memory with the keys. The full verification stays hermetic and separate (the continuous `verify-base` of wave 5, fresh processes). Commits:
28. Measure the floor on the e2-micro: a minimal git call, a fresh interpreter, the engine's imports, a trivial test in a live process, a fork from the zygote, an inotify event (D-104 records them; 4-vCPU container numbers are context only).
29. The zygote test server (`scripts/test-server`): preload, fork per batch, a unittest runner in the child, results with their keys in memory; a check that a child's mutations (environment, cwd, modules, temp files) never reach the next run.
30. The runner's warm path: inotify journal → keys → affected tests → zygote, answering a head in the PR gate; the verdict cites it as the warm result of the same keys.
31. Measured: p50, p95 and the worst case per PR class on the e2-micro, against 0.1 s, 1 s and 10 s.

**Onda 8 — compiled hot code, only where measurement says (Daniel 13:16 BRT, D-104).**
Candidates weighed: [mypyc](https://mypyc.readthedocs.io/) (compiles type-annotated modules to C extensions; mypy and Black ship with it, about 2–4× on their own code), Cython (larger gains with C types, more rewriting), Nuitka (whole-program; little gain on startup-bound runs). Plan: a CPU profile of the warm path and the gate's Python stages on the e2-micro first; compile only stable, hot, pure modules (candidates from this unit's profiles: glob matching and key hashing in `gate_test_cache`, the AST walks of the literal census); a C toolchain is pinned in `scripts/cloud/toolchain.json` like every tool; if the measured gain does not pay for the build step, the measurement goes in a D-xxx and nothing is compiled.
32. Profile on the e2-micro; the candidate list with seconds each.
33. Compile with the tool the profile favours (mypyc by default), behind a switch, the pure-Python module kept as the fallback; measured before and after.

**Onda 9 — 10 ms in the best case (Daniel 13:23 and 13:26 BRT, D-104).**
Floor measured on this session's 4-vCPU container (context; the e2-micro's is item 28): `git status`/`git diff` 6–7 ms in this repository, a fresh Python 13 ms (`-S` 11 ms), importing `config` 40 ms, a trivial unittest in a live process 0.05 ms, a file `stat` 0.001 ms, fork plus exit from a live process 1.5 ms. So 10 ms is out of reach for anything that starts a process or calls git; it is reachable only on the warm path with no process start: an inotify event, the keys of the touched files, the affected tests run in the live server, the result answered from memory. Whether the forked isolation of wave 7 fits inside 10 ms on the e2-micro is measured in item 28; if it does not, the best case runs in the live process with an in-process reset, and the 10 ms answer is reported as "warm, in-process", never as the hermetic verdict.
34. The best-case path: watcher event → in-memory keys → affected tests in the live server → answer; measured on the e2-micro (p50, p95), reported against 10 ms with the reason when it is not met.

**Retro (plan item 8).** `retro.md` (written at the session stop of 30/10, #820) is rewritten as the final retro after wave 9, then the train.

## Commits
The waves above are the commits, in that order; each owns its files and none runs in parallel with another.

## Premises
Premises: P-46, P-56
- P-46 (the pinned gate judges with the base's tooling): radius high (every gate). Not changed: this PR's speed-ups
  apply from the next PR; this PR's own numbers come from the head's advisory run and from local runs, labelled.
- P-56 (a content-keyed result is the answer for the same input): radius high. Commit 3 relies on it; a key that
  cannot be computed runs the test.

## Tests
Per commit, the owning script tests (`scripts/tests/covers/*.json`) plus the new cases; each head through the normal
gate (`scripts/gate-verdict --head <sha> --pr 815`). The whole suite cold and warm with the measurement harness of the
audit, before and after commits 1–3.

## Base defects expected
None known.

## Cheapest useful effort
Action: change only the mechanisms the audit measured (configuration replay, git spawns, keying, scans, the report's reads), one gated commit each
Cost: one long session, about twenty commits in four waves, one gate per commit, a few hundred REST calls; free compute only (the VM, Always Free)
Requirement: Daniel, who wants the whole suite in at most 10 s on A Torre's runner and the gate about 60 s from push to verdict (30/10 10:43 BRT)
Cheaper rejected: a bigger machine (free tier only); deleting or quarantining slow tests (checks keep their meaning); raising the gate's bounds (no loosening); stopping at the class fixes and leaving the state of the art to follow-up units (Daniel 11:47 BRT: the world standard now)
