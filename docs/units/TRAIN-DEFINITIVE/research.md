# TRAIN-DEFINITIVE — research

## Quem já resolveu
- Chubby / etcd / ZooKeeper leases: a lock is a lease kept alive by its live holder (keepalive); a holder that dies
  stops renewing and the lock frees within one short lease, never within the longest possible job.
  (Burrows, "The Chubby lock service", OSDI 2006; etcd `LeaseKeepAlive`.)
- Kubernetes Jobs: `activeDeadlineSeconds` is enforced by the controller (the pod is killed at the deadline and the
  Job ends `DeadlineExceeded`, a definite reason); a `preStop` hook / `terminationGracePeriodSeconds` releases what the
  process holds before SIGKILL.
- Zuul / Bors-NG / GitHub merge queue: every queue item has a build timeout, and a timeout is a result with a reason
  ("timed out"), reported like a failure; nothing waits for a dead build.
- Sidekiq / Celery: a worker that restarts re-queues or fails the jobs it held at boot ("orphan recovery"), using the
  job id it recorded before it started the work.
- HashiCorp Vault / AWS Secrets Manager rotation: each secret has a list of consumers; a rotation is a two-phase step
  (add the new value, update every consumer, then retire the old) and a consumer that fails authentication raises an
  alert naming the secret.
- Cloudflare Workers: `wrangler deploy` from CI on every merge to the deploy branch (continuous deployment; Workers
  Builds or a pipeline job), so the deployed Worker is always the merged one.

## Estado da arte
A job runs under a hard deadline enforced outside the job (the supervisor kills it), the job's locks are leases with
the same deadline (or a keepalive tied to the live process), and the supervisor recovers what a killed job held from
the job id it recorded before starting. Every outcome, including "killed at the deadline", is a result with a reason.
Queues drop work whose subject is closed or superseded at the moment it changes, not only on a timer. Deployment of the
coordinator follows the merge automatically. Secrets have an inventory of their consumers, and every consumer reports
its auth state so a rotation shows who is broken.

## Encaixe em nós
- Copy: the deadline (one registry budget, 10 s) enforced by the runner and by the role itself, a lease equal to that
  budget, a result with a sentence for every outcome including the deadline.
- Copy: orphan recovery from the runner's state file (the job it was running when it died) at the runner's start.
- Adapt: lease keepalive is not needed when no job outlives its budget; the lease simply ends with the budget.
- Adapt: supersession at enqueue time already exists in the control plane (#1084); closed PRs need a webhook-driven
  cancel (`pull_request closed`) since the control plane is the single writer.
- Adapt: continuous deployment of the Worker from the runner after a merge that touches `services/control-plane`
  (no GitHub Actions, D-086/ADR-41), with a Cloudflare API token held by the runner and listed in the credential
  inventory.
- Adapt: a credential inventory in the registry (which runner kind needs which variable, and which control-plane
  secret it must equal) and a runner that reports its auth state in its heartbeat.

## Escada de ambição
Now: one budget, enforced at the runner and in the role; lease = budget; orphan recovery at start; closed-PR cancel and
expiry on every request; credential inventory and auth-state reporting; deploy step after a control-plane merge; the
gate's fixed overhead measured and cut toward the budget. Later: a gate that is one process with in-memory stages and a
content-addressed result store, so a PR's gate is a lookup plus only the tests its diff affects.
