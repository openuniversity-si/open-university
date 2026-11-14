# TRAIN-RESYNC-TOOLCHAIN — research

## Quem já resolveu
- Prow Tide (Kubernetes, https://docs.prow.k8s.io/docs/components/core/tide/): when a PR's last test results are
  stale against the pool's base, Tide retests the PR itself (it triggers the jobs on the same head) and merges on the
  fresh result; the author is contacted only on a merge conflict or a red job.
- GitHub merge queue (https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue):
  the queue builds and tests its own `gh-readonly-queue/*` ref; it never asks the author to re-run anything, and it
  removes a PR with a reason (conflict, failed checks, timeout), never an empty conflict.
- Bors-NG (https://bors.tech/documentation/): `bors r+` tests the merge of the PR into the base on the bot's own
  staging branch; a result from elsewhere is never reused, the bot simply runs its own.
- Bazel remote caching (https://bazel.build/remote/caching): the action key includes the toolchain and the
  environment; a result produced by another toolchain is a cache miss, which triggers a local re-run, not a failure.
- Zuul gating (https://zuul-ci.org/docs/zuul/latest/gating.html): the gate pipeline re-runs jobs on the speculative
  state itself; "merge conflict" is reported only when git's merge actually fails.

## Estado da arte
The standard: the queue owns its proofs. A result it cannot trust (stale base, other machine, other toolchain) is a
cache miss, and the queue re-runs it itself on the same input, then merges; the author hears only about a real
conflict or a real red. The most advanced (Zuul, GitHub's queue): speculative execution, results keyed by the full
input (tree + toolchain + base), and every removal typed with its real reason. It requires a test runner the queue
controls and an input key that names the machine, both of which we have (`gate-verdict --cold`, `toolchain_id` in the
`input_digest`).

## Encaixe em nós
- Copy directly: a refused proof on an input the train can rebuild is a miss, and the train re-runs it on the same
  head (Bazel, Bors). Our `gate.passed` natural key already includes `input_digest` (which includes `toolchain_id`),
  so the re-run gets a new event; only `pr.ready`'s key (repo, pr, sha) blocks the queue route, so the train admits
  from the fresh `gate.passed` directly instead of waiting for a `pr.ready` that the forge deduplicates.
- Adapt: GitHub's typed removal reasons. We keep `pr.conflicted` for its one meaning (a file to resolve) and do not
  add a new event type for the rest: an unpushable branch goes through the tier-2 batch of one, which merges without
  pushing to the branch; a forge refusal is a moved head (the queue already drops it) or a machine problem (halt).
- Does not fit: speculative multi-PR execution (Zuul) — the verdict branch takes one PR alone by design (D-075).

## Escada de ambição
Now (this unit): same-head cold re-verdict + in-pass admission; a guard that makes an empty `pr.conflicted`
impossible. Next: a typed "removed from queue" event if a non-conflict hand-back is ever needed. State of the art:
the train keys every proof by the full input and treats any mismatch as a miss it re-runs itself (already true for
the verdict branch after this unit; the batch path follows when tier 2 reads verdicts).
