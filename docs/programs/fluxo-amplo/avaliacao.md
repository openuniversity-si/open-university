# FLUXO-AMPLO — avaliação

Program (padrão v8, D-115). Evidence and numbers live in the unit's [intake](../../units/FLUXO-AMPLO/intake.md),
[audit](../../units/FLUXO-AMPLO/audit.md) and [research](../../units/FLUXO-AMPLO/research.md); this file states the
frame.

## Pedido
Daniel (CEO), 31/10/2026 13:26–13:44 BRT: improve A Torre's whole flow of producing software; the main metric is
integrated commits per unit of time summed across sessions, kept valid, cohesive and relevant by guards counted in
operations; find the real bottleneck by measuring; capacity grows serial → parallel → dynamic → continuous; each phase
is 10x with a 1-2-…-10 sub-phase ladder; the rules are followed and evaluated.

## Sintoma
About 90 integrated commits per day on 31/10 against a peak of 688 on 27/10 (landing day, `scripts/flow-metrics`), with
no recorded reason for the fall; and no definition of a commit worth counting.

## Sistema que falhou
Two systems. (1) **Lane management is missing**: nothing launches, sizes, partitions and relaunches parallel lanes, and a
lane's first push can fail on a stale branch (RC-001); the flow runs on however many sessions were started by hand.
(2) **The count was missing**: "integrated commits" had no counting rule, so any speed-up was unfalsifiable and any
target could be met by splitting (D-137 builds it). The gate and the train exist and carried 688 commits in a day.

## Sistema ideal
A continuous flow in which lanes are created and retired by measured load (WIP, train queue, wait per PR); every lane
works a disjoint area from a fresh base; each commit is small, whole and relevant; the gate and the train admit it in
seconds and record a verdict as an event; the counted-commit series and its guards are an SLO that stops a phase when a
guard worsens. Only the physical limits remain: the gate's own seconds, the train's merge serialisation, GitHub and
model quota.

## Distância
Counting: a command and a rule (done, D-137), no admission-time check, no durability guard. Lanes: manual, 2 active,
ceiling about 216 commits/day for one serial lane (audit finding 4). Per lane: 70 % authoring, 30 % wait on gate and
train. Train: proven to about 700 commits/day, untested above. Rules: a challenge mechanism now exists (D-138).

## Painel de métricas
Objective: more valid, cohesive, relevant work saved per unit of time, without losing the property that each commit is
a safe point.
- **Main: counted integrated commits per day** (D-137). It pulls; the sub-phase ladder 200 … 1,000 is on it.
- Guard, share of raw: `empty`, `fixup`, `split` each at or below the phase-start baseline (0 / 0.2 % / 2.2 %); `tangled`
  not above 25.6 %; `plan-linked` not below 66.7 %. They keep the count from rising by cutting or mixing commits.
- Complementary: wait per PR (last commit → merge, median 14.4 min), authoring per commit (6.7 min), active lanes, gate
  verdict red-rate at the train (changes must not raise it). Each re-measured at the close of every sub-phase.
