# engine-forge-origin — intake

## Pedido
Daniel, 01/11/2026: take GitHub out of the operation and make Cursor Origin the forge. Nothing in the flow may depend on the vendor. The flow speaks to `scripts/lib/forge_events.py`. Each vendor is an adapter. Changing vendor later is one configuration key. GitHub stays a live adapter of the same port, unselected, so it can return or run beside Origin.

## Intenção
One switch. The train, the gate, the lanes and the sessions keep calling the port. Selecting `origin` or `github` does not edit the flow.

## Contexto
The port is `scripts/lib/forge_events.py`. `ADAPTERS` knew `file`, `github`, `git-ref` and `control`. `config/registry/forge-events.json` allowed only `github` and `file` for `forge-events.adapter`. `scripts/lib/forge_origin.py` implemented the six operations with an injected client that did not exist, and it had no owning unit, so `scripts/prepush` refused every push. The contract suite in `scripts/tests/forge_events/test_forge_contract.py` already runs the six operations against GitHub. Origin on this namespace is `openuniversity-si/open-university`, mirror detached.

## Regras
D-065 the port. D-068 parameters live in the registry. D-069 a vendor call lives in its adapter. D-283 this decision: the key selects the adapter and no other module branches on the vendor. The default of the key stays `github` until an operator sets `origin`, because the app private key is not on the agent and thirteen baseline call sites still name GitHub.

## Problema real
Origin was not a value of the key, and the adapter could not authenticate. The flow could not choose it.

## Lacunas
The thirteen baseline sites in `scripts/lib/adapters/engine-vendors.json` still call GitHub from outside the adapters. Check runs need an installation token (`repository:checks:write`); a user token cannot post one. Merge stays a git fast-forward (`GitRefs`), not `POST .../pulls/{n}/merge`. Get Pull Request has no head repository, so a fork is not visible.
