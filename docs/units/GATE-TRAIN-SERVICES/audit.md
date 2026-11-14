# GATE-TRAIN-SERVICES — audit

Stage 3 of the unit flow (D-077), read-only and cheap evidence; it follows #810's intent (D-081, open): a chain of whys
from each symptom to a structural root. It builds its own questions and does not dictate the plan.

## Entradas
- [intake.md](intake.md): the real problem (every verdict and merge needs a live AI session) and targets T1–T8.
- [research.md](research.md): the state of the art (webhook receiver + single-writer queue + disposable runners +
  health/metrics conventions) and the ambition ladder.

## Findings
1. **Nothing but the author session starts a gate.** `.githooks/post-commit` pushes the commit (`push_guard.py hook
   post-commit`) and `.githooks/pre-push` runs `scripts/commit-check --local`; no hook, ref or service starts
   `scripts/gate-dev`. The gate's record root is the invoking checkout (`scripts/lib/gate_pin.py` docstring, step 3).
   This PR's four gates were each started by this session (gate logs, 04:31Z–04:53Z).
2. **The train runs only while one Claude Code session keeps it alive.** `scripts/lib/train_serve.py` (docstring:
   "started in the background of the designated train-role session only"), `train.serve_max_s` 6600 s so the process
   exits below the 2 h background limit and the session restarts it (P-55, status `to-validate`, radius low);
   train.md "The coordinator starts it, watches its heartbeat and restarts it". The lock
   owner is `train@<session id>` (`train.session_id_env`).
3. **Green to merged is minutes, mostly not trigger latency.** #809 `gate.passed` 03:19:48Z → `pr.merged` 03:38:36Z
   (18 min 48 s); #804 02:49:02Z → 03:13:24Z (24 min 22 s); both merged as tier-2 batches (`b-2912cc8040dc`,
   `b-48fa829eacc5`: tier 2 of 4 min 41 s and 8 min 48 s on #548). #804 needed six green verdicts and four
   `pr.conflicted` round trips (7 h 25 min). Strict verdict merges exist (`v-0630ce8eaf14` #807, `v-c2453be0df00` #813).
4. **GitHub reads per gate are 3.5× the bound, and #548 is most of them.** Gate 1 (`4cd47abe`): `forge: 7 writes, 204
   reads (... 60 reads)`; gates 3 and 4: 212 reads. Of gate 1's 333 calls, 191 counted reads and 118 conditional `304`s
   are `GET /issues/:id/comments` pages (`.gate/records/reports/4cd47abe…/dev-20261030T043158/forge-count`): the
   21-page channel is read about 15 times per gate.
5. **Ten modules read the whole repository channel; the window equals the stopgap cap.** Whole reads:
   `defects.py:366`, `defect_detect.py:208`, `slo.py:177`, `program.py:292`, `plan_triage.py:400`, `quarantine.py:166`,
   `battery.py:159`, `gate_flake.py:145`, `gate_test_cache.py:129` (file log only: `forge-events.file_kinds`), and the
   newest-window reads (`config.py:78`, `quarantine.py:105`, `train.py:261`/`459`, `train_verdict.py:513`) size their
   window with `forge-events.github_max_pages` (`forge_github.py:109-118`), which the D-072 stopgap set to 200: every
   "window" is the whole channel (2,062 comments, 21 pages, 30/10 05:00Z).
6. **Wall time is cold-cache time.** Pinned stage span: gate 1 (cold) 288 s, script tests 263 s; gate 3 (warm) 110 s,
   script tests 89 s; gate 4 60 s of script tests. The selection ran 10 stages (scripts-only diff). End to end with the
   pin and the advisory run of the head's tooling: 11 min 27 s, 5 min 46 s, 4 min 47 s; push → `gate.passed` on gate 3
   was 2 min 13 s (04:45:52Z → 04:48:05Z). The 278–345 s Daniel measured is the cold path.
7. **No status, health or metrics surface; state is scattered.** Operational state lives in PR comments (the
   `gate-status v1` live panel), #548 events (106 of the newest 162 are `slo.breached`), git refs (`train/lock`,
   `train/wake`) and container-local files (`.gate/records/reports/<sha>/…`, `.gate/train/*.log`) that vanish with the
   container. `scripts/train queue` is a read-only replay over REST. `budget.measured` shows the train's last run at
   130 REST calls against `train.rest_calls_per_run_max` 20 (04:07:25Z). `gate.passed.cost.wall_s` carries an epoch
   (`1793325760.494` on #809) instead of a duration.
8. **Controls exist only as switches.** `train.enabled`, `train.trigger_mode`, `train.admit_mode` and friends go through
   `scripts/config set` (shared store, `config.changed` on #548, D-069 item 5). There is no requeue (a new push and gate
   is the only way) and no cancel; nothing records who ran a gate or a train run, or why.
9. **ADR-24 forbids GitHub Actions, enforced three times.** [ADR-24](../../adr/ADR-24-local-gate-no-github-actions.md)
   (14/10: the free minutes ran out and merging stopped), the gate stage `no GitHub Actions workflows`
   (`scripts/gate-local:367`), the vitest guard `apps/web/src/site/domain/no-github-actions.test.ts`, and
   `.claude/settings.json` denying sessions any write to `.github/workflows/**` (`test_claude_settings.py:45`).
10. **Platform limits measured from here.** The default branch is `main` (REST), which only moves at a frozen release
    (D-054), so `workflow_dispatch`, `repository_dispatch`, `schedule`, `issue_comment` and `workflow_run` cannot start
    a workflow that lives on `mod/roadmap-integration` (research); the pinned gate (P-46) judges this PR with the base's
    rules, so no rule this PR changes applies to its own heads; the proxy refuses the Actions REST paths and GraphQL;
    `developers.cloudflare.com` does not resolve here.
11. **Hosted Actions minutes cannot carry the flow for free.** 13 merges between 29/10 16:50Z and 30/10 03:39Z on #548
    (about 25 a day), with 4–8 gates per merged PR (#804: 8 gate events, #809: 4) is 100–200 gates a day; at 5–12
    minutes per gate on a 2-vCPU hosted runner (a 2.2 min warm and 6.5 min cold pinned run here on 4 vCPUs, plus setup),
    that is 15,000–72,000 minutes a month against 2,000 free (Free plan): 7–36 times the quota, the 14/10 failure again.
12. **`pr.ready` has no notion of a draft.** A green head whose listed plan items are all ticked emits `pr.ready` and
    wakes the train (gates 3 and 4: `train: woken over train/wake ... the train-role session admits #814`); the forge
    refuses to merge a draft (`Train.refused` keeps it queued, `train.py:200-218`).
13. **Red without a code cause** (fixed by this PR's commits 1–3): GX-23's per-process attestation (D-082), the
    self-host leg's last-line reason (D-082), `gate-isolation.test.sh` stale since #804, `test_battery.py` reading the
    live shared store.

## Causas raiz
Chains of whys from the findings to a structural root (D-081, Padrão v7):

### R1. No execution plane outside AI sessions (findings 1, 2, 9, 11)
Cadeia de porquês:
1. Por que todo veredito precisa de uma sessão? Only the pushing session starts `gate-dev`.
2. Por que só ela? ADR-24 moved every check "to our box" and removed Actions after the minutes ran out, and nothing took over the *trigger*: the box is a person's machine.
3. Por que as sessões preencheram o vão? They are the only always-available compute with credentials, so the gate and the train (GATE-ON-PUSH's `serve`) were bound to them.
Classe: arquitetura/desenho
Raiz: compute and trigger belong to the sessions; there is no runner a session does not host.

### R2. The event's consumer is bound to its host (findings 2, 10)
Cadeia de porquês:
1. Por que um wake fica sem dono? Its only consumer is a process inside one session that must be restarted every 110 minutes.
2. Por que só esse processo consome? The wake protocol is host-agnostic (git refs, no REST), but the consumer was written as a session loop, not a service.
3. Por que nada mais o serve? The transport is a protocol; the consumer is not, so no other host can run it.
Classe: arquitetura/desenho

### R3. No component owns the operational state (findings 7, 8, 12)
Cadeia de porquês:
1. Por que não há status nem ação de admin além de um interruptor? Each script recomputes what it needs from the log.
2. Por que recomputar não basta? The log mixes records with noise (`slo.breached`), so there is no place to put "draft, hold".
3. Por que ninguém guarda o estado? State is a by-product of scripts, not a service's responsibility.
Classe: mecanismo faltando

### R4. An append-only log without a shared reader (findings 4, 5)
Cadeia de porquês:
1. Por que cada leitura ficou cara? Every reader replays #548 in every process.
2. Por que a janela virou o log inteiro? The windowed reads share the cap's value, so raising the cap to survive made every window the whole log.
3. Por que não há leitura compartilhada? There is no read model and no cache of the immutable pages (the GATE-ON-PUSH retro's lesson (a)).
Classe: mecanismo faltando

### R5. Tests and keys bound to mutable ambient state (finding 13)
Cadeia de porquês:
1. Por que os testes mudam de resultado sem mudança de código? They read per-process attestation, the live shared store, or a literal registry value.
2. Por que leem estado ambiente? Each test was written against what it found on the machine, instance by instance.
3. Por que isso se repete? The hermetic-test rule (D-069 item 12) is not yet enforced; fixed per instance here.
Classe: regra faltando

## Distância do estado da arte
- **Have:** the not-rocket-science rule (the train merges only a head proved on the tip, D-075/D-078/D-079),
  content-addressed reuse of results (D-076, Bazel-like but per machine), events as the record, git-based lock and wake
  with no REST polling, switches in a shared store with an audit trail (`config.changed`), rate events.
- **Missing:** an always-on receiver of forge events with a durable single-writer queue (Zuul's scheduler, Mergify's
  control plane); runners that no AI session hosts; one status/health/metrics surface and requeue/cancel actions; a read
  model of the log; a result cache shared across runners.
- **Rung:** 0 of research.md's ladder. GATE-ON-PUSH climbed its own first rung (the wake), still inside a session.

## Base defects expected
- #810 (D-081) is open: `docs/domain/DECISIONS.md` conflicts when it lands; resolved by merging the base (merge commit).
- The train retries this draft after each green head and refuses the merge (finding 12); harmless, a few REST calls.
- Overlap warnings (prepush): `scripts/gate-local` with #683 (GS2), `DECISIONS.md` with #768 and #810.
- `slo.breached` floods #548 (finding 7); owner: the SLO unit, not this one.
