# Program fluxo-amplo: audit

The audit is `diagnostico.md` (the causes, with their chains of whys and classes, D-081). Its roots and the units that answer them:

- the gate on the e2-micro (cold path, measured by lane 2, unit G1; cold script tests, lane 3, unit G2);
- the structure warnings of three oversize units (lane 4, unit S1);
- the cost of every push through the pre-push hook (lane 5, unit P1).

The decision numbers are in `docs/domain/DECISIONS.md`; the coordinator's view is `scripts/coordinator status fluxo-amplo`.

## Five lanes (D-277, 01/11 15:14 BRT): what it costs
Said plainly: with five lanes the program's 24 units do not close on the date sixteen lanes would have reached. Measured on
01/11: 110 pull requests merged into the base in the day with up to sixteen lanes; the train was not the limit for most of the
day (the base was red 10:52 to about 14:20, D-272, and the channel stopped the flow 05h to 10h UTC). A lane delivers about the
same per hour with fewer neighbours, so throughput falls roughly with the lane count: 16 to 5 is about 3x slower. The 13 units
left in the graph plus the five of the channel redesign, about one day of the sixteen-lane flow, become about three days.
What drops: the covers narrowing of M9 to M15 (each a few percent of the gate's cost), S1 (structure warnings), P1 (the
pre-push cost) and N7 (checks through a script) go to the queue. What keeps its pace: the channel redesign (lane 1), the base,
the gate and the train (lane 2), the write queue the board needs (lane 6), the process units N8, L1, K5 (lane 8) and M16 (lane 16).
