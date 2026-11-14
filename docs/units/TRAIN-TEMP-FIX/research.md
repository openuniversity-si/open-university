# TRAIN-TEMP-FIX — research

## Quem já resolveu
- GitHub merge queue: a failed queue entry is removed with a reason shown on the PR timeline ("removed from the merge
  queue: ...").
- Bors-NG: a failed batch posts its failure and a link to the build log on each member PR.
- Zuul: each buildset records its result and a log URL in its database and reports it to the change.
- Kubernetes Prow/Tide: status contexts and the Tide dashboard show why a PR is not merging.

## Estado da arte
Every queue run, successful or failed, leaves a durable record with its reason, stored somewhere that does not depend on
the component that failed. Health views count only items that can still merge.

## Encaixe em nós
Adapt: one durable record of a death written over the git protocol on the lock's own release record, which needs only
the forge credential the lock already uses and so survives an unreadable event log (the failure we have). Copy: filter closed changes out of the status queue. Not a fit now: a dashboard or a per-PR failure
comment (the status channel is the diary, not PR comments).

## Escada de ambição
Now: record the death and its error line on the lock release, show it in `scripts/service status`, keep the status
count honest, and run the train from a place that has the token. What we lack, named: no supervisor notices a worker
that dies at start, and no inventory says which runner holds which credential. Later, in the redesign: a supervised runner with an inventory of the credentials each runner holds, and
failure events as part of the train's contract.
