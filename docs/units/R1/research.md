# R1 — research

## Quem já resolveu
1. Uber SubmitQueue, "Keeping Master Green at Scale" (EuroSys 2019): every change is tested on top of the base and the changes queued before it, and merges only when that combined result is green. Solves: the trunk's green state is the admission condition, not a check after the merge.
2. Google's continuous testing (TAP, described in "Taming Google-scale continuous testing", ICSE SEIP 2017): results are per change and per tip, and a red tip stops the submits that would build on it. Solves: one result per tip, and a red tip stops the flow.
3. GitHub merge queue (docs.github.com, "Managing a merge queue"): required checks must be green on the queue's combined ref before a merge; a failed entry is removed and the next one is tested again. Solves: a merge waits for checks on the merge result.
4. GitLab merge trains (docs.gitlab.com, "Merge trains"): each entry's pipeline runs on the combined result and the train stops at a failing entry. Solves: the same as 3, with one pipeline per entry.

These four are the references the repository's own padrão already names (docs/padrao/v8/intake-and-research.md). They were not fetched again in this session; the descriptions are the public ones as known to this unit.

## Estado da arte
The standard solution: admission to the trunk is gated by a check on the exact result of the merge (the combined tip), and a red trunk stops admission (SubmitQueue, merge queues). The most advanced: per-change speculative builds with bisection to the culprit and automatic quarantine (SubmitQueue's conflict analysis, TAP's batch bisection). Each requires one place where results are keyed by tip, that every admitting process can read, and an admission step that reads it before merging.

## Encaixe em nós
- Copy directly: a red base stops admission. The admission reads the base's state before it merges. Fits `Train.merge` (scripts/lib/train.py:439), which already checks the tip before it merges.
- Adapt: the results are keyed by the base tip's sha and stored where every train host reads them. The repository already shares train state as git refs (`train/lock`, `train/wake`), so a ref per tip fits without a new event kind. Our shadow writes `.gate/shadow/<sha>.json` on its own host, which does not fit: no other host can read it.
- Does not fit now: per-change speculative builds and bisection of the base. The batch's own bisection exists for its verdict; a base-level bisection is out of scope. Running the real gate inside the train before each merge does not fit yet: it costs one gate per tip on a host whose speed is not measured (intake, Lacunas).

## Escada de ambição
- Rung 0 (this unit): the train holds a merge while the newest published real-gate result of the base is red. A tip with no published result is reported as unknown and is not held.
- Rung 1: the train does not merge on an unknown tip; it runs the real gate on that tip itself, keyed by sha, after the train host's gate speed is measured.
- Rung 2: the real gate runs on the merge result for every batch, including under the regime (RC-005 proposal (b)), as the merge queues do.

The plan's cheapest useful effort is rung 0.
