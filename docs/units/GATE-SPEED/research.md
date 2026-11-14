# GATE-SPEED — research

Stage 2 of the unit flow (D-077). Starts from the intake's real problem: the gate reruns work that did not change and
pays a process, an interpreter and a git repository per test case, on a machine that sustains a quarter of one vCPU.
Complete on its own; it raises no questions for the audit.

## Quem já resolveu
- **Bazel / Blaze (Google)** ([remote caching](https://bazel.build/remote/caching),
  [persistent workers](https://bazel.build/remote/persistent)): every action, a test included, is keyed by the digest
  of its command, inputs and environment (the action cache, content-addressed storage). A test whose inputs did not
  change is not run: its cached result is the answer. "Whole suite" in seconds means *whole suite judged*, most of it
  by cache. Persistent workers keep a warm compiler or test process across actions, cutting JVM/interpreter start-up
  (Bazel measured 4x and more on Java builds).
- **Google TAP** ([Memon et al., *Taming Google-scale continuous testing*, ICSE-SEIP 2017](https://research.google/pubs/taming-google-scale-continuous-testing/)):
  for each change, only the tests that transitively depend on the changed files run; the rest are carried. Most
  changes affect a small fraction of the 4.2 M tests.
- **Buck2 (Meta)** ([docs](https://buck2.build/docs/)) and **Pants** ([docs](https://www.pantsbuild.org/)): the same
  model (a dependency graph, content-keyed actions, a daemon that keeps the graph and the file watcher warm). Pants
  infers Python dependencies from imports, so a test reruns only when a module it imports changed.
- **Nx / Turborepo** ([Nx affected](https://nx.dev/ci/features/affected), [Turborepo caching](https://turbo.build/repo/docs/crafting-your-repository/caching)):
  "affected" projects from the git diff and the project graph; task outputs and logs cached by a hash of inputs; a
  cache hit replays the log in milliseconds.
- **Test impact analysis** ([Microsoft TIA](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/test-impact-analysis),
  [Datadog Intelligent Test Runner](https://docs.datadoghq.com/tests/test_impact_analysis/),
  [Launchable](https://www.launchableinc.com/)): per-test coverage maps from earlier runs select the tests a diff can
  affect; Launchable adds ML ranking. All keep a periodic full run as the safety net.
- **Fast suites in practice**: pytest-xdist (`-n auto`, one interpreter per worker, tests distributed), vitest
  `pool: threads|forks` with `isolate: false` for pure modules, Jest workers; nailgun-style daemons (a JVM or
  interpreter kept warm, tests run in-process); Stripe and Shopify report suites of tens of thousands of tests kept
  under minutes by selection plus caching plus massive parallelism, the parallelism being what a free machine lacks.
- **Incremental secret scanning**: gitleaks `--log-opts="<base>..<head>"` (scan only the new commits) and
  `gitleaks dir` on changed files ([gitleaks](https://github.com/gitleaks/gitleaks)); GitHub push protection scans
  only pushed commits.
- **Fast PostgreSQL tests**: template databases (`CREATE DATABASE … TEMPLATE`, a copy in tens of ms), one
  transaction per test rolled back, `fsync=off`/`synchronous_commit=off`/unlogged tables for disposable test
  clusters ([PostgreSQL docs, non-durable settings](https://www.postgresql.org/docs/current/non-durability.html)).
- **Hermetic fixtures**: one fixture repository built once and cloned (`git clone --shared`/`--reference`, or
  `cp -a` of a template), repositories on tmpfs, in-memory doubles of git for logic that only reads refs.

## Estado da arte
- **Standard:** a content-keyed result cache per test (key = digest of the test's own files, everything it reads, the
  tool versions), a diff-based selection for what runs, parallel workers sized to the cores, and a full run on a
  schedule (nightly) as the safety net. A warm "whole suite" is a key computation plus a cache lookup per test:
  milliseconds each.
- **Most advanced:** a dependency graph inferred from the code (imports, file reads), a daemon that keeps it and a
  file watcher warm so the keys are known before the push, remote execution across many machines, and per-test
  impact analysis. A change then costs only its own tests, in parallel, in seconds.
- **What each requires:** the standard needs an honest key (every input of a test in it, or a hit can hide a break) and
  a store; the advanced needs a build graph (BUILD files or inference) and, for remote execution, paid machines.

## Encaixe em nós
- **Copy directly:** content-keyed results already exist (GATE-FAST, D-076, P-56: script-test and stage keys in
  `gate_keys`), and the script-test map selects by diff (`scripts/tests/covers/*.json`). What is missing is making the
  *whole* suite answerable from the cache cheaply (one process computing every key, not one per test) and keeping
  the cache warm on the always-on runner.
- **Copy directly:** incremental gitleaks over `<base>..<head>` (the gate already narrows a history hit; the scan
  itself can start narrow), and a tree scan of the changed files only, both with the full scan kept for the nightly.
- **Adapt:** persistent workers: one warm Python process that runs many `unittest` files in-process (imports paid
  once) instead of one interpreter per file and per scenario; Bazel's worker protocol is more than we need, a pool of
  forked workers over `unittest` discovery is enough on 2 vCPUs.
- **Adapt:** hermetic fixtures: a template repository built once per run and copied per case, instead of `git init`
  plus commits per test; tmpfs where the VM has room (953 MB: careful).
- **Adapt:** TIA in its simple form: our covers manifests are a hand-written impact map; an import-graph check can
  refuse a manifest that misses a module its test imports, so selection stays honest.
- **Does not fit:** remote execution and bigger machines (free tier only); Launchable/Datadog (paid, external data);
  Bazel/Buck2/Pants wholesale (a rewrite of the factory's build around BUILD files; the cost far exceeds the gain at
  this size).

## Escada de ambição
1. **Minimum useful step now:** a docs-only change runs no suite at all; the report never reruns stages on the base
   and reads GitHub a bounded number of times; secret scans cover the new commits and changed files only (the full
   scans stay at night). This alone takes the VM baseline from 36 min toward a few minutes.
2. **Then:** the whole script suite answered by content keys in one process, warm on the runner (T1 warm), and the
   heaviest tests made cheap (in-process instead of a subprocess per scenario, a template repository instead of
   `git init` per case).
3. **Then:** a warm runner that pre-computes keys and runs the affected tests as soon as a head appears; a shared
   result store between boxes (D-073).
4. **State of the art:** an inferred dependency graph per test and a daemon with a file watcher; out of reach on free
   tiers only for remote execution.
