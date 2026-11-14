# CONTROL-CHANNEL (CANALE7) — audit

## Entradas
- [intake.md](intake.md); [research.md](research.md).

## Findings
1. The control plane has no engine-event route (`handle` in `services/control-plane/src/core.js`).
2. Its storage is one dump of seven keys; an event log there would outgrow a stored value.
3. `adapter_from_config` builds `github` or `file`; no remote adapter but GitHub exists (`scripts/lib/forge_events.py`).

## Causas raiz

### R1. The engine's only remote log is GitHub
Cadeia de porquês:
1. Por que o fluxo para quando o GitHub recusa? Because every event append is a comment.
2. Por que comentário? Because GitHub is the port's only remote adapter.
3. Por que o control plane não serve? Because it was built for GitHub's webhooks and the runner, with no route for the engine's
   own events.
Classe: arquitetura/desenho
Evidência: findings 1 to 3.

## Distância do estado da arte
We run the single writer (the Durable Object) and the port; missing are the route, the per-record storage and the adapter. Rung 0.
