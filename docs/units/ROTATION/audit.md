# ROTATION (CANALE3) — audit

## Entradas
- [intake.md](intake.md); [research.md](research.md).

## Findings
1. `forge-events.github_comment_limit` is read only to print a warning (`scripts/lib/lane_status.py`); `GitHubAdapter.append`
   posts on `forge-events.github_log_issue` whatever its count (`scripts/lib/forge_github.py`).
2. The store lives on the channel; a fresh channel reads empty (D-161), and `config.replay` needs the snapshot's `through` event
   in the window.
3. On 31/10 the channel hit the wall and every gate failed with 403 until a person rotated it (D-160).

## Causas raiz

### R1. The ceiling has no door
Cadeia de porquês:
1. Por que o canal chega ao teto? Because every append posts on the same issue.
2. Por que ninguém troca antes? Because the limit is read only to warn a person.
3. Por que só um aviso? Because the rotation also has to move the store, and that was a manual procedure (D-161).
Classe: mecanismo faltando
Evidência: findings 1 to 3.

## Distância do estado da arte
We know the limit and the margin; we lack the writer's rotation, the carried snapshot and the pointer readers follow. Rung 0.
