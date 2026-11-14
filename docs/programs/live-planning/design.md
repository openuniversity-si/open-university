# Live planning — design (LP1)

Status: final (LP1, 27/10/2026, branch `mod/lp1`).

The **live-planning coordinator** ("the planner") keeps every program's plan alive: on each new piece of information it
asks, openly, *does this change the plan, and is there something I can do now that makes the rest go better or faster?*,
and records the answer with its context and intention. It is a Padrão-level mechanism: one design for every program and
venture (gate-excellence, reach-1000-prs-per-day, the roadmap, any future one), not a gate-excellence feature.

Audit evidence is in [audit.md](audit.md) (cases L1–L12, classes 1–6). Values: **agility** (wall-clock time to delivery;
parallelism is a means) and **robustness** (tomorrow easier than today).

## 0. Invariants (what the planner must never do)

1. **PRs never stop or wait for the planner.** No gate, push, `pr.ready`, train batch or merge reads planner state. A unit
   session fixes what is its own, passes the rest on in one command (§1.3), and keeps going. Only the plan moves.
2. **The plan moves at launch boundaries.** A decision changes what launches next. It reaches a *running* session only
   through the reuse-vs-redo judgment (§2.4), at most once per input, delivered as one recorded change applied at the
   session's next commit boundary — never a stream of chat cuts (audit L8).
3. **Every change is recorded** with its input, context, intention and expected effect, append-only and replayable
   (D-069 item 4). A change nobody can read later did not happen.
4. **Events, never a clock** (D-065). The planner is woken by inputs; there is no polling or periodic review. "Estimate
   overrun" is evaluated when any event for that unit arrives, not on a timer.
5. **Small context per decision.** A decision reads its input, the affected part of the graph and the recent decisions of
   its partition — never the whole program, the whole log or a whole plan document (§5).
6. **Only scope, money, production and source of truth go to Daniel** (delegation of 13:03). Everything else is decided,
   recorded and reported (DECIDE, THEN REPORT).

## 1. Inputs: what counts as new information

### 1.1 Sources (all already exist or are already specified; LP wires them)

| Input | Read from | Exists today? | Why it can matter to a plan |
|---|---|---|---|
| Gate failure with class `env` or `contract`; the same failure signature on ≥ 2 heads or on the base | `gate.failed` (class, stage, signature, `scripts/lib/gate_report.py:66`) | emitted, but env is mis-classed as code (audit L5) | One environment fix before more launches saves every later unit a red run (L5, L6, L11). |
| Base moved | `pr.merged`, `integration.advanced` | yes | The merged diff may shrink, grow, obsolete or unblock a pending unit, or invalidate a running one's premise (L4, L10). |
| Unit lesson | RETRO §5 → `scripts/lessons ingest` → `lesson.recorded` | yes, but lessons stay `proposed` (0 of 16 applied) | A lesson that applies to other units becomes a brief line or a prep unit *before* their launch (L1, L3). |
| Pass-on note from a running session | new `plan.note` (§1.3) | **new** | The cheapest, earliest signal: the session that found it says who else it touches, then keeps going. |
| Premise answered | `premise.confirmed` / `premise.refuted` | printed only (`scripts/lib/premises.py:272-274`) | A refuted premise re-scopes or cancels its dependents (`EVENTS.md:108`). |
| Defect registered / reopened / resolved | `defect.registered`, `defect.reopened`, `defect.resolved` | yes | Fix-first vs work-around; release units that waited on it. |
| Session failed / stalled / ended | `session.failed`, `session.ended`, `engine.session.stalled` | specified; `session.*` have no producer yet | Re-launch, re-split or redo decision. |
| Estimate overrun | derived: the unit's `work.assigned` time vs its `estimate` when its next event arrives | **derived** | Re-split, re-estimate the critical path, re-check what waits on it (plan rule "over 2× stops", `gate-excellence/plan.md:673`, is unenforced). |
| Train signals | `train.queue.growing`, `pr.ejected`, train halt | yes | Merge capacity is the bottleneck: launch less, or launch the train fix first (L7). |
| Owner ruling | `plan.input` written by `scripts/plan input` for Daniel or A Torre (a chat message turned into one event) | **new** | Daniel's rules of 14:19/14:44/14:59 are plan inputs; today they trigger whole new plan files (L10). |
| Flake / selection escape / SLO breach | `test.flaked`, `selection.escape`, `slo.breached` | yes | Usually no plan change; occasionally "fix the class first". |

### 1.2 Triage (deterministic, cheap, no model)

Every input passes a pure function `triage(event, plan) -> candidate | seen` before any judgment, in the same process that
appended the event (EVENTS.md "Transport v0"): milliseconds, no lock, no model. It:

1. **Dedupes by signature** (failure signature, lesson class, premise id, defect id). A second sighting of a known signature
   updates the existing candidate's count and affected list instead of creating a new one — that count is the
   "rediscovery" metric (§7).
2. **Computes the affected set** from data already in the repo: units whose `area` / owned paths (`units/*/unit.json`,
   `scripts/units`) intersect the input's paths; units whose `Premises:` cite the premise; pending units of the same lane;
   the explicit `affects` of a `plan.note`. Empty affected set and no `all` → `seen` (recorded, not judged).
3. **Promotes to a candidate** when any of: affected set includes a pending or running unit other than the producer;
   class `env`/`contract`; second sighting; premise event; owner ruling; overrun; train halt/eject. Everything else is
   recorded as `seen` with the reason, so "why didn't the planner react?" is answerable.

A candidate is emitted as `plan.candidate` (contract locked by the preparation unit) carrying the input refs, the
sightings and the affected set; that is all the judgment step receives besides the partition context (§5).

Triage is intentionally generous (open pertinence is the judgment's job, §2); it only drops what provably touches nobody
else.

### 1.3 The pass-on interface for running sessions

`scripts/plan note --program <p> --from <unit> --affects <units|areas|all> --kind <blocker|lesson|premise|estimate|engine>
--evidence <ref> "<one line>"` emits `plan.note` and returns at once. The Padrão rule becomes: *fix what is yours; for
anything that touches other units, run `plan note` the moment you know, then keep going.* RETRO §5 lessons are still
ingested at RETRO time; the note is the early copy. Sessions never wait for an answer.

## 2. Decision procedure (open judgment, short checklist)

### 2.1 The questions

For each candidate, the planner answers in writing — not a rule table, a judgment guided by these questions:

1. **What exactly is new, and how sure is it?** (evidence, sightings, is it reproduced on the base or one box only)
2. **Who does it touch?** Pending units, running units, the base, other programs. (Start from triage's affected set;
   widen if the judgment sees more.)
3. **What does doing nothing cost?** Roughly: affected units × expected loss each (red runs, rediscovery, rework, merge
   conflicts) vs the cost of acting. (L1: ≈ 1 red verdict per key-adding unit × ~20 units ≫ a 15-minute fix.)
4. **Is there something I can do now that makes the rest go better or faster?** A short preparation unit before the next
   launches; fixing first and launching after (L11); one brief line; applying a lesson; registering a known/env defect;
   pulling a later unit forward.
5. **Does the graph still hold?** Premises, dependencies, estimates, splits: reorder, re-split, merge, drop, defer, add an
   edge, remove a collision edge.
6. **What should launch next, and what should not yet?** A *targeted* hold (named units, reason, release condition), never
   a global one unless the base or engine itself is untrustworthy.
7. **For each running session it touches: reuse or redo?** (§2.4)
8. **Is it mine to decide?** Scope, money, production, source of truth → Daniel, with the decision prepared; meanwhile the
   safest reversible option is applied and everything else continues.
9. **Robustness: what change makes this never need deciding again?** A rule, helper, registry key, brief-template line or
   Padrão candidate — and who owns it. If it is cheap and shared, it is often the preparation unit of question 4.

Most candidates end in "no change, recorded"; that is a valid, logged decision.

### 2.2 Actions (an open menu, examples not limits)

| Action | Effect on the live plan | Typical trigger |
|---|---|---|
| `note` | Recorded, no graph change | Pertinent but cheaper to absorb |
| `brief_line` | A line added to the briefs of named pending units | A lesson with a one-line workaround (L1, L3) |
| `insert_unit` | New (usually preparation) unit, with edges *onto the affected pending units only* | A blocker that would hit many units (L1, L2, L5) |
| `reorder` / `rewave` | Changes order, wave or priority | A fix that unblocks others is pulled forward (L6, L7) |
| `split` / `merge_units` / `drop` / `defer` | Changes units | False premise, overrun, scope already done elsewhere (L4) |
| `set_estimate` / `set_edge` / `remove_edge` | Changes the critical path | Overrun; a collision edge removed by a prep unit |
| `hold` / `release` | Targeted launch hold with reason and release condition | Engine problem, red base, env gap |
| `register_defect` / `apply_lesson` | Writes through the existing tools (`scripts/defects`, `scripts/lessons`) | Known base or env problem; a lesson that should reach briefs |
| `redo` / `continue` / `rescope` (running unit) | §2.4 | Serious engine problem, false premise |
| `escalate` | One prepared question to Daniel; the rest proceeds | Scope, money, production, source of truth |

### 2.3 Coalescing

Candidates that arrive while a decision is running for the same partition join the next decision of that partition (one
decision may cover several inputs). This bounds decisions per partition by how fast decisions finish, not by input
volume, and is what turns L8's "4 cuts in 15 minutes" into one change.

### 2.4 Reuse vs redo for running sessions

Default: **continue** — the session keeps its work and its PR (invariant 1). The planner considers another outcome only when
the input makes the session's *output* wrong, not merely suboptimal:

| Question | Points to |
|---|---|
| Is the pushed work still correct under the new information (does it rest on the refuted premise, the broken engine, the obsolete scope)? | yes → continue; no → rescope or redo |
| If the engine was broken (e.g. the gate judged wrongly), is the problem in the *work* or only in its *verdict*? | verdict only → continue, the verdict is re-judged after the engine fix (invalidate the proof, not the session) |
| Sunk work (plan items ticked, commits pushed) vs remaining work under the new scope vs a fresh unit from the base | redo only when remaining + rework > fresh unit |
| Will the fix land in the base before this unit gates? | yes → continue; the unit merges the base per the MERGE LOOP |
| Can its good commits be harvested into the new unit? | close + harvest (as plan.md §5 did with BD1/GS2) rather than discard |

The outcome is one recorded change for that unit: `continue` (nothing sent), `rescope` (one message with the new done
criteria, applied at the next commit boundary), or `redo` (the coordinator closes the PR with a pointer to the decision,
harvests named commits, and launches the replacement unit). A session never receives more than one rescope per input.

## 3. The live plan: where it lives and how it is versioned

### 3.1 Shape

```
live plan(p) = fold( plan.md program.v1 block  (version 0, written once by the planning session),
                     plan.changed events of p    (versions 1..n, in order) )
```

`plan.changed` (new contract `contracts/events/plan.changed.v1.json`) carries:

- `program`, `version` (n), `parent` (n−1 and its digest: optimistic concurrency, a stale writer is refused),
- `ops[]` — a small, closed set of graph operations over `program.v1` (`add_unit`, `set_unit` fields, `remove_unit`,
  `set_deps`, `hold`, `release`, `brief_line`, `rescope`, `redo`), each validated against the contract after the fold,
- `inputs[]` — event ids / refs that triggered it (context),
- `judgment` — the answers to §2.1 that mattered, in ≤ 10 lines,
- `intention` — one sentence: what this change is for,
- `expected_effect` — what should become measurably better (e.g. "no key-adding unit fails D-A3 again"),
- `decided_by` (`planner`, `A Torre`, `Daniel`), `reversible` (bool), `escalated` (bool).

Status is still folded from delivery events (`scripts/lib/program.py:124-149`); plan changes are folded from `plan.changed`.
Both folds are pure, so the plan at any past moment is reproducible.

### 3.2 Storage and versioning

- **The decision log is a file in git**, on one dedicated branch `plan/live`: `docs/programs/<p>/plan-log.jsonl`
  (one `plan.changed` per line, hash-chained like `docs/process/lessons/*.audit.jsonl`). The planner is its **sole writer**,
  appends only, never force-pushes; a non-fast-forward is resolved by a merge commit. GitHub stays the source of truth
  (P-02, D-065); no new store. Git gives versioning, diff, blame and offline readability from any cloud session
  (`git fetch origin plan/live`).
- **Why not the base branch**: writing the plan to `mod/roadmap-integration` would need a PR, a gate and a merge per change
  — the planner would become the bottleneck it must not be. **Why not only forge comments**: they are not diffable and
  not readable without the API. The `plan.changed` event is still emitted through the forge port as the *trigger* for
  the coordinator and launcher; the file is the record.
- **Into the base at milestones**: the program's RETRO (and any planning session that rewrites the plan, like plan-v2)
  starts from the folded live plan and merges `plan-log.jsonl` into the base with the program docs, so the base keeps the
  history. `plan.md` version 0 is never edited after launch; a full re-plan becomes a set of `plan.changed` ops, not a new
  `plan-v2.md`.
- **Human view**: `scripts/program plan <p> [--at <version>]` prints the folded graph; `scripts/program log <p>` prints the
  decisions (time, input, intention, ops). The dashboard (`scripts/dashboard`) gains one section from the same fold.

## 4. How launches read the live plan

- `coordinator.next()` already re-reads the plan on every call (`scripts/lib/coordinator.py:155`). It changes to read
  `fold(plan.md, plan-log.jsonl)` and to honour three new fields: `hold` (skip), `brief_lines` (appended to the brief by
  `coordinator_launch.py:86-103`, next to applied lessons and open defects) and `priority` (inside a wave, before id).
- Every `work.assigned` carries `plan_version`; a launch decided on version n is refused if the folded version moved and
  the change touches that unit (optimistic check, no lock). So no launch uses a stale plan (L9).
- **The box launcher and `v3/LAUNCH-HOLD`** live off-repo. Contract for them: before any launch, call
  `scripts/coordinator next --program <p>` and launch only what it returns; `v3/LAUNCH-HOLD` stays as Daniel's / A Torre's
  global emergency brake and is mapped to a `hold all` in the fold (reason "LAUNCH-HOLD present"), so both are visible in
  one place. A hold is a plan state with a reason and a release condition, not a file nobody can read from a cloud
  session.
- Manual launches by A Torre follow the same `next` output; a launch outside it is recorded as `plan.changed` (`decided_by:
  A Torre`) so reality and plan never silently diverge.

## 5. Not a bottleneck; scaling to 1,000+ PRs/day

- **Off the PR path** (invariant 1). If the planner is down or slow, PRs, gates and the train run unchanged; launches follow
  the last folded plan. Inputs are events, so nothing is lost: the next decision reads them.
- **Volume**: at 1,000 PRs/day the event volume is ~10⁴/day. Triage (pure, ms) removes duplicates and inputs that touch
  nobody; signature dedupe collapses repeated failures (12 sightings of one test in L6 → one candidate). Expected candidates
  needing judgment: tens to low hundreds per day, dominated by base merges and env signatures.
- **Partitioning**: a decision's partition is (program, area). A decision reads: the candidate (with sightings), the affected
  units' rows and their direct neighbours in the graph, the last ≤ 10 decisions of the partition, the relevant registry
  records (defect, lesson, premise) — target ≤ 20k tokens. Partitions decide in parallel; `parent` versioning per program
  serialises only true conflicts (a refused write re-folds and re-decides its small context).
- **Cross-program inputs** (engine, gate, base, environment) go to the `engine` partition, whose actions may hold or insert
  units in several programs. This is the only partition that sees the base; it is where L5/L6/L7-type problems belong.
- **Latency target**: input → decision recorded in minutes, always before the next launch of an affected unit, because
  launches re-check `plan_version`.

## 6. What runs it, and its cost

| Part | Runs as | Model / cost |
|---|---|---|
| Triage, fold, `next`, `plan note`, `plan input`, log append | code in `scripts/lib/plan_live.py` (+ `program.py`, `coordinator.py`), run by whoever appends the input event (Transport v0) | none; ms |
| Judgment | one long **planner-role cloud session** (like the train role, `scripts/lib/engine_role.py`), woken by a candidate (send_message / event wake, never a schedule); it is the sole writer of `plan/live`; it fans out ≤ 3 read-only sub-agents for independent partitions when several candidates are pending | opus-tier; ≈ 20–40k tokens per decision |
| Escalation | one prepared question to Daniel only for scope/money/production/source of truth | — |

**Quota.** Today (≈ 100–300 PRs/day across programs): an estimated 20–60 decisions/day × ≈ 30k tokens ≈ 0.6–1.8 M
tokens/day, about the cost of one or two unit sessions per day. At 1,000 PRs/day: ≈ 100–200 decisions/day after
coalescing ≈ 3–6 M tokens/day. Against it: L1 alone cost two red verdicts (≈ 400 s + ≈ 60 s of gate each) and would
have cost one per key-adding unit for the rest of wave 0–1; L6 and L11 put 14 PRs red for ≈ 3 h. No money is spent:
Max-plan quota only; if the quota headroom (the coordinator's existing `quota_headroom_percent`, today blind,
`coordinator.py:135`) is low, the planner records candidates and decides only `engine`-partition ones.

Until the code exists, **A Torre runs the procedure by hand** (§2 checklist, `plan.changed` lines written by hand to
`plan/live`), which already removes classes 1, 2 and 6 of the audit.

## 7. Measures (how we know it works)

From the events, no new metric registry entry needed until a unit proposes one:

- **Rediscovery count**: sightings of a known signature or lesson class after its first candidate (target: falls each wave).
- **Input → decision time** and **decision → first affected launch** (decision must precede it).
- **Wall-clock to program end vs the plan's critical path**, recomputed per `plan.changed` (the plan shows its own ETA).
- **Reversal rate**: decisions undone by a later one within the same program (high = deciding too early).
- **Running sessions touched**: rescopes/redos per program (should be rare; L8's churn is the failure mode).

## 8. Premises of this design

| Id | Premise | Radius | If wrong |
|---|---|---|---|
| LP-P1 | A dedicated `plan/live` branch, appended by one writer, is an acceptable home for the decision log (GitHub stays the source of truth; nothing moves to a new store). | medium — source-of-truth adjacent | Fall back to the forge event log (comments) as the record; the fold is the same. Reversible. |
| LP-P2 | A Torre's off-repo launcher can call `scripts/coordinator next` before launching. | medium | Launch stays manual and reads `scripts/program plan` by hand; holds still work. |
| LP-P3 | A long planner-role cloud session can be woken by events (send_message from the triage step or by A Torre). | low | A Torre runs the judgment in its own session. |
| LP-P4 | Running sessions will run `scripts/plan note` when told to by the Padrão. | low | RETRO §5 ingest still catches it, later. |
| LP-P5 | Mis-classed env failures (L5) are fixable by `gate_classify` rules (gate-excellence GX-01/GX-03 territory). | low | Triage keys env detection on signatures seen on the base instead. |

None is CRITICAL (no scope, money or production change). LP-P1 touches *where* a record lives, not the source of truth
(still git on GitHub); decided here, reversible, and reported.

## 9. Relation to existing work

- **Coordinator (`scripts/coordinator`)** stays the executor; the planner only changes its input. No second launcher.
- **gate-excellence plan-v2 GX-41** ("dynamic-planning coordinator", `origin/mod/ga4:…/plan-v2.md:17`) is the same need.
  This program owns it; GX-41 is dropped from gate-excellence when the handover happens ([plan.md](plan.md) §5), so there is one
  implementation, not two.
- **Lessons, premises, defects** keep their registries; the planner is a new consumer, and wires the gaps (applied
  lessons, published premise events, env classification) instead of inventing new stores.
- **Padrão**: one new rule file (`docs/padrao/v2/pass-on.md`: fix yours, `plan note` the rest, keep going) and one for the
  coordinator role (the §2.1 checklist), shipped as a new Padrão version, never edited in place.
