# BOARD (E2) — plan

## Alternativas

### R1. The view and the log are one stream
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Post the board kinds less often (sample them) | remendo | não: the channel still grows, only slower | 15 min | alta | the state on the forge is stale | 0 |
| A2 A board: the board kinds go to the git-ref log, and a fixed set of sections on the board issue is rendered from it and edited in place | corrige a classe | sim: every state kind of a section, present and future | ~2 h | alta: `forge-events.board_issue` 0 turns it off | médio: a PATCH per changed section | 1 |
| A3 A separate dashboard service | redesenho | sim | days, money | baixa | alto | 3 |

### R2. The upsert is safe for one writer on a short thread only
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Read more pages in the find | remendo | não: two machines still both create | 5 min | alta | more reads | 0 |
| A2 The board's own issue (one page), convergence after every write (keep the lowest id per section, delete the rest), and a cut to size with the excess on a ref | corrige a classe | sim for every board writer | ~1 h, within A2 above | alta | baixo | 1 |

## Escolha
- R1 → A2: the view leaves the log; the board kinds stop commenting; off by default until the board issue exists.
- R2 → A2: the board converges instead of locking, so any number of writers on any machine end with one comment per section.
  Follow-up: the single publisher with the account's budget (W1, lane 6), so the board's PATCHes are serialised too.

## Commits
1. `docs: the intake and the research of BOARD (E2)`.
2. `docs: the audit and the plan of BOARD (E2)`.
3. `feat(events): the board: fixed sections edited in place, converged, cut to size` — `scripts/lib/forge_board.py`,
   `scripts/tests/forge_events/test_board.py`, `units/engine-events/unit.json`, `CODEOWNERS`, the covers.
4. `feat(events): the board kinds go to the git-ref log and the board, not to comments` — `scripts/lib/forge_events.py`, the
   registry keys `forge-events.board_issue`, `board_sections`, `board_overflow_ref`, the test.

## The proofs (each a test of commit 3)
- Rewritten, not accumulated: three refreshes of a section leave one comment with the last text.
- A concurrent writer: two boards that both found none and both created converge to one comment per section, the lowest id.
- Deleted by hand: the next refresh recreates the section once; a second refresh does not duplicate it.
- The size limit: a section above `forge-events.github_comment_max_chars` is cut to fit, ends with a pointer line, and its full
  text is appended to `refs/heads/<forge-events.board_overflow_ref>`; no other comment is created.

## Premises
Premises: none.

## Tests
`scripts/run test forge-events`, `scripts/run test forge-git-ref`, `scripts/run test config`; the whole suite once.

## Base defects expected
`test_config_check.StructureCheckWiring.test_structure_check_fails_on_a_registered_literal` fails on the base (noted in #1034).

## Cheapest useful effort
Action: build the board with its four proofs and route the board kinds to it, off until the board issue is set.
Cost: about three hours of session time.
Requirement: Daniel, whose channel takes about 95 state comments an hour and stopped the flow on 01/11.
Cheaper rejected: sampling the board kinds (the channel still fills); reading more pages in the find (two writers still
duplicate); a dashboard service (money).
