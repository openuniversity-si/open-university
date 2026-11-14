# BOARD (E2) — research

## Quem já resolveu
- GitHub's sticky comments (marocchino/sticky-pull-request-comment, Codecov, Vercel's bot): one comment per header, found by a
  hidden marker and edited in place; the PR never gets a second copy.
- Kubernetes' status subresource: the current state is one object rewritten; the history is events, kept apart.
- Dashboards over a log (Grafana over Prometheus, CI status pages): the page is a view of the newest state; the log keeps volume.
- Leader-less convergence (Dynamo's read repair): writers that may race converge by a deterministic rule (keep the oldest, the
  lowest id) instead of a lock.

## Estado da arte
A view is one object per section, rewritten in place, keyed by a stable marker; the log carries the volume; races converge by a
deterministic rule; a view that can exceed its container is cut and points to the log.

## Encaixe em nós
- **Copy**: one comment per section, keyed by its first line; edit only when the text changes.
- **Adapt**: the find reads the board issue's comments (a few, one page), not the channel; duplicates converge to the lowest id
  and the others are deleted.
- **Does not fit**: a separate dashboard service (money, a credential).

## Escada de ambição
1. (this unit) The board: sections from the git-ref log, upserted on their own issue, converged, cut to size with the excess on
   a ref; the board kinds no longer comment.
2. The single publisher: one process owns every board and PR write, with the account's budget (W1, lane 6).
3. Rotation (E3): the board issue is replaced by code past a threshold.
