# CONTROL-CHANNEL (CANALE7) — plan

## Alternativas

### R1. The engine's only remote log is GitHub
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Retry GitHub harder | remendo | não | 10 min | alta | the same limits | 0 |
| A2 The control plane appends and reads engine events; a control adapter; `forge-events.log_adapter` sends every kind to it | corrige a classe | sim, for every event of every channel | ~2 h | alta: the key's default is github | médio: the deploy and the token are operator steps | 1 |
| A3 A new event store service | redesenho | sim | days, money | baixa | alto | 3 |

## Escolha
- R1 → A2: the single writer we already run becomes the log; GitHub keeps the code. Follow-up: CANALE8 (the six-operation port).

## Commits
1. `docs: the intake and the research of CONTROL-CHANNEL (CANALE7)`.
2. `docs: the audit and the plan of CONTROL-CHANNEL (CANALE7)`.
3. `feat(control-plane): engine events appended and read per channel` — `services/control-plane/src/*.js`, its test.
4. `feat(events): the control adapter and forge-events.log_adapter, with the acceptance test` — `scripts/lib/forge_events.py`,
   `scripts/lib/forge_control.py`, registry keys, `scripts/tests/forge_events/test_control.py`.

## Premises
Premises: none.

## Tests
`node --test services/control-plane/test/`; `scripts/run test forge-events`; `scripts/run test config`.

## Base defects expected
`test_config_check.StructureCheckWiring.test_structure_check_fails_on_a_registered_literal`.

## Cheapest useful effort
Action: add the event route to the control plane we run and a control adapter, switched by one key, with the acceptance test.
Cost: about two hours of session time.
Requirement: Daniel, who ordered that nothing in the engine's operation depends on GitHub (15:43 BRT).
Cheaper rejected: retrying GitHub (the same limits stop the flow); a new store service (money, a credential, a deploy).
