# FLUXO-AMPLO — diagnóstico

Measured before deciding, from git, `origin/mod/roadmap-integration` at `b0a61aa1` (31/10 about 15:00 BRT).

## Métrica principal
**Counted integrated commits per day** (BRT day of landing). Gaps: a day is not a lane-hour, so it is reported next to
the active-lane count; the counting rule (D-137) is a proxy for valid work and does not yet check durability by
operations.

## Métricas de guarda
`empty`, `fixup`, `split`, `tangled`, `docsonly` (D-164, baseline 0.365), `plan-linked` as shares of the raw count (D-137); wait per PR; authoring per
commit; active lanes; red-rate at the train. A phase passes only if the main metric reaches its target and no guard
gets worse.

## Linha de base
| Metric | Value | Where, when, command |
|---|---|---|
| Raw per day, 24–31/10 | 116, 387, 402, 688, 330, 89, 86, 89 | `scripts/flow-metrics`, 31/10 |
| Counted per day, same days | 109, 379, 400, 676, 308, 88, 86, 89 | same |
| Guards (share of raw, 2,187 commits) | empty 0, fixup 0.002, split 0.022, tangled 0.256, plan-linked 0.667 | same |
| Active lanes (distinct branches per day) | 94 on 25/10, 113 on 27/10, 8 on 30/10, 2 on 31/10 | `git log --first-parent --merges` by head branch |
| Wait per PR, last commit → merge | median 4.2 min (24–28/10), 14.4 min (29–31/10) | git, 354 and 46 PRs |
| Authoring per PR, first → last commit | median 7.9 min, 33.5 min (5 commits each) | same |
| Serial-lane ceiling | about 216 commits/day (estimate, audit finding 4) | n/(a·n+W) with a = 6.7, W = 14.4 |
