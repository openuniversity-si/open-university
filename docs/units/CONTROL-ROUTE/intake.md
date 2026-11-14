# CONTROL-ROUTE — intake

## Pedido
A Torre, 02/11 11:40 BRT, on Daniel's order of 02/11 11:27 and 11:28 ("a gente não falou que ia sair do git, então tem que
sair do git"; "eu normalmente não gosto de retrocompatibilidade. Você vai trocar, troca, você vai mudar, muda."): the
control plane becomes the runner's only execution route, the git transport is deleted in the same change, and
`scripts/service status` reads the control-plane queue and drops PRs the forge reports closed.

## Intenção
One route that is the real one. The control plane receives every webhook and holds 1,058 queued jobs that no runner has
ever claimed, while the VM delivers through the git route the engine said it was leaving. A second route that is
silently taken hides the first route's failure.

## Contexto
- `scripts/lib/service_runner.py:459-462`: `GitTransport` is always built; `ControlTransport` wraps it only when
  `service.transport == 'control'` **and** the token exists, and `ControlTransport.poll` falls back to git on any error.
- The shared store holds `service.transport = git`; the VM has no `OU_RUNNER_TOKEN`; control-plane heartbeat 31/10 21:14 BRT.
- `scripts/lib/service_status.py:136`: the queue is every `train/wake` record with no `pr.merged` and not landed.
- Out of scope: the VM, its credentials, the Worker (`wrangler.toml`, deploy), the job store (CONTROL-STORE).

## Regras
D-054 (production frozen), D-086 / ADR-41 (control plane), D-141 (supersession), D-151 (gate bypass), D-289 (a parameter
leaves when nothing names it), D-077/D-081 (unit flow). New decision: D-290.

## Problema real
The runner must have exactly one job channel, the control plane, and fail loudly when it cannot use it.
Resolved when: `rg` finds no transport over git in `scripts/lib/service_runner.py`, a missing `OU_RUNNER_TOKEN` and
`service.transport git` both raise named errors under test, and the meter's queue drops #907 #910 #956 #966.

## Lacunas
- Whether anything besides the runner needs `train/wake` (measured in the audit).
- The control plane's `/status` is not reachable from this session (status.md B2); its shape is read from the Worker source.
