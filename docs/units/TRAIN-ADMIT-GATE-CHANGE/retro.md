# TRAIN-ADMIT-GATE-CHANGE — retro

## What went well
- The root cause was one comparison (`toolchain_id` vs the attestation that includes the registry the PR changes).
  The fix is a rule in a pure function plus one leg, behind a switch with an `off` rollback.
- #807 was read first: complementary, no duplicated mechanism.

## What did not
- The head-tooling verdict already existed (gate_pin advisory) but as a comment only; the train has to re-run it.
  A verified `gate.passed`-like event for that leg would save a cold run per gate-changing PR (research ladder 2).
- Three open PRs (#804, #807, this one) touch `train_verdict.py`/`train_admit.py`/`train.json`: textual conflicts are
  expected for whichever merges second; the train hands them back as `textual` to their owner sessions.

## Bootstrap record
This PR is itself toolchain-changing and the train that judges it predates the rule: it merges through the tier-2
fallback already in the store (D-079). The first PR admitted by the rule is #804's next ready head.
