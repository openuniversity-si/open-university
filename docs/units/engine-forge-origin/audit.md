# engine-forge-origin — audit

## Entradas
- [intake.md](intake.md); [research.md](research.md).

## Distância do estado da arte
The port and the GitHub adapter were rung 1. Origin's six operations existed only with an injected client, and the registry could not name it. This unit is the selectable adapter. The thirteen baseline sites are still rung 0: they are mapped, not moved.

## Causas raiz

### R1. The port could not name Origin
Cadeia de porquês:
1. Why could the flow not leave GitHub? Because `forge-events.adapter` had no `origin` value and the client did not exist.
2. Why was the client missing? Because the adapter was merged with an injected double and no authentication.
3. Why did that block the switch? Because a second vendor that is not in `ADAPTERS` is not a configuration change.
Classe: arquitetura/desenho

### R2. Thirteen call sites still name GitHub
Cadeia de porquês:
1. Why does selecting Origin not remove GitHub from the process? Because `scripts/lib/adapters/engine-vendors.json` still lists thirteen baseline sites outside the adapters.
2. Why are they outside? Because they predate the port and the vendor check only lets the list shrink.
3. Why not move them here? Because each site is another unit's read of a pull, a credential or a toolchain download, and this change is the adapter.
Classe: mecanismo faltando
