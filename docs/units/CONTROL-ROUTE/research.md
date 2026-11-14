# CONTROL-ROUTE — research

## Quem já resolveu
- GitHub Actions self-hosted runners: one long-poll channel to the service (`/_apis/.../message`); a runner without its
  registration token refuses to start, it never "falls back" to another queue.
- Buildkite agents: `buildkite-agent start` without `--token` exits with `missing token`; jobs are only ever claimed
  from the agent API, with a lease and heartbeat (the shape of `/v1/runner/claim|heartbeat|result`).
- GitLab Runner: one coordinator URL per runner; a failed check-in is retried against the same coordinator.
- Strangler-fig migrations (Fowler): the old path is removed once the new one carries traffic, not kept as a silent standby.

## Estado da arte
Standard: one job API with leases, heartbeats and explicit cancel; config errors stop the agent at start with the name of
the missing setting. Advanced: the queue view is the job store itself (one source), not reconstructed from side logs.

## Encaixe em nós
- Copy: refuse to start without the token, naming `OU_RUNNER_TOKEN`; a control plane that does not answer is a failed
  poll retried next poll (the runner stays up, it does not change route).
- Adapt: the meter reads the control plane's `GET /status` `queue` (the job store) and intersects it with the forge's
  open PRs, since the store keeps jobs of closed PRs (store defects belong to CONTROL-STORE).
- Does not fit now: moving supersession (D-141, one `git ls-remote`) into the Worker — that is the Worker's change.

## Escada de ambição
Now: one transport, loud errors, the meter reading the store and the forge. Next: CONTROL-STORE (retention,
supersession, TTL) makes the store's queue true on its own, and the forge filter becomes a check, not a correction.
