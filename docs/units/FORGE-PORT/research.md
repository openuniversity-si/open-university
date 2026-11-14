# FORGE-PORT (CANALE8) — research

## Quem já resolveu
- Hexagonal architecture (Cockburn, "Ports and Adapters"): the application owns a narrow port; each technology is an adapter
  run against one shared contract test.
- Consumer-driven contract tests (Pact): one test suite every provider must pass before it is used.
- Merge queues that merge by push (Bors-NG pushes the tested merge commit to the base; GitHub marks the PR merged when its head
  is in the base).

## Estado da arte
A narrow port, one contract suite run per adapter, the vendor chosen by configuration; a vendor's gap is closed inside its
adapter, never by a second switch.

## Encaixe em nós
- **Copy**: the contract suite per adapter; merge by push of the tested merge commit.
- **Adapt**: append and read are the control plane (CANALE7); set_status is the port's own log, mirrored to a vendor's checks
  when it has them.
- **Does not fit**: keeping the 18 operations (a vendor would have to implement each).

## Escada de ambição
1. The six-operation port and its contract suite, passing on GitHub.
2. Every caller (the train, the gate, the seven modules) through the six.
3. Origin's adapter passes the same suite; `forge.adapter origin` is the switch.
