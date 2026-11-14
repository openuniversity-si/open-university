# FLUXO-AMPLO — solução

Unlock graph (Mikado), from the current system (2 serial lanes, about 90 counted commits/day) to the ideal flow. Gains
are estimates on the main metric, re-measured after each sub-phase; the graph is redrawn when the bottleneck moves.

## Grafo
| Node | Change | Needs | Estimated gain |
|---|---|---|---|
| N1 | The count and its guards as a command (D-137) | none | enabler; done |
| N2 | The rule-challenge records (D-138) | none | enabler; done |
| N3 | Fill each PR's commit plan (up to the plan's 8 items) so the per-PR wait W is paid once for more commits | N1 | 6.3 → 7.2 commits/h per lane (1.15x) |
| N4 | Pipeline the lane: after the push of a PR head, author the next PR's commits while its gate and train run (no waiting turn) | N1, N3 | removes W from the lane: up to 9 commits/h, 216/day (1.4x) |
| N5 | Cut authoring per commit (a = 6.7 min): scaffolds, commit plans written first, tool calls batched | N1 | 2x at a = 3 min, then toward 1.4 min |
| N6 | Lane launcher: start k lanes from a fresh base, reset a stale designated branch (fixes RC-001), relaunch on stall | N2 | k-fold up to the next limit |
| N7 | Disjoint areas per lane (`gate-areas.json`) so merges do not conflict | N6 | keeps k-fold from collapsing to rework |
| N8 | Admission-time guards at the train (counted verdict as an event, durability by the next K integrations) | N1, N6 | keeps the count honest at k lanes |
| N9 | Train capacity beyond about 113 PRs/day (batching, shard shadow already in D-065) | N6 | first limit above ~700/day; unmeasured |
| N10 | Dynamic lane count from WIP, train queue and wait per PR | N6, N8, N9 | holds the optimum as load moves |
| N11 | Continuous flow, no turn boundaries | N10 | ideal |

Stage rule (Daniel): serial first (N3–N5), then parallel (N6–N8), then dynamic (N10), then continuous (N11). RC-002
asks that the serial → parallel step be taken when the serial lane is measured at its ceiling.

## Redesenho (31/10 21:40 BRT, after F1.1 and F1.2): where the bottleneck moved
Measured (`scripts/flow-metrics --hourly 8 --cycles`, `scripts/lane-status`): 23.3 counted commits an hour over the last three hours
(30, 18, 22; 560 a day at that pace); authoring per commit 99 s on the landing day (it was 385 s); the wait per PR about a
minute (gate 9 to 42 s, train 44 to 48 s, with the bypass).

| Then (30/10) | Now (31/10 21:40) |
|---|---|
| 2 lanes, 90 a day | 2 lanes, about 23 an hour |
| the wait per PR (14 to 25 min) was 30 % of a lane's cycle | the wait is about 1 min, under 10 % |
| authoring 6.7 min a commit | authoring 1.65 min a commit; a lane could write 36 an hour and lands 23: the rest is the PR's own overhead and idle between PRs |

So the constraint is now **commits written per hour per lane, times the number of lanes**. Nodes drawn from it:

| Node | Change | Needs | Estimated gain |
|---|---|---|---|
| N5b | The lap's overhead to zero: open the PR, check its body, the readers and the plan, gate, all by one command (`lane-ship --create`, D-245) | N5 | 23 → about 30 an hour per lane (the 36 ceiling less the writing of PR bodies) |
| N6b | A third and a fourth lane on disjoint units, each launched from `relaunch-prompt.md` | RC-004 (the approval is for two lanes; asked, not taken) | k-fold up to the train's merge rate |
| N9b | The train's merge rate: one merge about every 45 s, so about 80 an hour of PRs of one commit, 400 of 5 | N6b | the first limit above 40 an hour; unmeasured |
| N12 | The real gate under 10 s on the e2-micro (lane 2) so the regime of exception ends and the number is the flow's alone | none | removes the caveat of F1.1, not a gain in the count |

## Fases
| Id | Target | What changes | Stop criterion | Size |
|---|---|---|---|---|
| F1.1 | 200 counted/day | N3, N4: one serial lane at its ceiling | 200/day for a full lane-day, guards no worse | 2–3 PRs |
| F1.2 | 300–400 | N5: authoring per commit down | measured a ≤ 4.5 min, guards no worse | 2–3 PRs |
| F1.3 | 500–1,000 (21 to 42 an hour, steps 500 = 20.8, 600 = 25, ... 1,000 = 41.7) | N5b at two lanes; N6b beyond two (RC-004) | the hourly mean over at least three hours at each step, guards no worse | 4–6 PRs |
| F2 | 10,000 (steps 2,000 … 10,000) | N9, N10 and what the F1 measurement shows | measured limit or target | redrawn after F1 |
| F3 | 100,000 | N11 and the physical limits | a measured limit recorded as a D-NNN | redrawn after F2 |

Phase 1 is 100 → 1,000/day; its sub-phases on the ladder are F1.1 (200) to F1.3 (1,000), each merged and measured on its
own. F2 and F3 are redrawn when F1 closes.

## Critério de parada
Only the ideal system or a measured physical limit recorded as a D-NNN stops the program: the train's merge
serialisation, the gate's seconds, GitHub or model quota. Noise in a measurement, or cost-benefit, is not one.
