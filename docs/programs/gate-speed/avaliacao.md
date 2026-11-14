# gate-speed — avaliação

Program GATE-SPEED under Padrão v8 (D-115). It resumes the unit [docs/units/GATE-SPEED](../../units/GATE-SPEED/retro.md)
(waves 1–9, D-090–D-104, #815–#821) and keeps everything there that still holds.

## Pedido
Daniel, 30/10 23:10 BRT: all tests run in at most 10 s on the e2-micro runner; ideal 1 s; over 1 s is only a warning;
tests run in parallel. Total autonomy over test structure, folders, code and doc standards; never delete, skip or weaken
engine coverage or thresholds to hit a number. His lesson: GATE-SPEED was framed as "speed up the gate" when it is a
whole test-management system (selection, cache, parallelism, structure, coverage, flake handling, measurement), and
coverage was missed because there was no diagnóstico. 23:11: measure in the session container, every phase; the
e2-micro validates once, at the end, when the suite is close to 1 s here. 23:14: no wait for approval; the phases run
overnight, each merged by the train, until a stop criterion (D-NNN) or the retro.

## Sintoma
- A change waited minutes for its test verdict: 36 min 47 s on the VM (30/10 morning), 157–564 s per gate in a
  container after waves 1–R. The whole script suite cold took 468 s and 805 CPU-s on 2 CPUs before GATE-SPEED.
- Nobody knew the suite's coverage. No step measured it, so a speed-up could drop coverage and no number would move.
- Flakes were seen (TX32 timeout under load, `push-guard.test.sh` once) and handled one by one, never as a rate.

## Sistema que falhou
The test-management system: the one system that, for each change, decides which tests must run (selection), answers
the rest from trusted results (cache), runs what remains in parallel and cheaply (execution), keeps tests fast and
hermetic by construction (structure), proves the suite still checks what it checked (coverage, counts), separates
flakes from failures (flake handling) and measures all of it every time (measurement).

It exists in parts, built as gate speed-ups and not as one system with its own metrics: content keys (D-093), selection
by covers and readers (D-102), the hermetic rules, the defect register, `scripts/test-suite`. So it is an existing
system to improve. Two of its parts do not exist and must be built: coverage measurement and a cost budget per test.

## Sistema ideal
From first principles a test verdict is a pure function of the inputs the test reads. Therefore:
1. Every test's inputs are known (declared, then verified by a tracer); a change selects exactly the tests that read it.
2. A result for the same inputs is computed once (content-addressed), and later on any box.
3. What must run, runs on every core at once, longest first, and no single test is longer than the target; process
   start-up and imports are paid once (a warm interpreter forks per test), not per test.
4. A test costs what its assertion needs: in process and in memory; it spawns git or a shell only when that process is
   what it tests; fixtures are built once and copied.
5. Coverage, test count and flake rate are measured on every change and never go down; a test that passes only on a
   rerun is a flake with an owner, never a silent pass.
6. Measurement is one command, the same on every box; a slow box validates, it is not the lab.

Result: the whole suite cold in about 1 s on a 4-vCPU box and under 10 s on the e2-micro, and a typical change's
verdict well under 1 s from cache and selection. Raised by D-134: the whole suite with no store at all in about 1 ms
here (about 100 ms on the e2-micro), a test a function call on values already in memory in one warm process, the real
effects judged in a small separate integration layer.

## Distância
| Part | Today | Ideal |
|---|---|---|
| Selection | covers and readers (D-102); read tracing is report-only | traced reads enforced |
| Cache | content keys per box (D-093) | shared between boxes |
| Execution | 95 shell scripts on 4 workers; the longest script bounds the wall | per-test parallelism, warm fork server |
| Structure | most Python tests start a process, and many a git repository, per case | in process, in memory, fixtures copied |
| Coverage | never measured | measured every phase, never lower |
| Flakes | the gate's base re-run classifies one red at a time | a measured rate, each flake owned |
| Measurement | `scripts/test-suite` prints the wall | one command for the main and every guard metric |

## Painel
Objective: every verdict about a change is right and fast on any box, with or without results kept from before
(Daniel, 31/10 11:02–11:10 BRT, D-133); first in the session container, then carried to the e2-micro, the final
destination (Daniel, 31/10 12:36 BRT, D-134).

| Metric | Kind | Why it matters | Acceptable |
|---|---|---|---|
| `cold_wall_s` (with the shared cache: a box with an empty local store against the shared results) | main | what a fresh box, a session or the runner pays for a verdict | ≤ 10 s, ideal 1 s; 0.69 s after F10, kept |
| `uncached_wall_s` (the whole suite, no store at all, in the session container) | **main** | a cache that hides 100 s is no fast suite: "não adianta nada 1 s com cache e 100 s sem cache" | about 1 ms, the final target (D-134), by milestones 10 s, 1 s, 100 ms, 10 ms, 1 ms; 77.1 s after F11 step 2 |
| `gate_wall_s` (the whole gate, no store at all, end to end in the container: from the PR's event to its reported verdict) | complementary | what a PR actually waits for; the e2-micro's gate is the final destination, once the container reaches the target (D-134, 31/10 12:36) | falls with the main metric; about 91 s on #844 |
| `coverage_pct` | complementary | a faster suite that checks less is a worse suite | never lower than its baseline (89.69 %) |
| `test_functions` | complementary | no test deleted to go faster | never fewer |
| `failed` | complementary | a fast red suite proves nothing | 0 |
| the forge's round trips (`rest_calls` and their latency) | complementary | the part of `gate_wall_s` outside the box: each GitHub call is a network round trip | counted and timed apart; a measured floor if it is the last cost (D-134) |

## Painel final (D-136, 31/10 14:30 BRT)
Did the objective improve, or only the number? **Both, but not enough.** A fresh box against the shared results now
judges the whole suite in 1 s (169.1 → 0.99 s), and the e2-micro's gate reads those results since D-135, so the
common case, a change that touches few tests, is fast on every box. The case with no kept result at all, the one
Daniel named as the real objective, went from about 170 s to 74 s in the container, a factor of 2.3, against a target
of 10x per phase and 1 ms at the end. The program stopped there by Daniel's order (13:26 BRT), not at a physical
limit.

| Metric | Start (`c770ba2e`) | After F10 | After F11 | Target | |
|---|---|---|---|---|---|
| `cold_wall_s`, container, against the shared results | 169.1 s | 0.69 s | 0.99–1.02 s (3 passes) | ≤ 10 s, ideal 1 s | met |
| `uncached_wall_s`, container, no store at all | about 170 s | about 96 s | 74.0 s (median of 6; base of that hour 90.7 s) | about 1 ms (D-134) | not met: 2.3x since the start |
| `cpu_s`, uncached | 529.5 | about 320 | 229 (median of 6; base 301) | — | −24 % in F11 |
| `coverage_pct` | 89.12 % | 89.69 % | 89.69 % | never lower | held |
| `test_functions` | 2,337 | 2,378 | 2,384 | never fewer | held |
| `failed` | 0 | 0 | 0 | 0 | held |
| `gate_wall_s`, container, a docs-only PR | not measured | 16–91 s | 12–31 s with warm results (28 s on #845) | falls with the main metric | measured, not a target |
| the e2-micro's gate, whole, no store | not measured | not measured | 292–662 s on #838–#844 (0 hits); after D-135, same head twice: 364 s (0 of 5 hits), then 300 s (5 of 5; script tests 124 → 10 s) | ≤ 10 s (D-122), 100 ms (D-134) | not met; the shared results work there, the structure check (193–228 s) and schema compat (130–148 s) are now the gate |
| the forge's round trips per gate | — | 19–22 calls | 18–23 calls | counted apart | the floor is unknown |

The container is the lab: its numbers move ±15 % within the hour, so every row is the median of interleaved passes
and each phase is judged against its own base measured the same hour. The e2-micro numbers are read from the
`gate.passed` and `gate.failed` events the runner publishes (`cost.wall_s`, `cost.cpu_s`, `cost.cache_hits`, each
stage's duration), not measured by hand.
