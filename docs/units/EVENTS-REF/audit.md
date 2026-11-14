# EVENTS-REF (E1) — audit

## Entradas
- [intake.md](intake.md): the order, the channel's measurements and the problem in one sentence.
- [research.md](research.md): NoteDb's shape (one ref, one commit per append, fast-forward as compare-and-swap).

## Findings
1. Every kind not in `forge-events.file_kinds` is a GitHub comment: `adapter_from_config` builds the `github` adapter and routes
   only `engine.step.measured` and `gate.started` elsewhere (`scripts/lib/forge_events.py`, `adapter_from_config`;
   `config/registry/forge-events/forge-events.file_kinds.json`).
2. The repeated state kinds are the bulk of the channel: 79 % of 1292 comments on #865 (intake, A Torre's count).
3. A comment is a REST write, and the write budget is a state file per session (`scripts/lib/forge_rate.py`, 20/min, 300/h),
   while GitHub's secondary limit is per account: N sessions write N times the budget.
4. The engine already has a REST-free writer: `forge_git_ref.GitRefs.append` advances a log ref by fast-forward, used for
   `train.wake_ref` (413 commits), with no comment ceiling and no secondary write limit (`scripts/lib/forge_git_ref.py`).
5. No adapter of the port writes to a ref: `ADAPTERS` holds `file` and `github` only. The file log is local to one checkout,
   so it cannot carry state between the lanes, the train and the runner.
6. A read without kinds returns every log of a channel (`RoutingAdapter.read`); a read with kinds reads the one log that holds
   them all (`ForgeEvents._source`), so a kind moved to a new log is read from it alone.

## Causas raiz

### R1. The heartbeat and the record share one store
Cadeia de porquês:
1. Por que o canal encheu e o GitHub recusou escritas? Because 70 comments an hour, 269 at the peak, went to one issue.
2. Por que tantos comentários? Because every state change of the train, the SLO checker and the defect loop is an event, and
   every event is a comment.
3. Por que todo evento é um comentário? Because the port has one remote adapter, GitHub comments, and the routing table
   lists the exceptions that leave it, not the kinds that belong on it.
4. Por que não há outro destino remoto? Because the git-ref writer was built for the lock and the wake ref (D-070) and was never
   made an adapter of the event port.
5. Por que isso importa? Because the record people read inherits the volume and the limits of the heartbeat.
Classe: arquitetura/desenho
Evidência: findings 1, 2, 4 and 5.

### R2. The write budget is counted per session, the limit per account
Cadeia de porquês:
1. Por que 30 POSTs seguidos foram recusados? Because GitHub's secondary limit was reached.
2. Por que o orçamento local não evitou? Because each session holds its own budget (20/min) and several sessions wrote at once.
3. Por que o orçamento é por sessão? Because `forge_rate` keeps its state in a file of the session's home, and no process owns
   the account's writes.
Classe: mecanismo faltando
Evidência: finding 3; `docs/operations/incidents.md` already names the write queue (lane 6) as not built.

## Distância do estado da arte
We have NoteDb's writer (create and fast-forward of `refs/heads/*`) and a routing port. Missing: the adapter that puts the port
on that writer, and the routing that sends the state kinds there by default. We stand at rung 0 of the ladder; this unit is rung 1.
R2 (the account's single publisher) is rung 2, unit E2.
