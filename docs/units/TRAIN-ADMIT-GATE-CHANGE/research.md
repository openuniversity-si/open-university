# TRAIN-ADMIT-GATE-CHANGE — research

## Quem já resolveu
Bazel/TAP and Uber SubmitQueue judge a change to the build/CI infra with both the pinned infra and the new infra it
brings (self-hosting); both green admits, and the new infra is the pin after the merge.

## Estado da arte
- `train_admit.admissible` refuses when `payload.toolchain_id` differs from the train's attestation
  (`gate_keys.toolchain_id` = `toolchain_manifest.attestation`: installed versions + `registry_digest`, the effective
  registry). A PR that changes `config/registry/*` or the gate gives its verdict another id: the refusal is
  structural, not a race.
- `gate_pin.report` already runs the head's own tooling `--report-only` when the diff touches the gate, but only posts
  it as an advisory comment: no event the train can verify.

## Encaixe em nós
- #807 (TRAIN-RESYNC-TOOLCHAIN, D-078) re-verdicts the same head cold on a toolchain refusal and guards
  `pr.conflicted`; it does not change the toolchain comparison, so a toolchain-changing PR still refuses after it.
  Complementary: this unit adds one rule in `train_admit` and one leg in `train_verdict.judge_verdict`, reusing #807's
  vocabulary (cold verdict of the same head). No duplication.
- `train.verdict_fallback=tier2` in the store is the bootstrap path for this PR.

## Escada de ambição
1. Now: the train runs the head leg itself (report-only, cold) and admits on dual green.
2. Next: the pinned gate publishes the head-tooling leg as a verified event, so the train reuses it instead of
   running it.
3. Later: unit manifests narrow `train.self_host_paths` to the units the toolchain change really reaches.
