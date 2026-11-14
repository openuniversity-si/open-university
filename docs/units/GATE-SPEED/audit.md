# GATE-SPEED — audit

Stage 3 of the unit flow (D-077, Padrão v7): read-only, cheap evidence. It builds its own questions from the intake's
problem, states causes by a chain of whys (D-081) and proposes no solution.

## Entradas
- [intake.md](intake.md): the real problem (the gate recomputes what did not change and pays a process and a git
  repository per test case, then as long again in its report) and targets T1–T6.
- [research.md](research.md): the state of the art (content-keyed results, diff-based selection, warm workers, a
  nightly full run as the safety net) and the ambition ladder.

Method. The VM numbers are Daniel's run on `the-tower-runner` (`scripts/gate-dev --pr 811`, 30/10 09:57–10:34 BRT)
read back from its `gate.failed` event and status comment on #811; this session has no shell on the VM (intake,
Lacunas). Everything else was measured in this session's container (4 vCPUs, 16 GB): the gate runs of this PR's heads
(reports under `.gate/records/reports/<head>/`), the whole script suite run once per test with a harness (all 111
`scripts/tests/*.test.sh`, two workers pinned to two CPUs with `taskset`, then four workers), a `sys.addaudithook`
tracer for every GitHub request (with its Python stack) and every `subprocess.Popen`, and `cProfile` of the structure
check. Container numbers are context: the e2-micro sustains 0.25 vCPU and bursts to two.

## Findings
1. **On the VM a docs-only head ran the whole script suite cold, and the stages alone took 16 min.** #811's
   `gate.failed` (`642e4e0d…`, 13:30Z): `selection.kind` `full`, `cost.cache_hits` 0 of 8, `cpu_s` 1,087; script tests
   703.8 s, secret scan (history) 191.2 s, structure check 153.8 s, PR metadata 111.0 s, secret scan (tree) 94.0 s,
   schema compat 39.4 s; status comment "Finished in 32m22s"; 36 min 47 s end to end with the report. The head was 84
   commits behind its base; the run was the VM's first, so its per-box caches were empty.
2. **The whole script suite costs about 805 CPU-seconds cold.** Harness, this container: 2 workers on 2 CPUs 468 s
   wall (629 s user + 175 s system); 4 workers 256 s wall (809 CPU-s). 111 scripts, 159 Python test files, 2,262
   test functions. Largest child process 179 MB. The nine heaviest scripts are half the time: `train` 78.5 s,
   `push-guard` 74.6, `structure-check` 74.4, `train-reuse` 53.3, `config` 47.9, `merge-phase` 40.4, `generate`
   37.0, `units` 36.0, `gate-db` 25.1; 40 scripts take under 2 s. At 0.25 vCPU sustained, 805 CPU-s is about 54
   minutes; at a full two-vCPU burst, about 7 minutes.
3. **Most of that CPU is git processes.** Python-level spawns per script: `train-reuse` 7,354 (all git, 6,172 of them
   `git show`), `train` 5,937 (5,900 git: 1,638 `rev-parse`, 560 `show`, 506 `fetch`, 323 `push`, 311 `commit`, 220
   `init`), `structure-check` 2,772 (2,684 git, 1,363 `show`, 78 runs of `scripts/structure-check` itself),
   `push-guard` 733, `units` 224. A gate run of this PR's third head made 1,667 spawns outside the tests' own.
4. **Production code reads git objects one process per object, with no memo.** `train_ownership.manifests` runs
   `git show <commit>:<path>` once per unit manifest (about 110) on every call, for an immutable commit
   (`scripts/lib/train_ownership.py:31-35`); in `train-reuse` the same 110 manifests were read 54 times each. The
   same shape: `census.py:138,175`, `gate_areas.py:96`, `gate_policy.py:48`, `plan_live.py:236`.
5. **A warm whole suite already exists per box, and costs seconds to key.** `gate_test_cache` keys each script test by
   the content of every file its covers name and answers a recorded PASS without running it
   (`scripts/lib/gate_test_cache.py:162-200`). Keying all 111 here: 4.75 s to load the map in a fresh process (the
   first `config.get` replays the shared store) plus 3.56 s to hash 1,908 files and compute the keys, each key
   matching every tracked file against its globs (111 × 3,491 files). The markers are per box with a TTL
   (`gate.test_cache_ttl_s`), so a fresh runner (the VM's first run) and the train's tier 2 (keys disabled,
   D-065 (5)) run everything.
6. **The structure check spends its time re-reading configuration.** `cProfile` of `structure.py --pr 815` (80 s under
   the profiler, 18–21 s in the gate): `config._overrides` 5,910 calls, 35.5 s cumulative, each replaying the shared
   store's events; `event_contracts.validate` 4,688 calls, 25.0 s, rebuilding the schema catalog by globbing the
   contracts directory twice per event (`catalog` 9,372 calls, 21.3 s; `event_contracts.py:36-42,73`); importing
   `commit_check` 14.1 s (module-level unit evaluation); three separate AST passes over the same scripts (literal
   census 8.5 s, vendor check 8.2 s, config secret findings 10.7 s).
7. **The time after the stages is three to four times the stages on a green docs-only head.** This PR's first head
   (`0cef25ef`, one line of `DECISIONS.md`): started 13:52:30Z, stages 13:52:42–13:53:16Z (34 s), `gate.passed`
   13:54:29Z, verdict answered 13:55:20Z: 12 s before, 34 s of stages, 124 s after. Daniel's #811 run: about 17 min
   of report, which re-ran the failing stages on the base (`defect_detect.py:1-20`: every failing test is re-run on
   the base in a throwaway worktree with its own install; resolved defects are re-verified on the base on every run).
8. **GitHub reads per gate are about twice the bound, and most are comment lists.** Head 1: 135 calls (104 counted
   reads, 24 `304`s, 7 writes; the gate prints "bounds … 60 reads"), 103 of them `GET …/issues/:id/comments`. The
   tracer on head 3 (133 calls): 105 comment-list GETs over 69 distinct issues: the known-defect router reads the
   comments of every open PR (`defect_router.queue`, `defect_router.py:35-44`, one read per open PR, 66 here), and
   #815's own list was read 23 times by separate modules in one process (`forge_events.read` from the status
   comment, carry, `pr_ready`, the router). #811 on the VM: 128 calls, 98 comment-list GETs.
9. **The secret scans start from nothing on a fresh machine.** `secret scan (history)` scans only commits after the
   last recorded base, else all of `HEAD` (`scripts/gate-local:307-308,357-365`, `gate_speed.py secret-plan`): the VM's first
   run scanned the whole history (191 s). `secret scan (tree)` copies every tracked file with `tar` into a temporary
   directory and scans it all on every run (`scripts/lib/gate-runner.sh:194-202`): 94 s on the VM, 3.6 s here.
10. **A registry key or a hook selects the whole battery.** This PR's second head (a registry key, a hook, two tests):
    selection `full`, every web stage, 531 s here, script tests 302 s (all 111). The fail-closed classes are
    `gate.full_battery_globs` (the registry, contracts, the engine, shared code, lockfiles; `gate_select.py:1-15`), and
    a script-test selection falls back to the whole suite for any uncovered `scripts/` path.
11. **The runner keeps the code it started with.** `scripts/service runner` refreshes its checkout to the base tip
    before train jobs but never re-executes itself (`service_runner.py:233-241`, the unit's `Restart=always` restarts
    it only when it exits), so a merged change to the runner reaches the VM only on a manual restart.
12. **Memory is not the limit.** VM peak 460 of 953 MB (Daniel); the largest test process here 179 MB.

## Causas raiz

### R1. The gate recomputes what did not change, and its memory of past answers lives on one box
Cadeia de porquês:
1. Por que um head docs-only roda 704 s de testes no VM? The selection was `full` and none of the 111 results was
   reused: 0 cache hits (finding 1).
2. Por que nenhum resultado foi reaproveitado? The per-test markers live in a per-box store with a TTL; the VM had
   never run a gate, and tier 2 never reads them (finding 5).
3. Por que o mesmo vale para os scans? The history scan remembers its last base in the same per-box way, and the tree
   scan has no memory at all (finding 9).
4. Por que a memória é por máquina? GATE-FAST built content keys as a speed-up of one box (D-076, P-56), with the
   shared store left for later (D-073); nothing made the answer "this input already passed" a property of the input
   that any runner can check.
5. Por que isso importa agora? The runner is a fresh, always-on, 0.25-vCPU machine: every cold start pays the whole
   factory's history, and a cold whole suite is about 54 minutes of its sustained CPU (finding 2).
Classe: arquitetura/desenho
Evidência: #811 `gate.failed` `642e4e0d…` (`cache_hits` 0, `selection.kind` full); `gate_test_cache.py:162-230`;
`scripts/gate-local:357-365`; `gate-runner.sh:194-202`.

### R2. A test or a module pays one process per git object or step
Cadeia de porquês:
1. Por que a suíte inteira custa ~805 CPU-s? Most of it is git processes: 7,354 in one script, 5,937 in another
   (finding 3).
2. Por que tantos processos git? Fixtures build repositories step by step (`init`, `add`, `commit`, `push` per case),
   and production modules read objects one `git show` at a time (finding 4).
3. Por que o código de produção lê assim? There is no shared reader of a commit's tree (one `cat-file --batch` or
   `ls-tree` per commit), and no memo keyed by the commit sha, though a commit never changes.
4. Por que ninguém notou? On a 4-vCPU box a git spawn costs milliseconds; the cost scales with the factory's size
   (manifests, events) and only shows on a small machine.
Classe: mecanismo faltando
Evidência: spawn counts (finding 3); `train_ownership.py:31-35` and the five readers of finding 4.

### R3. Reading a registry value replays a remote log
Cadeia de porquês:
1. Por que o structure check leva 154 s no VM? Its profile is dominated by configuration, not by checking (finding 6).
2. Por que a configuração custa? Every `config.get` replays the shared store's events into overrides and copies them
   (`config.py:446-470`); each replay validates every event against its schema.
3. Por que a validação é cara? The schema catalog is rebuilt by globbing the contracts directory twice per event
   (`event_contracts.py:36-42,73`), though the contracts do not change within a process.
4. Por que o desenho permitiu? The shared store (D-069 switches) was added behind the same `config.get` the code
   calls in hot loops, as if it were a constant read; nothing measures the cost of a registry read.
Classe: arquitetura/desenho
Evidência: `cProfile` of `structure.py --pr 815` (finding 6).

### R4. The gate's report runs the factory's chores on the verdict's critical path
Cadeia de porquês:
1. Por que o relatório leva mais que os estágios (124 s vs 34 s; ~17 min no VM)? After the stages, the run publishes,
   adjudicates known defects, re-verifies resolved defects on the base and routes defects (finding 7).
2. Por que isso fica no caminho do veredito? KD1 and TX11 were added as hooks of `gate_report` (D-069 items 4, 8, 9),
   so every gate pays them before it answers, and the base re-run needs a worktree and an install.
3. Por que tantas leituras do GitHub? Each module reads the PR's channel itself (23 reads of #815 in one process), and
   the router reads every open PR's comments to price a defect (finding 8).
4. Por que não há um limite que pare isso? The gate prints its 60-read bound but does not enforce it, and no component
   owns "read this PR's channel once per run".
Classe: arquitetura/desenho
Evidência: head 1 timeline and `forge-count`; tracer of head 3; `defect_router.py:35-44`; `defect_detect.py:1-20`.

### R5. The impact map is coarse where it matters most
Cadeia de porquês:
1. Por que uma chave de registro roda 531 s e toda a bateria web? The registry, contracts and engine paths are in
   `gate.full_battery_globs`, and an uncovered `scripts/` path runs every script test (finding 10).
2. Por que tão grosso? The map fails closed by design (GS1): a path whose readers are unknown runs everything, which
   is safe.
3. Por que os leitores são desconhecidos? A registry key names its readers (`x-readers`) and a test names its covers,
   but the selection does not use the readers of the keys a diff changes; it classifies the file.
Classe: regra faltando
Evidência: this PR's second head (`e52c650f`, selection `full`, 531 s); `gate_select.py:1-15`.

### R6. The runner cannot pick up its own fixes
Cadeia de porquês:
1. Por que a correção do User-Agent não chega ao VM no merge? The runner process keeps the code it started with
   (finding 11).
2. Por que? The refresh updates files for the jobs it starts, but nothing re-executes the runner when its own code
   changes, and `Restart=always` only acts on an exit.
3. Por que isso não apareceu antes? The runner was born in #814 and has never been updated in place.
Classe: mecanismo faltando
Evidência: `service_runner.py:233-241, 399-410`.

## Distância do estado da arte
- **What we have (rung 1–2 of the ladder in part):** content-keyed results per script test and per stage (D-076);
  a hand-written impact map (covers manifests, units, `x-readers`); diff selection for the web stages; parallel lanes;
  incremental history scan after a recorded base; a nightly full run (`gate-noite`).
- **What is missing:** results any runner can trust without having produced them (the answer is a property of the
  input, not of the box); keys computed once per run, cheaply, for the whole suite; tests that do not pay a process
  per git step; a registry read that is a constant read; a report that answers before it does chores; a channel read
  once per run; incremental scans by default; a runner that updates itself.
- **The physical floor on the e2-micro:** a cold whole script suite is about 805 CPU-s (finding 2), the web unit
  stage about 14–32 s and the e2e smoke about 40 s on four vCPUs here, a production build minutes; none of these can
  fit 10 s cold on 0.25 sustained vCPU. Only a warm answer (unchanged inputs judged by key, changed ones run) can.
  Bazel's state of the art makes the same trade: "whole suite" in seconds means whole suite *judged*, with the full
  cold run at night.

## Base defects expected
- None known that block this unit. The open drafts #796 and #793 touch the same area and are not edited.
