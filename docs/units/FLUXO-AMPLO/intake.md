# FLUXO-AMPLO — intake

Stage 1 of the unit flow (D-077, padrão v8). A broad unit: a goal and one main metric, no strict rails.

## Pedido
Daniel, 31/10/2026 13:26–13:44 BRT, in substance:
- Improve A Torre's WHOLE flow of producing software; find what actually limits it today; measure, don't assume.
- MAIN METRIC: integrations per unit of time, in INTEGRATED COMMITS (a commit that passed the gate and landed on the
  base branch), summed across parallel sessions. A commit is the smallest unit of saved work; a PR is an envelope.
- OPEN PROBLEM: make each counted commit VALID, COHESIVE and RELEVANT so that trivial or split commits do not inflate
  the number. Guards must count in OPERATIONS, never in time windows or durability periods.
- If the bottleneck is still test time, continue GATE-SPEED (D-132..D-136); otherwise work on what brings more.
- Padrão v8 stays: unlock graph, 10x per phase (Phase 1: 100 → 1,000/day, sub-phases 200 … 1,000), redesign first,
  answer "did the goal improve or only the number" at each phase close, stop only at a measured limit (a D-xxx).
- Capacity grows progressively: serial commits from one session first; parallel, dynamic parallelism, continuous flow later.
- Relaunches are fine: record a D-xxx and write `relaunch-prompt.md`; say "RELANÇAR:" in the PR and chat.
- Rules are followed AND evaluated: a rule-challenge mechanism (three impact grades) is part of this unit.
- Hard limits: Python for engine/tests, free tiers, no production change, no secrets, no GitHub Actions, no measuring
  loops on the e2-micro, no REST polling.

## Intenção
Daniel wants to watch A Torre decide its own next steps in a continuous loop of evaluate, measure, decide. The
deliverable is therefore a working loop plus its evidence, not a single optimisation.

## Contexto
Integrated commit = a non-merge commit reachable from the base through a merged PR (every base commit entered through a
gated PR merge; `--first-parent` merges are the envelopes).

| Day (BRT) | PRs merged | Integrated commits |
|---|---|---|
| 24/10 | 33 | 48 |
| 25/10 | 110 | 449 |
| 26/10 | 62 | 301 |
| 27/10 | 123 | 748 |
| 28/10 | 27 | 391 |
| 29/10 | 11 | 82 |
| 30/10 | 16 | 64 |
| 31/10 (to 14:54) | 19 | 98 |

- 7-day mean: 311 commits/day; the last three days: 64–98/day. So "about 100/day" is the **current** baseline (31/10 =
  98 by 14:54), and the peak (748 on 27/10) shows the system once did 7x that with many parallel sessions.
- 401 PRs since 24/10: median 5 commits per PR (mean 6.5, max 21); median PR 496 changed lines.
- Commit size, 2,181 commits: p10 = 4 lines, p25 = 15, median = 39, p90 = 273. A quarter of commits are ≤ 15 lines, so
  the inflation risk the brief names is real in the data already, before any incentive.
- Serial cadence since 30/10 (119 gaps inside sessions): median 5.9 min between commits (p25 0.7, p75 17.7).
- Lead time first commit → merge, PRs merged since 28/10 (n = 57): median 50 min, p90 about 17 h (a few long-lived
  PRs). Median 10.5 min of lead per commit.
- Gate on the e2-micro: 292–661 s per PR head with 0 cache hits (D-135, before its fix); session container 16–91 s.

## Regras
AGENTS.md delivery flow; D-132 (10x per phase), D-136 (GATE-SPEED paused at F11, D-134 in force); commit plan of 3–8
items in the PR body; trailers `Fit-Review: not structural` until a structural design is approved.

## Problema real
The flow's throughput (integrated commits per unit of time) fell from a peak of 748/day to about 100/day without a
measured reason, and nobody can yet say which stage limits it or whether a bigger number would still be useful work.
Resolved when: (a) the baseline is a reproducible command, (b) the limiting stage is identified from records, (c) a
counting rule with guard metrics makes the number hard to inflate, (d) each phase moves the metric 10x with the guards green.

## Lacunas
- The gate's own stage timings per PR live on the VM and in `.gate/` of other machines, not here; the bottleneck
  analysis uses git history plus the records readable from this checkout, and says where a number is an estimate.
- "Serial first" is followed; if it blocks the metric the rule-challenge record is used (see the questioning mechanism).
