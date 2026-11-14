# ROTATION (CANALE3) — plan

## Alternativas

### R1. The ceiling has no door
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 A louder warning | remendo | não | 5 min | alta | none | 0 |
| A2 The adapter rotates at limit minus margin: next issue, store carried (snapshot and the changes after it), one pointer line; readers follow pointers from the registry's issue | corrige a classe | sim, for every issue the adapter appends to | ~1.5 h | alta: no rotation below the threshold | médio: a reader with an old cache reads the old issue until it re-reads | 1 |
| A3 The channel leaves GitHub (E7) | redesenho | sim | a unit (E7, after E5) | média | médio | 3 |

## Escolha
- R1 → A2: the door in the one place that writes. Follow-up: E7 (Daniel, 15:43 BRT) removes the channel from GitHub.

## Commits
1. `docs: the intake and the research of ROTATION (CANALE3)`.
2. `docs: the audit and the plan of ROTATION (CANALE3)`.
3. `feat(events): the board kinds go to the git-ref log and the board (CANALE2)` — `scripts/lib/forge_events.py`, the
   `forge-events.board_*` keys, `forge_github.GitHubAdapter.issue_comments`, tests.
4. `feat(events): the repository channel rotates before its limit (CANALE3)` — `scripts/lib/forge_github.py`, tests.

## Premises
Premises: none.

## Tests
`scripts/run test forge-events`, `scripts/run test config`.

## Base defects expected
`test_config_check.StructureCheckWiring.test_structure_check_fails_on_a_registered_literal` (noted in #1034).

## Cheapest useful effort
Action: rotate the repository channel in the adapter, carrying the store, with a pointer readers follow.
Cost: about 1.5 hours of session time.
Requirement: Daniel, whose flow stopped on 31/10 when the channel hit its wall (D-160).
Cheaper rejected: a louder warning (a person still rotates at the wall); rotating by hand now (it moves the wall, not the door).
