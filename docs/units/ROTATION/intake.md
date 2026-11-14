# ROTATION (CANALE3) — intake

## Pedido
Daniel's order of 01/11 14:12 BRT, item 6 of the design: "Rotation becomes code: past a threshold the next board opens, config
points to it, the old one gets one pointer line." A Torre, 15:44 BRT: "Agora o E3 (rotação: limiar, abertura do próximo quadro,
ponteiro) — um PR por vez, e no corpo do PR escreva os pontos dos provedores de cota."

## Intenção
No issue of the flow ever reaches GitHub's 2500-comment wall: the code opens the next one before it, carrying what the flow
needs to keep working, so nobody rotates by hand at the wall (D-160).

## Contexto
- The repository channel is #865 (`forge-events.github_log_issue`, a registry default because it locates the change store,
  D-160): 1433 of 2500 comments at 15:3x BRT on 01/11. `forge-events.github_comment_limit` (2500) is read only by
  `scripts/lib/lane_status.py`, to print "WARN: rotate the channel, D-160"; no code rotates.
- The change store is read from that channel; a new channel starts empty, so settings fall back to defaults unless the newest
  `config.snapshot` and the changes after it are carried (D-161; `config.replay` refuses a snapshot whose `through` is not in
  the window read).
- The board (CANALE2, #1037) never grows: it has one comment per section. The routing of the board kinds is the first code
  commit of this unit (it did not land with #1037).

## Regras
- D-160, D-161: rotate before the limit, carry the settings. D-070: every GitHub call passes the write budget.
- D-281: one PR at a time. D-054: no production change.

## Problema real
The channel grows toward a wall that stops every write, and the only door is a person rotating by hand and restoring the
settings. Resolved means: an append to the repository channel past `github_comment_limit - channel_warn_margin` opens the next
issue, carries the newest snapshot and the changes after it, writes one pointer line on the old issue, and every reader that
starts from the registry's issue follows the pointer.

## Lacunas
- Bumping the registry default to the newest issue saves a hop per process; it is a PR, so it stays a follow-up.
