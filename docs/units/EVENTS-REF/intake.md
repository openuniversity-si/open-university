# EVENTS-REF (E1) — intake

## Pedido
Daniel's order to A Torre, 01/11 14:12 BRT, relayed to the FLUXO-AMPLO session: "halt the flow and fix the GitHub channel
DEFINITIVELY before anything else ships ... Isso nao pode virar gargalo do nosso." Unit E1 of that order, 01/11 after E4 merged:
"the git-ref adapter for the event log, refs/heads/train/events, through scripts/lib/forge_git_ref.py, so every state kind
stops becoming an issue comment. That is the unit that removes the volume at the source."

## Intenção
The flow must never stop again because its own heartbeat filled a GitHub issue or tripped GitHub's write limit. The record a
human reads (decisions, exceptions, red gates with their reason, merges, releases) stays on the forge; the state machines talk
to each other on a log that has no comment ceiling and no secondary write limit.

## Contexto
- The repository channel is issue #865 (`forge-events.github_log_issue`), created 31/10 19:40 BRT. In 18.5 h it took 1292 of
  its 2500 comments: 70 an hour on average, 269 in the peak hour (05h UTC on 01/11). A Torre's measurement, 01/11 afternoon.
- 06:17–06:29 UTC on 01/11 GitHub refused 30 consecutive `POST /repos/openuniversity-si/open-university/issues/:id/comments`, kind secondary,
  each blocking a process 61–65 s (nine `forge.rate.limited` events). Between 05h and 10h UTC the flow produced 2 commits.
- 79 % of the 1292 comments are repeated state: `slo.breached` 183, `train.batch.started` 147, `train.batch.shards` 145,
  `train.batch.green` 139, `integration.advanced` 139, `train.queue.empty` 136, `defect.verified` 136.
- At 13:57 BRT on 01/11 this session's engine recorded a block of 2297 s on a GET of the channel issue
  (`~/.cache/the-tower/forge-write-budget.json`), while the token's core quota stood at 14923 of 15000: the session's lane
  scripts were stopped for 38 minutes by the channel, not by the quota.
- `scripts/lib/forge_git_ref.py` (GX-FIX-train-lock, D-070) already writes records to `refs/heads/*` by create and
  fast-forward over git, with no REST; `refs/heads/train/wake` carries 413 commits written that way.
- `scripts/lib/forge_events.py` already routes kinds to another log (`RoutingAdapter`, `forge-events.file_kinds`, D-070);
  a read without kinds returns every log of the channel, a read with kinds reads the one log that holds them all.
- E4 (BASE-REGIME, D-272, PR #1026) merged: the base's real gate passes on `1b376334a` in 10.9 s.

## Regras
- D-070 (GX-FIX-forge-rate, GX-FIX-train-lock): every engine GitHub call passes the write budget; the engine writes refs only
  by create and fast-forward over git; no delete, no rewind.
- D-085: the one shared windowed read of a channel.
- D-065: the flow runs on events; the merge train is the only merger. D-054: no production change.
- D-077, D-081: intake, research, audit and plan before code; root causes end in a structural cause.
- D-138: a rule that hurts is challenged, never worked around. D-151: `gate.bypass` and `service.paused` are not this unit's.
- D-273 (recorded by the follow-up EVENTS-ROUTE before it routes): state kinds go to the git-ref log; the forge keeps the record kinds.

## Problema real
Every engine event, whatever its kind, becomes an issue comment, so the channel's size and the account's write limit grow with
the heartbeat, and the flow stops when either is reached. Resolved means: with the defaults of the registry, an event of a state
kind (for example `train.batch.started`) is appended to `refs/heads/train/events` and makes no GitHub REST call; an event of a
record kind (for example `pr.merged`) still makes its comment; a reader of the port sees both, in log order.

## Lacunas
- Which kinds are the human record is a judgment the design names by class (decisions, exceptions, red gates, merges,
  releases); the list is a registry key, so it changes in one place. Nobody else needs to answer it.
- The events already on issue #865 and on PR comments stay where they are; a read without kinds still returns them. A read
  that filters by a kind now on the ref (`train_reuse`, `train_admit`) sees only the ref's events from the cut on; the open PRs
  are re-gated in E5 anyway.
- The board (E2), the single publisher (E2) and rotation (E3) are not this unit; this unit removes the volume they would carry.
