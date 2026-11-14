# Program gate-excellence: brief

Program steps (Daniel 11:29 BRT 27/10): 1 exploratory audit (Fable 5.1, origin/mod/ga1 bed976b1) -> 2 deep-dive audit (Opus 5.5, origin/mod/ga2 6c842b2d) -> 3 planning into small PRs (Opus 5.5, origin/mod/ga3 70a5f444) -> 4 execution of those PRs (GX-00 first).

## Concept (Daniel, approved; the idea, not a checklist)
The gate is the stage that PROVES a change can enter. Everything that affects that proof is in scope: correctness, cost, time, reliability, visibility, scale and ergonomics (for sessions, coordinator and Daniel), inside one PR and across PRs. The gate must be excellent on its own AND designed to favor every stage that follows, above all the merge train: the proof is delivered in a reusable, verifiable form, bound to exact head/base/lane, so the train does not re-prove everything. From RETRO and other systems, only the parts that touch the gate (RETRO stays a file in the repo; the gate must handle the docs-only commit). Examples Daniel gave are illustrations, never limits. Principles: progress in waves from general to specific, each wave raising capacity for the next; fix the class, not the instance; no literals (every adjustable value is registered config with an API); today's work must not hinder growth to 10k-100k PRs/day.

## Complaint, symptom, evidence
See [audit.md](audit.md) (index of the two audits) and [plan.md](plan.md) §0.

## Measurable goal
Repeated as data in the `program.v1` block of [plan.md](plan.md).
