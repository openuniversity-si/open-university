# BOARD (E2) — intake

## Pedido
Daniel's order of 01/11 14:12 BRT, unit E2, as A Torre sent it at about 15:30 BRT: "o quadro de comentário fixo — 5 ou 6
comentários editados por upsert_comment, cobrindo o estado que hoje se repete 79% das vezes. O que o E2 tem que provar: que o
comentário é reescrito e não acumulado; que um escritor concorrente não cria um segundo quadro (o upsert precisa achar o
existente); que um comentário apagado à mão se recria sem duplicar; e que o quadro cabe no limite de tamanho do GitHub, com o
excedente indo para o diário em ref, não para um comentário novo." At the close: the saving per hour, measured.

## Intenção
A person sees the flow's current state in a few comments that never grow, and the state machines stop paying a new comment
for every heartbeat.

## Contexto
- Issue #865 (the repository channel) held 1433 of 2500 comments at 15:3x BRT on 01/11.
- Measured on #865, 17h UTC (14h BRT) of 01/11: 106 comments in the hour; each of `train.batch.started`, `train.batch.shards`,
  `train.batch.green`, `train.queue.empty`, `integration.advanced`, `slo.breached`, `defect.verified` appeared in 13 or 14 of
  them; 19 comments in the three hours were this session's STATUS lines (not events).
- E1 merged (#1030): `forge_git_ref.GitRefAdapter` keeps an event log on `refs/heads/train/events` with no REST.
- `GitHubAdapter.upsert_comment` (GV1) edits in place the newest comment whose first line matches, else creates it; it searches
  only the newest `pages` pages (default 1), its find-or-create lock is per session, and a body above
  `forge-events.github_comment_max_chars` is split into continuation comments.

## Regras
- D-070: every engine GitHub call passes the write budget; refs only by create and fast-forward.
- D-277: five lanes; E2 is lane 1's. D-054: no production change. D-077, D-081: intake to plan before code.

## Problema real
The state kinds are appended as new comments, so the channel grows with the heartbeat; the existing upsert would duplicate a
board on a long issue, under two writers, and on an oversized body. Resolved means: the board kinds update a fixed set of
comments on the board issue (one per section, found, edited, never added), two writers converge to one comment per section, a
comment deleted by hand is recreated once, a section above the size limit is cut with its excess on a git ref, and the board
kinds make no new comment on the channel.

## Lacunas
- The board issue must exist and be named in `forge-events.board_issue`; creating it is one write, done once by an operator with
  the credential (A Torre). Until the key is set, nothing changes (the default is off).
- The single publisher and the account's write queue (E2's second half in the design, lane 6's W1) are not this unit; the board
  writes only when a section's text changes.
