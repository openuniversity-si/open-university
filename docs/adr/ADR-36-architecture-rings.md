# ADR-36 — Architecture rings and the cumulative checker

Status: accepted for the structural audit (state 5.3).

The checker in `scripts/check-architecture.mjs` is the executable form of the ring rules.
Since plan v3.1 U2 (D-067) the rules are data in the unit manifests and the checker is a generic engine over them
([UNITS.md](../architecture/UNITS.md#architecture-rules-as-data-u2)); a rule's `since` is its state.
Kernel is ring 0, domain and ports are ring 1, server, client, platform and admin adapters are ring 2, and app and UI composition is ring 3.
A productive edge may only point at the same ring or a lower one, and a context talks to another context through domain or ports.
`checkArchitecture` still returns the violation list. The report around it records the layer, the graph size and the count of non-trivial cycles.
Rules are selected with `--through` and stay in the unit-test executor. A fixture that is empty of a rule's inputs passes.
