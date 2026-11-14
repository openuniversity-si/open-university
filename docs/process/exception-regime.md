# Exception regime

In an exception regime every lock of the engine lifts except two: **money** and **other people**. The regime is a
recorded state of the repository, not a message between sessions, so a lane reads it before it acts and depends on
no one to confirm it.

## Why

Locks are written for the normal regime. When the normal regime breaks (GitHub's secondary rate limit, a gate slower
than the flow), Daniel declares an exception. Until now each exception was a single switch (`gate.bypass`, D-151) or
a message relayed by lane 1. A lane that read the message refused it, because no rule said an exception existed
(incident of lane 6, 01/11). The analysis chose redesign over mechanism and patch: the rules system has to know the
regime.

## The state

One registry key in the shared store, `regime.exception`:

| Field | Meaning |
|---|---|
| `active` | `true` while the regime holds |
| `granted_by` | who declared it (Daniel) |
| `granted_at` | the clock of the declaration (BRT) |
| `reason` | the break that caused it |
| `exit` | the condition that ends it (for this one: GitHub writes no longer limit the flow) |
| `kept` | the locks that never lift: `money`, `people` |

## The rule

One function, `regime.lifted(lock)`, answers every lock: `true` when the regime is active and `lock` is not kept.
A lock that is lifted does not refuse. It prints a warning naming the lock and the decision of the regime, and emits
an event `lock.lifted` (lock, sha, lane, time). Nothing is silent: `gate-noite` lists every lifted lock since the
regime started, and the exit of the regime reviews that list.

`gate.bypass` becomes one case of the rule: the gate asks `regime.lifted('gate')`.

## The locks

| Lock | Where | In the regime |
|---|---|---|
| gate verdict before merge | `gate_bypass`, `train_git` | lifts (`gate`) |
| the train as the only merger | `train`, AGENTS.md | lifts (`merger`) for lane 1 only: the session that holds Daniel's order merges a gated head into `mod/roadmap-integration` by fast-forward when the train cannot (GitHub REST refused); other lanes keep the train |
| commit plan budgets, fix-up, several commits per push | `commit_check` | lifts (`commit-plan`) |
| count guards split and rework | `flow_metrics.classify` | lifts (`count-guards`) |
| structure check refusals | `structure_check` | lifts (`structure`) |
| decision number claimed before a commit | `decision_next` | lifts (`decision-claim`): the record takes the next free number and the table check renumbers later |
| GitHub REST for merges and PRs | train | lifts (`forge`): git only |
| literal census | `commit_check --local` | lifts (`literals`) |

## The kept locks

Never lifted, whatever the regime:

- **Money**: no paid service, plan, tier or spending.
- **Other people**: nothing that reaches a person other than Daniel: messages, notifications, other people's
  repositories or accounts, and production, which serves Open University's users (D-054, frozen).
- Because they reach people too: secrets never leave the environment, and the history of `main` and
  `mod/roadmap-integration` is never rewritten (another lane's work would be lost without a way back).

## Outside the engine

The permission classifier of a Claude Code session is not a lock of this repository and the regime cannot lift it.
Where it refuses an action the regime allows, the lane does not work around it: lane 1, whose session holds Daniel's
order, does the action, or Daniel adds an allow rule to `.claude/settings.json`.

## Standing answers

Questions lanes asked more than twice get one answer here, so no lane asks again:

- **Amend or a new commit?** A new commit, never an amend: trailer `Gate-fix: <reason>` and the same `Plan:` item as
  the commit it fixes (D-253, it does not count as a split). One commit per push.
- **A commit that would not count (docs-only, split).** `scripts/flow-metrics --admit` names it; admission guards the
  count, not the quality: run the gate directly, `GATE_BYPASS=0 scripts/gate-dev --pr N`; it emits `pr.ready` when it passes.
- **A draft PR.** Mark it ready (`origin pr ready N`) and run `scripts/deliver --pr N`.
- **The decision claim fails ("tries spent").** Ask lane 1, which pushes the claim ref `claude/decision-claims/D-NNN`.
- **GitHub REST refuses (secondary limit).** Stop, do not retry, tell lane 1.

## Delivery

| Unit | Lane |
|---|---|
| `regime.exception` key, `scripts/lib/regime.py`, `lock.lifted` event, tests | 4 (registry and events) |
| `gate.bypass` and the train read `regime.lifted` | 1 |
| `commit_check` and `flow_metrics` read `regime.lifted` | 8 |
| `structure_check` and the decision claim read `regime.lifted` | 14 |
| `gate-noite` lists the lifted locks | 11 |
