# ORIGIN-PUSH-HISTORY — research

Scope: the repo's own facts and general forge practice. No web search: the brief asks for none, and the repo's evidence settles the mechanism.

## Quem já resolveu
- GitHub: `/repos/{repo}/activity?activity_type=push|force_push` (the adapter's current source for these operations, `scripts/lib/forge_github.py:453`, `:568`).
- GitLab and Bitbucket: push events are delivered as webhooks and kept by the forge; the consumer reads the forge's own event history.
- Git itself: the reflog records every ref move locally with old and new sha; it is per-clone, never per-forge, so it cannot answer for a remote branch.

## Estado da arte
- Forges that expose push history do so from their own event store; a consumer that keeps its own journal of ref moves answers the same questions only from the moment it started recording.
- A window-capped journal can answer "what happened to this ref" only when it holds the ref's creation or its entire history (the same completeness question every event-sourced reader has).

## Encaixe em nós
- The Origin webhook already carries the triple (`repository.pushed`, `refUpdates[]`). The control plane receives it and drops it. The engine's journal (`services/control-plane/src/core.js`, the EventLog) is the natural store: one contract, one write, one read.
- The consumer's commit check reads pushes by position against the PR's commit list (`scripts/lib/commit_check.py:74-89`); the port shape must stay GitHub's `{before, after, timestamp}` so the consumer is unchanged.

## Escada de ambição
- Rung 0: ask the vendor for a push route. Not available in the public API (brief fact 1).
- Rung 1 (chosen): journal each ref move from the webhook at its source, one contract, a completeness rule per branch (the creation record, or an untruncated window), refusal otherwise.
- Rung 3 (deferred, revisit on live refusals): a per-branch channel in the control plane, so a branch's history never shares a window with other repository traffic.
