# CONTROL-CHANNEL (CANALE7) — intake

## Pedido
Daniel, 01/11 15:43 BRT: "Nada pode depender, se comunicar com exceções, do GitHub. Nem publicação, nem nada ... A gente precisa
de um canal de monitoramento, controle e comunicação pra cada uma das seções." The design is A Torre's
`/workspace/torre/redesenho-canal/e7-sem-github.md` (what exists and what is missing, measured 15:49 BRT). Acceptance: with
api.github.com down, a session publishes STATUS, reads its own work, receives a decision and records a result.

## Intenção
The engine talks, measures and decides without GitHub; GitHub keeps the code (branch, PR, merge, gate).

## Contexto
- The control plane `forge-webhook` (GATE-TRAIN-SERVICES, ADR-41, D-086) is live: one Durable Object `Control`, the single
  writer of the queue, the leases, the switches and its own log; it has `/webhook`, `/v1/runner/*`, `/v1/admin`, and no route to
  append or read engine events (`services/control-plane/src/core.js`).
- Its state is one dump of seven keys in Durable Object storage (`index.js`); a stored value is capped (about 128 KiB), so an
  event log cannot live in that dump.
- The port (`scripts/lib/forge_events.py`) has Memory, File, GitHub and Routing adapters; every event kind not file-routed is
  a GitHub comment on #865 or on a PR.
- The control plane's job queue holds 604 stale jobs since 31/10 15:52 BRT with no live runner (A Torre); not this unit's path.
- Deploying the Worker and its secrets is Daniel's step (D-088, `npx wrangler deploy`, `wrangler secret put`).

## Regras
- D-086, D-088: the control plane is free plan, deployed by Daniel. D-070: the git-ref log and the lock stay git.
- D-281, D-282: CANALE7 is the chain's next piece; its done criterion is the channel goal. D-054: no production change.

## Problema real
Every engine event needs api.github.com, so the flow stops whenever GitHub refuses. Resolved means: the control plane appends
and reads engine events per channel; the port has a control adapter; one key (`forge-events.log_adapter`) sends every event
kind to it; and a test proves the four acts with the GitHub adapter refusing every call.

## Lacunas
- The deploy and the `EVENTS_TOKEN` secret (Daniel, D-088); the sessions' token (`TOWER_EVENTS_TOKEN`, an operator step).
- The 604 stale jobs: a case of the queue's missing expiry, recorded, not fixed here.
