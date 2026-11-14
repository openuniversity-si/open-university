# EVENTS-REF (E1) — plan

## Alternativas

### R1. The heartbeat and the record share one store
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Add the seven loudest kinds to `forge-events.file_kinds` | remendo | não: the file log is one checkout's, so the train and the lanes stop seeing each other's state | 5 min | alta | breaks the train's reads across machines | 0 |
| A2 A git-ref adapter for the port, and the routing inverted: every kind goes to `refs/heads/train/events` except the record kinds listed in `forge-events.forge_kinds` | corrige a classe | sim: every state kind, present and future, leaves the comments | ~2 h | alta: `forge-events.state_adapter = github` restores today's routing | médio: concurrent appends race on one ref (bounded retry) | 1 |
| A3 A separate service (a broker or a database) for the log | redesenho | sim | days, a credential, money | baixa | alto | 3 |

### R2. The write budget is counted per session, the limit per account
| Alternativa | Nível | Resolve a raiz? | Custo | Reversibilidade | Risco | Degrau |
|---|---|---|---|---|---|---|
| A1 Lower the session budget | remendo | não: N sessions still multiply it | 5 min | alta | slows every session | 0 |
| A2 One publisher process owns every forge write; lanes enqueue | corrige a classe | sim | one unit (E2) | alta | médio | 2 |

## Escolha
- R1 → A2: it moves the whole class (state kinds) off the comments with the writer we already trust (D-070), keeps the record
  kinds on the forge, and flips back with one registry key. A1 breaks cross-machine reads; A3 costs money and a credential.
  Cut (Daniel, 01/11 afternoon, "smaller unit merged beats complete unit waiting"): this unit lands the adapter, its registry
  keys and its tests; nothing is routed to it yet, so the merge changes no behaviour.
  Follow-up: EVENTS-ROUTE, inside the same class: `forge-events.state_adapter` (default `git-ref`) and `forge-events.forge_kinds`
  route every kind but the record kinds to the ref, with D-273 recorded first.
- R2 → A2: the single publisher is unit E2 of Daniel's order, opened after this class lands. Follow-up: E2 (the board, the
  single publisher and the write queue).

## Commits
1. `docs: the intake and the research of EVENTS-REF (E1)` — `docs/units/EVENTS-REF/intake.md`, `research.md`.
2. `docs: the audit and the plan of EVENTS-REF (E1)` — `docs/units/EVENTS-REF/audit.md`, `plan.md`.
3. `feat(events): the git-ref adapter of the event port` — `scripts/lib/forge_git_ref.py`, `scripts/tests/test_forge_git_ref.py`,
   keys `forge-events.git_ref_log`, `git_ref_attempts`, `git_ref_window`, the generated `config/registry/forge-events.json` and
   `scripts/lib/generated/config_registry_forge_events.py`, and this plan's cut.
A chain: each commit needs the previous one.

## Premises
Premises: none.

## Tests
- Commit 3: `scripts/run test forge-git-ref` (a bare local remote; two writers on one log), `scripts/run test config`.
- Final: `scripts/test-suite` once (shared tooling), then `scripts/lane-ship <pr> --real`.

## Base defects expected
None known on `db7b5bd5f`.

## Cheapest useful effort
Action: build the git-ref adapter with tests on a local bare remote, and run the whole script suite once.
Cost: about one hour of session time and one suite run.
Requirement: Daniel, whose flow stopped for five hours on 01/11 because its heartbeat filled the channel.
Cheaper rejected: more kinds in `file_kinds` (local to one checkout, so the train and the lanes stop seeing each other's state);
rotating the issue by hand (the volume fills the next one in a day and the secondary limit stays).
