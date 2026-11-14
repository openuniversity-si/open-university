# engine-wrappers contract (1.0.0)

The unit is logical (S1, P-03) and has no `@ou/` address, so the manifest `contract` slot stays empty (a filled slot is red in `scripts/unit-battery`, measured in the audit). The published surface is the set of executables, which keep their paths and behaviour:

| Command | Behaviour |
|---|---|
| `scripts/run <gate\|test> …` | resolves to `scripts/gate-<name>` or `scripts/tests/<name>.test.sh`; `--print` names it |
| `scripts/tower-catalog <command> … --target preview\|staging\|prod` | admin catalog API; secret on fd 3 only |
| `scripts/tower-media …` | `tower-catalog media …`, delegation only |
| `scripts/tower-factory …` | validate/convert a `curated/v1` file with the pinned Node |
| `scripts/factory-bench …` | synthetic institution bench against the local database |

A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, then remove the old. Nothing outside these files imports the unit; no consumer file is edited here.

Literals: none (the no-literals check finds zero and no `x-literal-sites` entry names the unit). Battery: `scripts/unit-battery engine-wrappers`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate` shows no drift for this unit.
