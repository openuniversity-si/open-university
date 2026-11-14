# TRAIN-ADMIT-GATE-CHANGE — audit

## Entradas
`intake.md`, `research.md`, #804 comments (20:37Z gate-status, 20:38Z forge-events, 20:49Z), #807 body and diff.

## Distância do estado da arte
The pinned leg exists (the proof); the head leg exists only as an advisory comment. Distance: one leg the train must
run itself and one rule that accepts the pair.

## Achados

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| A1 | The strict rule compares `payload.toolchain_id` with the train's attestation and refuses any difference. | `scripts/lib/train_admit.py` (toolchain check), #804 20:38Z `pr.conflicted` | A PR that changes the registry or the gate files can never match: the attestation hashes the effective registry of the checkout (`toolchain_manifest.registry_digest`). |
| A2 | The re-verdict (D-075 requeue, and #807's same-head re-verdict) runs the same gate on the same head. | `train_verdict.resync`, `judge_again` | It produces the same foreign id: the PR ends `not-admitted` after one wasted cold run. |
| A3 | The head's own tooling verdict exists only as an advisory comment. | `gate_pin.report`, `advisory_body` | Not a verified event: the train cannot rest an admission on it. The train must run that leg itself. |
| A4 | After a merge, the tip's scripts and registry are the ones every later attestation and `gate_version` read. | `train_reuse.toolchain_id`, `gate_pin.gate_version` | "The new toolchain becomes the pin" needs no extra step: it is a consequence of the merge. |
| A5 | `train.verdict_fallback=tier2` in the shared store runs a refused PR as a tier-2 batch of one with the train's tooling. | store since 19:31Z, #804 20:49Z comment | The bootstrap of this PR needs no new key and no hand merge. |

Invariants kept: P-53 (the head contains the tip, its tree is the merged tree, the digest is recomputed), P-43 (both
legs are cold), P-46 (`gate_version` is still the tip's: the pinned gate judged the proof).
