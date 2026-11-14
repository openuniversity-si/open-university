# TRAIN-ADMIT-GATE-CHANGE — plan

Rule (D-079): with `train.self_host` on, a verdict whose only difference from the strict rule is a foreign
`toolchain_id` admits when

1. the PR's change (tip...head) touches `train.self_host_paths` (the toolchain set: the gate files, the train, the
   registry, the toolchain manifest), and
2. every other strict condition holds: verified v4 `gate.passed` of the head, base is the tip, the head contains the
   tip, plan dev, `gate_version` is the tip's (the pinned gate on the base judged it), `head_tree` matches, the
   `input_digest` recomputes with the proof's own toolchain id, cold; and
3. the second leg, the head's own tooling run cold on the same head (`train.self_host_command`, report-only, in a
   checkout of the head), exits 0. It runs only when 1 and 2 hold, once per head per run, measured as
   `train:self-host`.

Either leg red refuses (fail closed) and the PR takes `train.verdict_fallback` as today. A PR that touches none of the
paths is judged exactly as before (same refusal text). After merge the tip carries the new tooling and registry, so
the next attestation is the new pin (audit A4).

Commits: see the PR body plan (items 3–6). Bootstrap: D-079 and the PR body.

## Cheapest useful effort
Action: the head leg, one cold report-only gate run of the head's own tooling, only for a toolchain-changing PR whose
strict verdict differs by its toolchain_id alone, once per head.
Cost: one extra cold gate run per toolchain-changing PR (about the cost of the tier-2 batch of one it replaces).
Requirement: Daniel (17:47 BRT), who wants gate-changing PRs to flow through the train instead of looping `not-admitted`.
Cheaper rejected: keep the `tier2` fallback forever (the verdict path never admits a gate change); trust the advisory
comment (not a verified event, P-43); relax the toolchain check for every PR (breaks GX-28).
