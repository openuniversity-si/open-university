# TRAIN-TEMP-FIX — audit

First measured by the first launch (session `01B2LxDVDe3V…`, 17:30–17:34 UTC, base `fab6e204d`) and taken here as
notes; every finding below was re-measured by this session (17:35–17:55 UTC, base `e8b74c581`) or is marked as not
re-measured. F9–F12 are this session's own.

## Entradas
- [intake.md](intake.md): the brief (the train stopped merging after #1081, 14:10 UTC).
- [research.md](research.md): how other merge queues surface a dead run.

## Findings

F1. **The base has not moved since `fab6e204d`.** `git log -1 origin/mod/roadmap-integration` = `fab6e204d`
(2026-11-02T11:09:54-03:00 = 14:09:54Z); `scripts/service status` lists the last merge as
`#1081 b-9e72d313817e at 2026-11-02T14:10:02.271Z`.

F2. **The wake log is not 160 records after 14:10. It holds 7** (the brief's lead refuted). Command:
`git fetch origin +refs/heads/train/wake:refs/tt/wake +refs/heads/train/lock:refs/tt/lock`, then
`git log --format=%cI refs/tt/wake --since=2026-11-02T14:10:03Z | wc -l` → `7` (tip `de0305e4e`, 16:14:45Z). In the
window 14:10:31Z–17:32:00Z `train/lock` holds **36 records = 18 take/release pairs** with zero merges
(`git log refs/tt/lock --since=… --until=… | wc -l` → `36`).

F3. **Every runner-VM run since 14:14 holds the lock for 2–4 seconds.** The take and release pairs on `train/lock`
(take sha → release sha), all owned by `train@<vm>:<pid>`:

| take (UTC) | take sha | release (UTC) | release sha |
|---|---|---|---|
| 16:30:29 (`expires 17:05:29.374Z`) | `3aa622efd` | 16:30:32 | `47616067c` |
| 16:45:46 | `0f22ef4ed` | 16:45:48 | `7ce50d6c2` |
| 17:00:47 | `a1e94f810` | 17:00:51 | `b87c0f795` |
| 17:15:54 | `5e3d51274` | 17:15:56 | `9f5cd564a` |
| 17:30:59 | `a390facd5` | 17:31:03 | `e35460f79` |

The same pattern repeats from 14:14:20 (`af2040b8e` → `d26e338b8`). The last healthy run had a different owner
(`train@grok-bot-vm-301145804:802992`, `5319c4f40` 14:09:15Z take → `017125f3f` 14:10:30Z release, with #1081 merged
in between). That run held the lock for 75 s.

F4. **Reproduced: with no events token, reading the queue raises.**
`env -u TOWER_EVENTS_TOKEN scripts/train queue` → exit 1 (re-run by this session at 17:35Z and 17:53Z),
`forge_control.ControlError: no events token: set $TOWER_EVENTS_TOKEN`. Stack: `train.py:579 main` →
`train.py:175 Train.queue` → `train_queue.py:153 QueueIndex.build` → `forge_events.py:498 ForgeEvents.read` →
`forge_events.py:266 RoutingAdapter.read` → `forge_control.py:61 ControlAdapter.read` → `forge_control.py:35 _call`.
On this base `forge-events.log_adapter` defaults to `control`
(`config/registry/forge-events/forge-events.log_adapter.json`, set by `46b29a5ba` "the diary returns to the control
plane", 2026-11-01 21:29 -03). The forge's other operations stay on `forge-events.adapter` = `github`, which includes
the lock. So the lock works without the events token and the log read does not.

F5. **The call path explains the 3-second pattern.** `engine_role.py:155` `LockedRole.run` takes the lock first
(`port.lock`, over git: `forge_git_ref`). `engine_role.py:158` then calls `self.drain(port)` → `train.py:401`
`entries = self.queue()` → the control-plane read of F4 raises. The `finally` at `engine_role.py:159–161` releases the
lock, and the exception leaves `train.py:main` uncaught. Its only trace is a Python traceback on the runner's stderr. Nothing on
the forge, the event log or the lock record names the cause. What survives is the take and release pair in
`train/lock`.

F6. **The runner VM is provisioned with `GH_TOKEN` only.** `docs/operations/services.md:38` installs `runner.env` with
"one line: GH_TOKEN=<the agent's fine-grained token>"; `services/runner/tower-runner.service.tmpl:12` reads that file;
`rg TOWER_EVENTS_TOKEN docs/operations services` finds nothing. **Not verified on the VM itself**: a session has no
cloud credentials and does not reach it (status.md). The hypothesis stands on F3 + F4 + F6 together.

F7. **`scripts/service status` reported 7 "woken, not merged" and only 2 were real** (first launch, 17:40Z). This
session re-ran the `fab6e204d` status in a throwaway worktree at 17:36:54Z (after #1084/#1083 merged): `queue: 5 woken,
not merged` — #907, #910, #956, #966 (all closed, never merged) and #1066. Its queue lists #907, #910, #956,
#966, #1066, #1084 and #1083. REST `GET /pulls/<n>` (2026-11-02 17:40Z): #907, #910, #956 and #966 are `closed`,
`merged=false`. #1066 is open but has no live `pr.ready`. `scripts/train queue` holds exactly
`#1084 af6c4300f… ready 2026-11-02T15:29:09.755Z` and `#1083 216eebe25… ready 2026-11-02T16:14:00.903Z`.
`service_status.py:136–137` filters a wake only by `pr.merged` in the window and `landed(sha)` (ancestor of the base).
A closed PR is never filtered, so it stays "woken, not merged" forever, and the queue check warns on the oldest
(`140228 s`).

F8. **A session holds both what the run needs.** This session has the repository, `GH_TOKEN`
and `TOWER_EVENTS_TOKEN` (presence checked, value never printed), and `scripts/train queue` reads both entries with
it. `train.admit_mode` = `batch`, so `bootstrap` (`train_verdict.py:212`) is off and a hand run takes only the live
queue. It never resyncs an open PR such as #1066.

F9. **#1084 and #1083 merged at 17:32Z, through the train, from a cloud session.** `train/lock` takes at 17:32:22Z
(`c6c007d71`), 17:32:28Z, 17:32:41Z and the release at 17:33:16Z (`dcf74b611`), owner
`train@cse_01B2LxDVDe3VXUj36wufvza9` (the first launch). `scripts/service status`: `merged: #1084 b-9ef10b2cc24c at
17:32:52.752Z`, `merged: #1083 b-9ef10b2cc24c at 17:32:54.831Z`; base tip `e8b74c581` (merge of #1083, parent
`850f8e3c0`, merge of #1084). `scripts/train queue` with the token prints nothing (17:35Z). A machine that holds the
token merges in one 54 s run, which isolates the stall to the VM's environment, not to the code or the queue.

F10. **The VM runner has not reached the control plane for ~41 h, and the CLI hid it.** `curl $service.control_url/status`
(17:51Z): `runners` holds `the-tower-runner` (kind `vm`) with `heartbeat 2026-11-01T00:14:56.751Z`, and the control
plane's own health warns `runner the-tower-runner: beat 149770 s ago`; `jobs` metric: 1101 queued. In the same moment
`scripts/service status` printed `control plane: runners=unknown, jobs=unknown` and no check about it
(`service_status.py:198–200` on `e8b74c581` hard-codes `unknown`; `contracts/service/status.v1.json` says the CLI does
not read those collections). After #1083 (D-290: the control plane is the runner's only job route) the VM stopped taking
the lock at all: the lock tip is still `dcf74b611` (17:33:16Z) at 17:51Z, where the 15-minute pattern of F3 predicts a
take near 17:46Z. So the VM went from dying in 3 s to doing nothing, both silently.

F11. **The status line printed a released lock as if it were held.** `service_status.py:341` on `e8b74c581` renders
`lock: {owner} until {expires or "released"}`, so the released record of F9 printed `lock:
train@cse_01B2LxDVDe3VXUj36wufvza9 until released` (17:35:27Z).

F12. **Two suites are red or slow on the base, unrelated to this unit.** `test_train_role.py`:
`RestBudget.test_the_run_publishes_its_rest_calls_against_the_budget` fails with and without this unit's diff (git stash,
17:44Z); `test_planner_role.py` did not finish in 600 s on this head (17:46Z); its base run is in
[status.md](status.md). Neither is in the brief's known-defect list.

F13. **R3 was already fixed on the base before this unit changed anything.** `5b23c44fe` (CONTROL-ROUTE, merged in
`e8b74c581`) makes the status queue "the control-plane queue minus PRs the forge reports closed". On `e8b74c581` at
17:35:27Z `scripts/service status` lists 3 entries, all open (#1066, #1082, #1085) and none of #907/#910/#956/#966.

## Causas raiz

### R1. A train run that dies leaves no durable cause
Cadeia de porquês:
1. Why did nobody know for 3 h why the train merged nothing? Each run died in 3 s, and the only visible trace was the
   lock's take and release pair (F3).
2. Why was there no other trace? `Train.run`/`LockedRole.run` releases the lock in `finally` and lets the exception
   escape (`engine_role.py:157–161`). `train.main` catches only `TrainHalt` (`train.py:583`).
3. Why is a traceback on stderr not enough? The runner VM's job output is on a machine that a session cannot reach
   (F6), and no event or ref records a death.
4. Why does no event record it? The train emits only success-path events (`train.batch.*`, `train.queue.*`). A
   failure event would have to go to the same log whose read is failing (`control`), and nobody designed a record
   that survives the failure of the event log itself.
Ramo 1b (the runner itself, after D-290):
1. Why was the VM's silence after 17:33Z invisible from a session? `scripts/service status` reports
   `runners=unknown` (F10).
2. Why unknown? The CLI reads the control plane's queue but deliberately not its runners nor its health.
3. Why does that matter? The only witness of a dead runner (its stale heartbeat) is then reachable only by someone who
   curls `GET /status` by hand.
Classe: mecanismo faltando
Evidência: `scripts/lib/engine_role.py:155–161`, `scripts/lib/train.py:583–587`, `scripts/lib/service_status.py:198`,
F3, F5, F10.

### R2. The log adapter moved to a transport that one of the runners cannot use
Cadeia de porquês:
1. Why does the runner VM's run raise? Its queue read goes to the control plane and it has no events token (F4, F6).
2. Why does the read go there? `forge-events.log_adapter` was switched to `control` in `46b29a5ba`. That key's own
   description says to switch it "once the control plane is deployed with EVENTS_TOKEN and the sessions hold the
   token". The sessions do. The runner VM was not counted.
3. Why was the VM not counted? No check ties a log-adapter switch to every consumer that reads the log. Preflight
   checks the machine it runs on, and the VM's `runner.env` is provisioned by hand (`services.md:38`).
4. Why is that a design issue? The train has one runner kind that is provisioned outside the repository, and the
   adapter switch has no inventory of who must hold the token. CONTROL-ROUTE (#1083) owns that route.
Classe: arquitetura/desenho
Evidência: `46b29a5ba`, `forge-events.log_adapter.json` description, `docs/operations/services.md:38`.

### R3. The status queue counts PRs that can never merge
Cadeia de porquês:
1. Why does status show 7 waiting when 2 are? Closed PRs keep their last wake (F7).
2. Why are they kept? `service_status.status` drops a wake only by `pr.merged` in the window or by ancestry in the
   base. A closed PR has neither.
3. Why was the PR state never read? The module reads only git refs, the event window and the runner file (its
   docstring), and the forge's change state was never one of its sources.
Classe: bug local
Evidência: `scripts/lib/service_status.py:136–137` (on `fab6e204d`). Fixed by `5b23c44fe` (#1083) before this unit
acted (F13); this unit only measures before and after.

### R4. The status line reads a released lock as held
Cadeia de porquês:
1. Why did status say the session held the lock after it had released it? The line prints `until released` (F11).
2. Why that wording? The renderer prints the owner of the last record whatever its state.
3. Why was it not caught? No test renders a released lock.
Classe: bug local
Evidência: `scripts/lib/service_status.py:341` on `e8b74c581`.

## Open questions
- Q1. That the VM lacks `$TOWER_EVENTS_TOKEN` (and, after D-290, the runner token) is inferred from F3+F4+F6+F9+F10,
  not observed on the VM. Only someone with access to the VM can read its `runner.env` and its journal.
- Q2. Why the VM's control-plane heartbeat stopped at 2026-11-01T00:14:56Z, a day before the log adapter question,
  is not explained by anything measured here.

## Distância do estado da arte
Merge queues such as GitHub's merge queue, Bors and Zuul record a failed queue run with its reason on the item or on
the queue (research.md). Our train records only success events, so it is on the lowest rung for failures.

## Base defects expected
The brief's known base failures (`pr-creation-path.test.sh`, `test_config_check.py::test_structure_check_fails_on_a_registered_literal`,
`test_structure.py` (28), `test_gate_forge_budget.py` (2), `test_preflight.py::test_pinned_vercel_cli_starts`,
`test_github_cli.py::test_the_cache_keeps_at_most_its_entries`). They are not in this unit's scope.
